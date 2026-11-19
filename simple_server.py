"""Dashboat v3 — lightweight web UI and actual Telegram lifecycle control."""
import asyncio
import base64
import hmac
import html
import json
import logging
import os
import re
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from storage import initialize, read, update
from telegram_monitor import TelegramMonitor

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)
# Avoid logging Bot API URLs, which include the secret BOT_TOKEN.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

_lock = threading.RLock()
_control_lock = threading.RLock()  # serialize start/stop/restart requests
_thread = None
_loop = None
_monitor = None
_state = 'stopped'
_message = ''
_cancel_requested = threading.Event()


def status(state, detail=''):
    global _state, _message
    with _lock:
        _state, _message = state, detail
    log.info('Monitor: %s %s', state, detail)
    if state == 'running' and not _cancel_requested.is_set():
        update(lambda d: d.update(monitoring_active=True))


def snapshot():
    with _lock:
        counts = dict(_monitor.counts) if _monitor else {'messages': 0, 'matches': 0, 'sent': 0}
        last = _monitor.last_message if _monitor else None
        return {'monitor': _state, 'detail': _message, 'counts': counts,
                'last_message': last, 'connected': bool(_monitor and _monitor.client and _monitor.client.is_connected())}


def worker():
    global _loop, _monitor, _thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        data = read()
        mon = TelegramMonitor(data['keywords'], data['groups'], status_callback=status)
        with _lock:
            _loop = loop
            _monitor = mon
        if _cancel_requested.is_set():
            status('stopped')
            return
        loop.run_until_complete(mon.start())
    except Exception as exc:
        log.exception('Telegram monitor failed')
        status('error', str(exc))
    finally:
        # Failed/disconnected workers must never leave the persistent auto-start flag on.
        # A deliberate user stop has already cleared it.
        update(lambda d: d.update(monitoring_active=False))
        with _lock:
            _loop = None
            _monitor = None
        loop.close()


def start_monitoring():
    global _thread
    with _control_lock, _lock:
        if _thread and _thread.is_alive():
            return
        data = read()
        if not data['keywords'] or not data['groups']:
            status('error', 'Сначала добавьте ключевые слова и группы')
            return
        _cancel_requested.clear()
        status('starting')
        # Only mark persistent auto-start after Telethon reports 'running'.
        _thread = threading.Thread(target=worker, daemon=True, name='dashboat-monitor')
        _thread.start()


def stop_monitoring():
    # A previous stop must complete before start_monitoring is permitted to run.
    with _control_lock:
        _cancel_requested.set()
        update(lambda d: d.update(monitoring_active=False))
        with _lock:
            loop, mon, thread = _loop, _monitor, _thread
        if thread and thread.is_alive():
            status('stopping')
            if loop and mon and loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(mon.stop(), loop)
                    future.result(timeout=15)
                except Exception:
                    log.exception('Monitor shutdown failed')
                    status('error', 'Не удалось остановить монитор; проверьте логи')
                    return False
            # Covers a stop pressed while the worker is creating its loop.
            thread.join(timeout=15)
            if thread.is_alive():
                status('error', 'Монитор не завершился за отведённое время')
                return False
        status('stopped')
        return True


def restart_monitoring():
    with _control_lock:
        if stop_monitoring():
            start_monitoring()


