# simple_server.py — DASHBORD v1.0 (18.11.2025) — Батуми Барахолка
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
        except:
            os.remove(DATA_FILE)
    return {"keywords": [], "groups": [], "alerts": [], "monitoring_active": False}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_alert(alert):
    data = load_data()
    alert["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["alerts"].append(alert)
    data["alerts"] = data["alerts"][-100:]
    save_data(data)


def monitoring_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    data = load_data()
    if not data.get("keywords") or not data.get("groups"):
        return
    monitor = TelegramMonitor(data["keywords"], data["groups"])
    monitor.set_callback(add_alert)
    loop.run_until_complete(monitor.start())


def start_monitoring():
    global monitor_thread
    if monitor_thread and monitor_thread.is_alive():
        return
    data = load_data()
    data["monitoring_active"] = True
    save_data(data)
    monitor_thread = threading.Thread(target=monitoring_worker, daemon=True)
    monitor_thread.start()
    log.info("DASHBORD ЗАПУЩЕН — мониторинг активен 24/7")


def stop_monitoring():
    global monitor_thread
    data = load_data()
    data["monitoring_active"] = False
    save_data(data)
    monitor_thread = None


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

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
            if kw:
                data = load_data()
                if kw not in data["keywords"]:
                    data["keywords"].append(kw)
                    save_data(data)

        elif self.path == "/api/add_group":
            g = params.get("group", [""])[0].strip()
            if g:
                data = load_data()
                if g not in data["groups"]:
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
        status_color = "green" if data.get("monitoring_active") else "#d32f2f"
        status_text = "АКТИВЕН" if data.get("monitoring_active") else "ОСТАНОВЛЕН"

        # Ключевые слова с кнопкой удаления
        kw_html = "".join(
            f'<div style="background:#fff;padding:12px;margin:6px 0;border-radius:8px;display:flex;justify-content:space-between;align-items:center">'
            f'{kw.upper()} '
            f'<form method="POST" action="/api/delete_keyword" style="margin:0">'
            f'<input type="hidden" name="keyword" value="{kw}">'
            f'<button type="submit" style="background:#d32f2f;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:0.9em">✕</button></form></div>'
            for kw in data["keywords"]
        ) or "<div style='color:#888;padding:20px'>— нет ключевых слов —</div>"

        # Группы с кнопкой удаления
        grp_html = "".join(
            f'<div style="background:#fff;padding:12px;margin:6px 0;border-radius:8px;display:flex;justify-content:space-between;align-items:center">'
            f'{g} '
            f'<form method="POST" action="/api/delete_group" style="margin:0">'
            f'<input type="hidden" name="group" value="{g}">'
            f'<button type="submit" style="background:#d32f2f;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:0.9em">✕</button></form></div>'
            for g in data["groups"]
        ) or "<div style='color:#888;padding:20px'>— нет групп —</div>"

        # Алерты
        alerts = "".join(
            f'<div style="background:#fff;padding:16px;margin:12px 0;border-radius:12px;border-left:5px solid #1a5fb4">'
            f'<b style="color:#1a5fb4">{a["timestamp"]}</b><br>'
            f'<a href="{a["link"]}" target="_blank" style="color:#1a5fb4;font-weight:bold">{a["keyword"].upper()} → {a["group"]}</a><br>'
            f'<small style="color:#555">{a["message"][:250]}{"..." if len(a["message"])>250 else ""}</small>'
            f'</div>'
            for a in reversed(data.get("alerts", [])[-20:])
        ) or '<div style="text-align:center;color:#888;padding:40px">Алертов пока нет</div>'

        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Dashbord — Батуми Барахолка</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="20">
    <style>
        body {{font-family:system-ui;background:#f5f7fa;padding:20px;color:#333;line-height:1.6}}
        h1 {{color:#1a5fb4;text-align:center;margin-bottom:10px}}
        .status {{font-size:2em;font-weight:bold;color:{status_color};text-align:center;display:block;margin:10px 0}}
        .btn {{padding:14px 28px;border:none;border-radius:10px;color:#fff;font-size:1.1em;cursor:pointer;margin:8px}}
        .btn-start {{background:#1a5fb4}}
        .btn-stop {{background:#d32f2f}}
        .btn-clear {{background:#8B0000}}
        input[type=text] {{padding:14px;width:100%;max-width:400px;border-radius:10px;border:1px solid #ccc;font-size:1.1em;margin:10px 0}}
        .section {{background:#fff;padding:20px;border-radius:16px;margin:20px 0;box-shadow:0 4px 12px rgba(0,0,0,0.05)}}
        footer {{text-align:center;color:#888;margin-top:60px;font-size:0.9em}}
    </style>
</head>
<body>
    <h1>Dashbord</h1>
    <div class="status">{status_text}</div>

    <div style="text-align:center">
        <form method="POST" action="/api/start_monitoring" style="display:inline"><button class="btn btn-start">ЗАПУСТИТЬ</button></form>
        <form method="POST" action="/api/stop_monitoring" style="display:inline"><button class="btn btn-stop">ОСТАНОВИТЬ</button></form>
        <form method="POST" action="/api/clear_alerts" style="display:inline"><button class="btn btn-clear">ОЧИСТИТЬ АЛЕРТЫ</button></form>
    </div>

    <div class="section">
        <h2>Ключевые слова</h2>
        <form method="POST" action="/api/add_keyword">
            <input name="keyword" placeholder="например: mi band, айфон, macbook" required>
            <button class="btn btn-start">+</button>
        </form>
        {kw_html}
    </div>

    <div class="section">
        <h2>Группы</h2>
        <form method="POST" action="/api/add_group">
            <input name="group" placeholder="-1001234567890" required>
            <button class="btn btn-start">+</button>
        </form>
        {grp_html}
    </div>

    <div class="section">
        <h2>Последние алерты</h2>
        {alerts}
    </div>

    <footer>
        Dashbord v1.0 — Батуми Барахолка 2025<br>
        @Shmelibze — король барахолки
    </footer>
</body>
</html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    log.info(f"DASHBORD запущен → https://dashboat-bot.onrender.com")
    if load_data().get("monitoring_active"):
        start_monitoring()
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
