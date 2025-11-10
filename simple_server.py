# simple_server.py
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import urllib.parse
from datetime import datetime
import threading
import asyncio
import socket
from telegram_monitor import TelegramMonitor

# === Настройки ===
DATA_FILE = "dashboat_data.json"
API_ID = 24777032
API_HASH = "12da668ad167c903820f8899ea202158"

monitor_instance = None
monitor_thread = None
monitor_loop = None


# === Работа с данными ===
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "groups" in data:
                    data["groups"] = [str(g).strip() for g in data["groups"]]
                return data
        except json.JSONDecodeError as e:
            print(f"[ОШИБКА] JSON повреждён: {e}")
            return {"keywords": [], "groups": [], "alerts": [], "monitoring_active": False}
    return {"keywords": [], "groups": [], "alerts": [], "monitoring_active": False}


def save_data(data):
    if "groups" in data:
        data["groups"] = [str(g).strip() for g in data["groups"]]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_alert(alert_data):
    data = load_data()
    alert_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["alerts"].append(alert_data)
    data["alerts"] = data["alerts"][-100:]
    save_data(data)
    print(f"ALERT: '{alert_data['keyword']}' в '{alert_data['group']}'")


# === Мониторинг ===
def run_monitor_async(api_id, api_hash, keywords, groups):
    global monitor_instance, monitor_loop
    monitor_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(monitor_loop)

    try:
        print(f"\n[MONITOR] Создаю TelegramMonitor...")
        print(f"   Ключевые слова: {keywords}")
        print(f"   Группы: {groups}")

        monitor_instance = TelegramMonitor(
            api_id=api_id,
            api_hash=api_hash,
            keywords=keywords,
            groups=groups,
            callback=add_alert
        )
        print("[MONITOR] TelegramMonitor создан")
        print("[MONITOR] Запускаю client.start()...")
        monitor_loop.run_until_complete(monitor_instance.start())

    except Exception as e:
        print(f"[ОШИБКА] В run_monitor_async: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if monitor_loop.is_running():
            monitor_loop.stop()
        monitor_loop.close()
        print("[MONITOR] Цикл закрыт")


def start_monitoring():
    global monitor_thread
    data = load_data()

    print(f"\n[START] Проверка данных:")
    print(f"   Ключевые слова: {data.get('keywords', [])}")
    print(f"   Группы: {data.get('groups', [])}")
    print(f"   monitoring_active: {data.get('monitoring_active')}")

    if not data.get("keywords"):
        print("[ОТКАЗ] Нет ключевых слов")
        return False
    if not data.get("groups"):
        print("[ОТКАЗ] Нет групп")
        return False
    if monitor_thread and monitor_thread.is_alive():
        print("[УЖЕ РАБОТАЕТ] Мониторинг уже запущен")
        return False

    print("[ЗАПУСК] Запускаю мониторинг...")
    monitor_thread = threading.Thread(
        target=run_monitor_async,
        args=(API_ID, API_HASH, data["keywords"], data["groups"]),
        daemon=True,
    )
    monitor_thread.start()
    print("[УСПЕХ] МОНИТОРИНГ УСПЕШНО ЗАПУЩЕН!\n")
    return True


def stop_monitoring():
    global monitor_instance, monitor_loop
    if monitor_instance and monitor_loop and monitor_loop.is_running():
        try:
            print("[ОСТАНОВКА] Останавливаю мониторинг...")
            future = asyncio.run_coroutine_threadsafe(monitor_instance.stop(), monitor_loop)
            future.result(timeout=10)
            print("[УСПЕХ] Мониторинг остановлен")
        except Exception as e:
            print(f"[ОШИБКА] При остановке: {e}")
    else:
        print("[ИНФО] Мониторинг не запущен")
    return True


# === Dashboard ===
class DashboardHandler(BaseHTTPRequestHandler):

    def do_HEAD(self):
        """Поддержка HEAD-запросов от UptimeRobot"""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        if self.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.get_html_page().encode("utf-8"))
        elif self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_data(), ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")
        params = urllib.parse.parse_qs(post_data)

        print(f"\n[POST] Путь: {self.path}")
        print(f"[POST] Данные: {params}")

        data = load_data()
        path = self.path

        if path == "/api/add_keyword":
            kw = params.get("keyword", [""])[0].strip().lower()
            if kw and kw not in data["keywords"]:
                data["keywords"].append(kw)
                save_data(data)
                print(f"[ДОБАВЛЕНО] Ключевое слово: {kw}")

        elif path == "/api/add_group":
            grp = params.get("group", [""])[0].strip()
            if grp and grp not in data["groups"]:
                data["groups"].append(grp)
                save_data(data)
                print(f"[ДОБАВЛЕНО] Группа: {grp}")

        elif path == "/api/delete_keyword":
            kw = params.get("keyword", [""])[0]
            if kw in data["keywords"]:
                data["keywords"].remove(kw)
                save_data(data)

        elif path == "/api/delete_group":
            grp = params.get("group", [""])[0]
            if grp in data["groups"]:
                data["groups"].remove(grp)
                save_data(data)

        elif path == "/api/start_monitoring":
            print("[КНОПКА] Нажата START")
            if start_monitoring():
                data["monitoring_active"] = True
                save_data(data)
                print("[УСПЕХ] monitoring_active = True")

        elif path == "/api/stop_monitoring":
            print("[КНОПКА] Нажата STOP")
            stop_monitoring()
            data["monitoring_active"] = False
            save_data(data)

        elif path == "/api/clear_alerts":
            data["alerts"] = []
            save_data(data)
            print("[ОЧИЩЕНО] Алерты удалены")

        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    def get_html_page(self):
        data = load_data()
        status_color = "green" if data.get("monitoring_active") else "red"
        status_text = "Активен" if data.get("monitoring_active") else "Остановлен"

        keywords_html = "".join(
            f'<li>{kw} <form method="POST" action="/api/delete_keyword" style="display:inline">'
            f'<input type="hidden" name="keyword" value="{kw}"><button>Delete</button></form></li>'
            for kw in data.get("keywords", [])
        ) or "<li>Нет ключевых слов</li>"

        groups_html = "".join(
            f'<li>{grp} <form method="POST" action="/api/delete_group" style="display:inline">'
            f'<input type="hidden" name="group" value="{grp}"><button>Delete</button></form></li>'
            for grp in data.get("groups", [])
        ) or "<li>Нет групп</li>"

        alerts = data.get("alerts", [])[-10:]
        alerts_html = "".join(
            f"<div style='border:1px solid #ddd;padding:10px;margin:5px;border-radius:5px;'>"
            f"<b>{a['timestamp']}</b> — <b>{a['keyword']}</b> в <i>{a['group']}</i><br>"
            f"{a['message'][:200]}{'...' if len(a['message']) > 200 else ''}</div>"
            for a in alerts
        ) or "<p>Нет оповещений</p>"

        return f"""
        <html><head>
        <meta charset="utf-8">
        <title>Dashboat</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ font-family: Arial; max-width: 800px; margin:auto; background:#fafafa; padding:20px; }}
            h1 {{ color:#333; }}
            button {{ background:#007bff; color:white; border:none; border-radius:4px; padding:8px 16px; margin:5px; }}
            input[type=text] {{ padding:8px; border-radius:4px; border:1px solid #ccc; width:200px; }}
            .status {{ font-weight:bold; color:{status_color}; }}
        </style>
        </head><body>
        <h1>Dashboat Dashboard</h1>
        <p>Статус: <span class="status">{status_text}</span></p>

        <form method="POST" action="/api/start_monitoring" style="display:inline">
            <button>Start</button>
        </form>
        <form method="POST" action="/api/stop_monitoring" style="display:inline">
            <button>Stop</button>
        </form>

        <h2>Ключевые слова</h2>
        <form method="POST" action="/api/add_keyword">
            <input type="text" name="keyword" placeholder="Например: масляный" required>
            <button>Add</button>
        </form>
        <ul>{keywords_html}</ul>

        <h2>Группы (ID)</h2>
        <form method="POST" action="/api/add_group">
            <input type="text" name="group" placeholder="-1001234567890" required>
            <button>Add</button>
        </form>
        <ul>{groups_html}</ul>

        <h2>Последние оповещения</h2>
        <form method="POST" action="/api/clear_alerts">
            <button style="background:#dc3545">Очистить</button>
        </form>
        {alerts_html}

        <p style="color:#888; margin-top:50px; font-size:0.9em;">
            Dashboat v2.0 | Автообновление каждые 10 сек
        </p>
        </body></html>
        """


# === Запуск сервера ===
def get_free_port(default=5000, max_tries=20):
    for i in range(max_tries):
        port = default + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return default


def run_server():
    port = get_free_port()
    print(f"\nDASHBOARD: http://0.0.0.0:{port}")
    print("Откройте Preview в Replit\n")

    # Автозапуск при старте
    data = load_data()
    if data.get("monitoring_active") and data.get("keywords") and data.get("groups"):
        print("[АВТОЗАПУСК] Запускаю мониторинг при старте...")
        start_monitoring()

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    run_server()