def parse_group_list(raw):
    """Split multiline/space/comma-separated group IDs and @usernames, preserving order."""
    result = []
    seen = set()
    invalid = []
    for item in re.split(r'[\s,;]+', raw.strip()):
        if not item:
            continue
        # Telegram supergroup / channel marked IDs, or public group usernames.
        if not (re.fullmatch(r'-100[0-9]{5,}', item) or
                re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{4,31}', item)):
            invalid.append(item)
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result, invalid


def esc(value):
    return html.escape(str(value), quote=True)


class Handler(BaseHTTPRequestHandler):
    def _respond(self, status_code, body, content_type='text/html; charset=utf-8', extra=None):
        raw = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def _authorized(self):
        password = os.environ.get('ADMIN_PASSWORD', '')
        if not password:
            self._respond(503, 'ADMIN_PASSWORD не задан в Render. Настройте переменную окружения.')
            return False
        header = self.headers.get('Authorization', '')
        try:
            decoded = base64.b64decode(header.split(' ', 1)[1], validate=True).decode('utf-8') if header.startswith('Basic ') else ''
        except (ValueError, UnicodeDecodeError, IndexError):
            decoded = ''
        expected = f'admin:{password}'
        if not hmac.compare_digest(decoded.encode(), expected.encode()):
            self._respond(401, 'Для управления Dashboat требуется вход.',
                          extra={'WWW-Authenticate': 'Basic realm="Dashboat Admin", charset="UTF-8"'})
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ('/', '/index.html', '/ping'):
            # Public HTTP 200 retained for existing UptimeRobot checks.
            self._respond(200, '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Dashboat</title>'
                         '<body><h2>Dashboat online</h2><p><a href="/dashboard">Панель управления</a></p></body></html>')
        elif path == '/health':
            info = snapshot()
            ok = info['monitor'] == 'running' and info['connected']
            self._respond(200 if ok else 503, json.dumps(info, ensure_ascii=False), 'application/json; charset=utf-8')
        elif path == '/dashboard':
            if self._authorized():
                self._respond(200, self.html())
        else:
            self._respond(404, 'Не найдено')

    def do_POST(self):
        if not self._authorized():
            return
        path = urllib.parse.urlsplit(self.path).path
        if not path.startswith('/api/'):
            self._respond(404, 'Не найдено')
            return
        # Reject cross-origin browser form submissions with saved Basic credentials.
        origin = self.headers.get('Origin')
        if origin:
            host = self.headers.get('Host', '')
            parsed = urllib.parse.urlsplit(origin)
            if parsed.netloc != host or parsed.scheme not in ('http', 'https'):
                self._respond(403, 'Недопустимый источник')
                return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            self._respond(415, 'Неверный формат запроса')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self._respond(400, 'Неверная длина запроса')
            return
        if length < 0:
            self._respond(400, 'Неверная длина запроса')
            return
        if length > 4096:
            self._respond(413, 'Слишком большой запрос')
            return
        params = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'))
        value = lambda key: params.get(key, [''])[0].strip()
        try:
            if path == '/api/add_keyword':
                kw = value('keyword').lower()[:100]
                if kw:
                    update(lambda d: d['keywords'].append(kw) if kw not in d['keywords'] else None)
            elif path == '/api/delete_keyword':
                kw = value('keyword')
                update(lambda d: d['keywords'].remove(kw) if kw in d['keywords'] else None)
            elif path == '/api/add_group':
                group = value('group')[:150]
                groups, invalid = parse_group_list(group)
                if invalid or len(groups) != 1:
                    self._respond(400, 'Укажите один корректный ID супергруппы или @username')
                    return
                update(lambda d: d['groups'].append(groups[0]) if groups[0] not in d['groups'] else None)
            elif path == '/api/add_groups_bulk':
                groups, invalid = parse_group_list(value('groups_bulk'))
                if invalid:
                    self._respond(400, 'Некорректные ID или @username: ' + esc(', '.join(invalid)))
                    return
                if not groups:
                    self._respond(400, 'Список пуст: вставьте ID групп или @username')
                    return
                def add_all(data):
                    existing = {g.lower() for g in data['groups']}
                    for group in groups:
                        if group.lower() not in existing:
                            data['groups'].append(group)
                            existing.add(group.lower())
                update(add_all)
            elif path == '/api/delete_group':
                group = value('group')
                update(lambda d: d['groups'].remove(group) if group in d['groups'] else None)
            elif path == '/api/start_monitoring':
                start_monitoring()
            elif path == '/api/stop_monitoring':
                stop_monitoring()
            elif path == '/api/restart_monitoring':
                restart_monitoring()
            elif path == '/api/clear_alerts':
                update(lambda d: d.update(alerts=[]))
            else:
                self._respond(404, 'Неизвестная команда')
                return
        except Exception:
            log.exception('Admin action failed')
            self._respond(500, 'Ошибка. Проверьте логи Render.')
            return
        self._respond(303, '', extra={'Location': '/dashboard'})

    def html(self):
        data = read()
        info = snapshot()
        state = info['monitor']
        labels = {'starting': 'ПОДКЛЮЧЕНИЕ', 'running': 'АКТИВЕН', 'stopping': 'ОСТАНОВКА',
                  'stopped': 'ОСТАНОВЛЕН', 'error': 'ОШИБКА'}
        color = '#138a46' if state == 'running' and info['connected'] else '#c0392b'
        def action(path, text, css='', hidden_name='', hidden_value=''):
            hidden = (f'<input type="hidden" name="{hidden_name}" value="{esc(hidden_value)}">'
                      if hidden_name else '')
            return (f'<form method="POST" action="{path}" class="inline">{hidden}'
                    f'<button class="btn {css}">{esc(text)}</button></form>')
        keywords = ''.join('<div class="item"><span>' + esc(k.upper()) + '</span>' +
                           action('/api/delete_keyword', '✕', 'danger', 'keyword', k) + '</div>'
                           for k in data['keywords']) or '<p>— нет ключевых слов —</p>'
        groups = ''.join('<div class="item"><span>' + esc(data['group_titles'].get(g, g)) +
                         (f' <small>({esc(g)})</small>' if data['group_titles'].get(g, g) != g else '') + '</span>' +
                         action('/api/delete_group', '✕', 'danger', 'group', g) + '</div>'
                         for g in data['groups']) or '<p>— нет групп —</p>'
        failed_groups = getattr(_monitor, 'failed_groups', {}) if _monitor else {}
        resolved_ids = getattr(_monitor, 'resolved_inputs', set()) if _monitor else set()
        connection_info = ('<p class="muted">Подключено: ' + str(len(resolved_ids)) +
                           ' из ' + str(len(data['groups'])) + '</p>') if state == 'running' else ''
        failed_html = ''.join('<div class="item"><span>⚠ ' + esc(g) +
                              '</span><small>' + esc(reason) + '</small></div>'
                              for g, reason in failed_groups.items())
        if failed_html:
            failed_html = '<h3>Недоступные группы</h3>' + failed_html
        matches_html = ''.join('<div class="alert"><b>' + esc(m.get('timestamp','')) + '</b> ' +
            ('<strong>ДУБЛЬ · уведомление не отправлено</strong>' if m.get('duplicate') else '<strong>Уведомление отправлено</strong>' if m.get('sent') else '<strong>Ошибка отправки</strong>') +
            '<p>' + esc(m.get('keyword','')) + ' · ' + esc(m.get('group','')) + '</p>' +
            ('<a target="_blank" rel="noopener noreferrer" href="' + esc(m.get('link','')) + '">Открыть объявление</a><p>' if m.get('link') else '<p>') +
            '<small>' + esc(str(m.get('message',''))[:300]) + '</small></p></div>'
            for m in reversed(data.get('matches_log', [])[-50:])) or '<p>Совпадений пока нет</p>'
        alerts = ''.join('<div class="alert"><b>' + esc(a.get('timestamp', '')) + '</b><p>' +
                         (f'<a target="_blank" rel="noopener noreferrer" href="{esc(a.get("link", ""))}">' if a.get('link') else '<span>') +
                         esc(str(a.get('keyword', '')).upper()) + ' → ' + esc(a.get('group', '')) +
                         ('</a>' if a.get('link') else '</span>') + '</p>' +
                         '<small>' + esc(str(a.get('message', ''))[:300]) + '</small></div>'
                         for a in reversed(data['alerts'][-20:])) or '<p>Алертов пока нет</p>'
        stats = info['counts']
        detail = esc(info['detail'])
        return f'''<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>Dashboat v3 — Батуми</title><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="20"><style>
body{{font-family:system-ui,Arial,sans-serif;background:#f5f7fa;color:#273143;margin:auto;padding:20px;max-width:900px}}
h1{{text-align:center;color:#1a5fb4}} .status{{font-size:1.8em;color:{color};font-weight:700;text-align:center}}
.section{{background:white;padding:20px;border-radius:14px;margin:20px 0;box-shadow:0 3px 12px #00000010}}
.btn{{background:#1a5fb4;color:white;border:0;border-radius:9px;padding:11px 17px;cursor:pointer;margin:5px}}
.danger{{background:#be3636}} .inline{{display:inline-block;margin:0}}.item{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eee;padding:7px;gap:12px;overflow-wrap:anywhere}}
input,textarea{{max-width:100%;box-sizing:border-box;padding:11px;border:1px solid #cbd2dc;border-radius:8px}}textarea{{width:100%;font:inherit;resize:vertical}}.alert{{border-left:4px solid #1a5fb4;padding:12px;margin:12px 0;background:#f6f9ff;overflow-wrap:anywhere}}
.stats{{display:flex;gap:16px;flex-wrap:wrap}}.stats span{{background:#eff4fb;padding:12px;border-radius:10px}}small,.muted{{color:#687486}}
</style></head><body><h1>Dashboat v3</h1><div class="status">{esc(labels.get(state, state))}</div>
<p style="text-align:center">{detail}</p><div style="text-align:center">
{action('/api/start_monitoring', 'ЗАПУСТИТЬ')}{action('/api/stop_monitoring', 'ОСТАНОВИТЬ', 'danger')}
{action('/api/restart_monitoring', 'ПЕРЕЗАПУСТИТЬ')}</div>
<div class="section"><div class="stats"><span>Групп: <b>{len(data['groups'])}</b></span><span>Сообщений: <b>{stats['messages']}</b></span><span>Совпадений: <b>{stats['matches']}</b></span><span>Отправлено: <b>{stats['sent']}</b></span></div>
<p class="muted">Последнее сообщение: {esc(info['last_message'] or '—')} (UTC). После изменения настроек нажмите «ПЕРЕЗАПУСТИТЬ».</p></div>
<div class="section"><h2>Ключевые слова</h2><form method="POST" action="/api/add_keyword"><input name="keyword" placeholder="mi band, айфон, macbook" required><button class="btn">+</button></form>{keywords}</div>
<div class="section"><h2>Группы</h2><form method="POST" action="/api/add_group"><input name="group" placeholder="-1001234567890 или @username" required><button class="btn">+</button></form>
<h3>Добавить список групп сразу</h3>
<form method="POST" action="/api/add_groups_bulk">
<textarea name="groups_bulk" rows="5" maxlength="3500" placeholder="Вставьте ID групп через пробел, запятую или с новой строки" required></textarea>
<button class="btn" type="submit">ДОБАВИТЬ ВСЕ ГРУППЫ</button></form>
<p class="muted">Повторяющиеся ID пропускаются. Уже сохранённые группы останутся. Чтобы применить новый список к Telegram, нажмите «ПЕРЕЗАПУСТИТЬ».</p>{connection_info}{failed_html}{groups}</div>
<div class="section"><h2>Просмотр совпадений (включая дубли)</h2><p class="muted">Повторные публикации отображаются здесь, даже если уведомление было подавлено. Последние 50 записей.</p>{matches_html}</div>
<div class="section"><h2>Последние алерты</h2>{action('/api/clear_alerts', 'ОЧИСТИТЬ АЛЕРТЫ', 'danger')}{alerts}</div>
<p class="muted">Dashboat v3 · Панель обновляется раз в 20 секунд</p></body></html>'''


if __name__ == '__main__':
    initialize()
    if read().get('monitoring_active'):
        start_monitoring()
    port = int(os.getenv('PORT', '10000'))
    log.info('Dashboat v3 listening on port %s', port)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
