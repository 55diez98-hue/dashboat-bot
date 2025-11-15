# simple_server.py
import threading
import asyncio
import json
import os
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram_monitor import TelegramMonitor

# === ENV ===
DATA_FILE = "dashboat_data.json"
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID")

if not all([API_ID, API_HASH, BOT_TOKEN, ALERT_CHAT_ID]):
    print("[ОШИБКА] Установите API_ID, API_HASH, BOT_TOKEN, ALERT_CHAT_ID в Render")
    exit(1)

monitor = None

# === Данные ===
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["groups"] = [str(g).strip() for g in data.get("groups", [])]
                return data
        except: pass
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

# === Мониторинг ===
async def run_monitoring():
    global monitor
    data = load_data()
    if not data["keywords"] or not data["groups"]:
        return

    monitor = TelegramMonitor(
        keywords=data["keywords"],
        groups=data["groups"],
        callback=add_alert
    )
    await monitor.start()

def start_monitoring():
    data = load_data()
    if data["monitoring_active"]: return
    data["monitoring_active"] = True
    save_data(data)
    threading.Thread(target=lambda: asyncio.run(run_monitoring()), daemon=True).start()

def stop_monitoring():
    global monitor
    data = load_data()
    data["monitoring_active"] = False
    save_data(data)
    if monitor:
        asyncio.run_coroutine_threadsafe(monitor.stop(), asyncio.get_event_loop())

# === HTTP ===
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.html().encode("utf-8"))
        elif self.path == "/api/data":
            self.send_json(load_data())
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)
        data = load_data()

        if self.path == "/api/add_keyword":
            kw = params.get("keyword", [""])[0].strip().lower()
            if kw and kw not in data["keywords"]:
                data["keywords"].append(kw); save_data(data)
        elif self.path == "/api/add_group":
            g = params.get("group", [""])[0].strip()
            if g and g not in data["groups"]:
                data["groups"].append(g); save_data(data)
        elif self.path == "/api/delete_keyword":
            kw = params.get("keyword", [""])[0]
            if kw in data["keywords"]:
                data["keywords"].remove(kw); save_data(data)
        elif self.path == "/api/delete_group":
            g = params.get("group", [""])[0]
            if g in data["groups"]:
                data["groups"].remove(g); save_data(data)
        elif self.path == "/api/start_monitoring":
            start_monitoring()
        elif self.path == "/api/stop_monitoring":
            stop_monitoring()
        elif self.path == "/api/clear_alerts":
            data["alerts"] = []; save_data(data)

        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def html(self):
        data = load_data()
        status = "green">Активен' if data.get("monitoring_active") else "red">Остановлен"
        kw_html = "".join(
            f'<li>{kw} <form method="POST" action="/api/delete_keyword" style="display:inline">'
            f'<input type="hidden" name="keyword" value="{kw}"><button>×</button></form></li>'
            for kw in data["keywords"]
        ) or "<li>—</li>"

        grp_html = "".join(
            f'<li>{g} <form method="POST" action="/api/delete_group" style="display:inline">'
            f'<input type="hidden" name="group" value="{g}"><button>×</button></form></li>'
            for g in data["groups"]
        ) or "<li>—</li>"

        alerts = "".join(
            f'<div style="border:1px solid #ddd;padding:8px;margin:5px;border-radius:4px">'
            f'<b>{a["timestamp"]}</b> — <a href="{a["link"]}" target="_blank">{a["keyword"]} в {a["group"]}</a><br>'
            f'<small>{a["message"][:150]}{"..." if len(a["message"])>150 else ""}</small></div>'
            for a in data["alerts"][-10:]
        ) or "<p>Нет алертов</p>"

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Dashboat</title>
<meta http-equiv="refresh" content="10">
<style>body{{font-family:Arial;max-width:800px;margin:40px auto;background:#f9f9f9;padding:20px}}
button{{background:#007bff;color:#fff;border:none;padding:8px 16px;border-radius:4px;margin:5px;cursor:pointer}}
input[type=text]{{padding:8px;border:1px solid #ccc;border-radius:4px;width:220px}}
</style></head><body>
<h1>Dashboat</h1>
<p>Статус: <b style="color:{status}</p>

<form method="POST" action="/api/start_monitoring" style="display:inline"><button>Запустить</button></form>
<form method="POST" action="/api/stop_monitoring" style="display:inline"><button>Остановить</button></form>

<h2>Ключевые слова</h2>
<form method="POST" action="/api/add_keyword"><input name="keyword" placeholder="масляный" required><button>+</button></form>
<ul>{kw_html}</ul>

<h2>Группы (ID)</h2>
<form method="POST" action="/api/add_group"><input name="group" placeholder="-1001234567890" required><button>+</button></form>
<ul>{grp_html}</ul>

<h2>Алерты</h2>
<form method="POST" action="/api/clear_alerts"><button style="background:#dc3545">Очистить</button></form>
{alerts}

<p style="color:#888;font-size:0.9em;margin-top:50px">Dashboat v4 | @Shmelibze | Батуми</p>
</body></html>"""

# === Запуск ===
def run_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"[SERVER] Запуск на 0.0.0.0:{port}")

    # Автозапуск
    data = load_data()
    if data.get("monitoring_active"):
        start_monitoring()

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

if __name__ == "__main__":
    run_server()
