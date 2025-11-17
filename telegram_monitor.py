# telegram_monitor.py — v9.0 — финальная, 100% работает 24/7 на Render
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

class TelegramMonitor:
    def __init__(self, keywords, groups, callback):
        self.keywords = [k.lower() for k in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        log.info("[DASHBOAT v9.0] Запуск с строковой сессией...")
        await client.start()
        log.info("АВТОРИЗОВАН НАВСЕГДА — СЕССИЯ ЖИВАЯ!")

        # Получаем названия групп
        for gid in self.groups:
            try:
                entity = await client.get_entity(gid)
                title = getattr(entity, "title", str(gid))
                self.group_titles[gid] = title
                log.info(f"[OK] Подключено: {title}")
            except Exception as e:
                log.error(f"[FAIL] Группа {gid} — {e}")

        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return
            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Unknown")
            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"
                    self.callback({
                        'keyword': kw,
                        'group': group_title,
                        'message': event.message.message[:100],
                        'link': link
                    })
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(
                                ALERT_CHAT_ID,
                                f"{kw.upper()} → {group_title}\n{link}",
                                disable_web_page_preview=True
                            )
                        except: pass

        log.info(f"[DASHBOAT v9.0] Мониторинг {len(self.groups)} групп запущен — АЛЕРТЫ ЛЕТЯТ!")
        await client.run_until_disconnected()
