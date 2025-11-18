# telegram_monitor.py — v9.1 — ГАРАНТИРОВАННО РАБОТАЕТ с StringSession + алерты в дашборд и канал
import os
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID"))

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

# ГЛОБАЛЬНЫЙ callback, который будет переопределён из main.py
alert_callback = None

def set_callback(callback):
    global alert_callback
    alert_callback = callback

class TelegramMonitor:
    def __init__(self, keywords, groups):
        self.keywords = [k.lower() for k in keywords]
        self.groups = [int(g) for g in groups]

    async def start(self):
        log.info("[DASHBOAT v9.1] Запуск с StringSession...")
        await client.start()
        log.info("СЕССИЯ АКТИВНА — ГОТОВ ЛОВИТЬ!")

        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return
            text = event.message.message.lower()

            for kw in self.keywords:
                if kw in text:
                    try:
                        entity = await client.get_entity(event.chat_id)
                        title = getattr(entity, "title", "Unknown")
                    except:
                        title = "Unknown"

                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    alert_data = {
                        "keyword": kw,
                        "group": title,
                        "message": event.message.message[:200],
                        "link": link
                    }

                    # ← ВОТ ЭТО САМОЕ ВАЖНОЕ — два способа доставки
                    if alert_callback:
                        alert_callback(alert_data)                     # ← в дашборд
                    if bot and ALERT_CHAT_ID:
                        await bot.send_message(
                            chat_id=ALERT_CHAT_ID,
                            text=f"{kw.upper()} → {title}\n{link}",
                            disable_web_page_preview=True
                        )                                                     # ← в канал

        log.info(f"[DASHBOAT v9.1] Мониторим {len(self.groups)} групп — алерты включены!")
        await client.run_until_disconnected()
