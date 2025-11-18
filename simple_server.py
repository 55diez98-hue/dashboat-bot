# simple_server.py — АБСОЛЮТНО ФИНАЛЬНАЯ ВЕРСИЯ (v17) — 18.11.2025
import asyncio
import json
import os
import urllib.parse
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram_monitor import TelegramMonitor
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DATA_FILE = "dashboat_data.json"
monitor_thread = None


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            log.error("Повреждённый JSON — создаём новый")
            os.remove(DATA_FILE)
    return {"keywords": [], "groups": [], "alerts": [], "monitoring_active": False}


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)  # ← ИСПРАВЛЕНО!
    except Exception as e:
        log.error(f"Не удалось сохранить JSON: {e}")


def add_alert(alert):
    data = load_data()
    alert["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["alerts"].append(alert)
    data["alerts"] = data["alerts"][-100:]  # последние 100
    save_data(data)


def monitoring_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        data = load_data()
        if not data.get("keywords") or not data.get("groups"):
            log.warning("Нет ключей или групп — мониторинг не запускается")
            return

        monitor = TelegramMonitor(data["keywords"], data["groups"])
        monitor.set_callback(add_alert)
        log.info("[TELETHON] Запуск мониторинга...")
        try:
            await monitor.start()
        except Exception as e:
            log.error(f"[TELETHON] Ошибка: {e}")

    loop.run_until_complete(run())


def start_monitoring():
    global monitor_thread
    if monitor_thread and monitor_thread.is_alive():
        log.info("Мониторинг уже запущен")
        return

    data = load_data()
    data["monitoring_active"] = True
    save_data(data)

    monitor_thread = threading.Thread(target=monitoring_worker, daemon=True)
    monitor_thread.start()
    log.info("МОНИТОРИНГ ЗАПУЩЕН — Telethon работает в отдельном потоке!")


def stop_monitoring():
    data = load_data()
    data["monitoring_active"] = False
    save_data(data)
    log.info("Мониторинг остановлен (перезапусти для включения)")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.html().encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)

        if "/api/add_keyword" in self.path:
            kw = params.get("keyword", [""])[0].strip().lower()
            if kw:
                data = load_data()
                if kw not in data["keywords"]:
                    data["keywords"].append(kw)
                    save_data(data)

        elif "/api/add_group" in self.path:
            g = params.get("group", [""])[0].strip()
            if g:
                data = load_data()
                if g not in data["groups"]:
                    data["groups"].append(g)
                    save_data(data)

        elif "/api/delete_keyword" in self.path:
            kw = params.get("keyword", [""])[0]
            data = load_data()
            if kw in data["keywords"]:
                data["keywords"].remove(kw)
                save_data(data)

        elif "/api/delete_group" in self.path:
            g = params.get("group", [""])[0]
            data = load_data()
            if g in data["groups"]:
                data["groups"].remove(g)
                save_data(data)

        elif "/api/start_monitoring" in self.path:
            start_monitoring()

        elif "/api/stop_monitoring" in self.path:
            stop_monitoring()

        elif "/api/clear_alerts" in self.path:
            data = load_data()
            data["alerts"] = []
            save_data(data)

        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    def html(self):
        data = load_data()
        status_color = "green" if data.get("monitoring_active") else "red"
        status_text = "АКТИВЕН" if data.get("monitoring_active") else "ОСТАНОВЛЕН"

        kw_html = "<br>".join(data.get("keywords", [])) or "—"
        grp_html = "<br>".join(data.get("groups", [])) or "—"
        alerts = "".join(
            f'<div style="background:#fff;padding:15px;margin:10px 0;border-radius:10px;border-left:4px solid #1a5fb4">'
            f'<b>{a["timestamp"]}</b><br>'
            f'<a href="{a["link"]}" target="_blank"><b>{a["keyword"].upper()}</b> → {a["group"]}</a><br>'
            f'<small>{a["message"][:200]}...</small></div>'
            for a in reversed(data.get("alerts", [])[-10:])
        ) or "<p style='color:#888'>Алертов пока нет</p>"

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Dashboat v17 — Батуми</title>
<meta http-equiv="refresh" content="20">
<style>body{{font-family:system-ui;background:#f0f2f5;padding:20px;line-height:1.6}}
h1{{color:#1a5fb4}} button{{background:#1a5fb4;color:#fff;padding:14px 28px;border:none;border-radius:8px;font-size:1.2em;cursor:pointer}}
button:hover{{background:#0d47a1}} .status{{font-size:2em;font-weight:bold;color:{status_color}}}
</style></head><body>
<h1>Dashboat v17 — Батуми Барахолка</h1>
<p>Статус: <span class="status">{status_text}</span></p>

<form method="POST" action="/api/start_monitoring" style="display:inline"><button>ЗАПУСТИТЬ</button></form>
<form method="POST" action="/api/stop_monitoring" style="display:inline"><button style="background:#d32f2f">ОСТАНОВИТЬ</button></form>
<form method="POST" action="/api/clear_alerts" style="display:inline;margin-left:20px"><button style="background:#8B0000">ОЧИСТИТЬ АЛЕРТЫ</button></form>

<h2>Ключевые слова</h2>
<form method="POST" action="/api/add_keyword"><input name="keyword" placeholder="mi band, айфон, смартфон" required style="padding:12px;width:300px"><button>+</button></form>
<pre>{kw_html}</pre>

<h2>Группы</h2>
<form method="POST" action="/api/add_group"><input name="group" placeholder="-1001234567890" required style="padding:12px;width:300px"><button>+</button></form>
<pre>{grp_html}</pre>

<h2>Последние алерты</h2>
{alerts}
</body></html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    log.info(f"Сервер запущен на порту {port}")
    log.info("Дашборд: https://dashboat-bot.onrender.com")

    if load_data().get("monitoring_active"):
        start_monitoring()

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
