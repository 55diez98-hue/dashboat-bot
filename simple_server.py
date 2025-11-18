# simple_server.py — ФИНАЛЬНАЯ РАБОЧАЯ ВЕРСИЯ (18.11.2025)
# Работает на Render. Запуск в отдельном потоке. Никаких RuntimeError: no running event loop
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
                data = json.load(f)
                data["groups"] = [str(g).strip() for g in data.get("groups", [])]
                return data
        except Exception as e:
            log.error(f"Ошибка чтения dashboat_data.json: {e}")
    return {"keywords": [], "groups": [], "alerts": [], "monitoring_active": False}


def save_data(data):
    data["groups"] = [str(g).strip() for g in data["groups"]]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_alert(alert):
    data = load_data()
    alert["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["alerts"].append(alert)
    data["alerts"] = data["alerts"][-100:]
    save_data(data)


# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
#  ЭТО ГЛАВНОЕ — МОНИТОРИНГ В ОТДЕЛЬНОМ ПОТОКЕ С СОБСТВЕННЫМ LOOP
def monitoring_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def runner():
        data = load_data()
        if not data["keywords"] or not data["groups"]:
            log.warning("Нет ключевых слов или групп — мониторинг не стартует")
            return

        log.info("[MONITOR] Запускаем TelegramMonitor в отдельном потоке")
        monitor = TelegramMonitor(data["keywords"], data["groups"])
        monitor.set_callback(add_alert)
        await monitor.start()   # ← здесь тесты и вся работа

    try:
        loop.run_until_complete(runner())
    except Exception as e:
        log.error(f"[КРИТ] Ошибка в мониторинге: {e}")
    finally:
        loop.close()


def start_monitoring():
    global monitor_thread
    if monitor_thread and monitor_thread.is_alive():
        log.info("[MONITOR] Уже работает")
        return

    data = load_data()
    data["monitoring_active"] = True
    save_data(data)

    monitor_thread = threading.Thread(target=monitoring_worker, daemon=True)
    monitor_thread.start()
    log.info("[MONITOR] УСПЕШНО ЗАПУЩЕН В ОТДЕЛЬНОМ ПОТОКЕ — Telethon стартует!")


def stop_monitoring():
    global monitor_thread
    data = load_data()
    data["monitoring_active"] = False
    save_data(data)

    if monitor_thread and monitor_thread.is_alive():
        # Telethon сам завершится при отключении клиента
        log.info("[MONITOR] Остановка...")
        # ничего больше не делаем — поток завершится сам
    monitor_thread = None
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←


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

        if self.path == "/api/add_keyword":
            kw = params.get("keyword", [""])[0].strip().lower()
            if kw and kw not in load_data()["keywords"]:
                data = load_data()
                data["keywords"].append(kw)
                save_data(data)

        elif self.path == "/api/add_group":
            g = params.get("group", [""])[0].strip()
            if g and g not in load_data()["groups"]:
                data = load_data()
                data["groups"].append(g)
                save_data(data)

        elif self.path == "/api/delete_keyword":
            kw = params.get("keyword", [""])[0]
            data = load_data()
            if kw in data["keywords"]:
                data["keywords"].remove(kw)
                save_data(data)

        elif self.path == "/api/delete_group":
            g = params.get("group", [""])[0]
            data = load_data()
            if g in data["groups"]:
                data["groups"].remove(g)
                save_data(data)

        elif self.path == "/api/start_monitoring":
            start_monitoring()

        elif self.path == "/api/stop_monitoring":
            stop_monitoring()

        elif self.path == "/api/clear_alerts":
            data = load_data()
            data["alerts"] = []
            save_data(data)

        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    def html(self):
        data = load_data()
        status_color = "green" if data.get("monitoring_active") else "red"
        status_text = "Активен" if data.get("monitoring_active") else "Остановлен"

        kw_html = "".join(
            f'<li>{kw} <form method="POST" action="/api/delete_keyword" style="display:inline">'
            f'<input type="hidden" name="keyword" value="{kw}"><button type="submit">×</button></form></li>'
            for kw in data["keywords"]
        ) or "<li>—</li>"

        grp_html = "".join(
            f'<li>{g} <form method="POST" action="/api/delete_group" style="display:inline">'
            f'<input type="hidden" name="group" value="{g}"><button type="submit">×</button></form></li>'
            for g in data["groups"]
        ) or "<li>—</li>"

        alerts = "".join(
            f'<div style="border:1px solid #ddd;padding:12px;margin:10px 0;border-radius:8px;background:#fff">'
            f'<b>{a["timestamp"]}</b><br>'
            f'<a href="{a["link"]}" target="_blank">{a["keyword"].upper()} → {a["group"]}</a><br>'
            f'<small>{a["message"][:150]}{"..." if len(a["message"])>150 else ""}</small></div>'
            for a in reversed(data["alerts"][-15:])
        ) or "<p style='color:#888'>Нет алертов</p>"

        return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Dashboat v12</title>
<meta http-equiv="refresh" content="15">
<style>
  body {{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;background:#f0f2f5;padding:20px;line-height:1.5}}
  h1 {{color:#1a5fb4}}
  button {{background:#1a5fb4;color:white;border:none;padding:10px 18px;border-radius:8px;cursor:pointer}}
  button:hover {{background:#0d47a1}}
  input[type=text] {{padding:10px;width:300px;border-radius:8px;border:1px solid #ccc}}
  ul {{list-style:none;padding:0}}
  li {{background:white;padding:10px;margin:5px 0;border-radius:8px;display:flex;justify-content:space-between;align-items:center}}
  .status {{font-weight:bold;color:{status_color}}}
</style></head><body>
<h1>Dashboat v12 — Батуми</h1>
<p>Статус мониторинга: <span class="status">{status_text}</span></p>

<form method="POST" action="/api/start_monitoring" style="display:inline"><button>ЗАПУСТИТЬ</button></form>
<form method="POST" action="/api/stop_monitoring" style="display:inline"><button>Остановить</button></form>
<form method="POST" action="/api/clear_alerts" style="display:inline;margin-left:15px"><button style="background:#d32f2f">Очистить алерты</button></form>

<h2>Ключевые слова</h2>
<form method="POST" action="/api/add_keyword"><input name="keyword" placeholder="масляный" required><button>+</button></form>
<ul>{kw_html}</ul>

<h2>Группы (ID)</h2>
<form method="POST" action="/api/add_group"><input name="group" placeholder="-1001234567890" required><button>+</button></form>
<ul>{grp_html}</ul>

<h2>Алерты (последние 15)</h2>
{alerts}

<div style="margin-top:100px;color:#888;font-size:0.9em;text-align:center">
Dashboat v12 | @Shmelibze | Батуми 2025
</div>
</body></html>"""


def run_server():
    port = int(os.environ.get("PORT", 10000))
    log.info(f"[SERVER] Запуск на порту {port}")
    log.info(f"[DASHBOARD] https://dashboat-bot.onrender.com")

    if load_data().get("monitoring_active"):
        start_monitoring()

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    run_server()
