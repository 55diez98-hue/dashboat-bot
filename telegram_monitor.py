# telegram_monitor.py — ФИНАЛЬНАЯ РАБОЧАЯ ВЕРСИЯ (v5.3)
import os
import logging
from telethon import TelegramClient, events
from telegram import Bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID"))
PHONE = os.getenv("PHONE")
CODE = os.getenv("CODE", "").strip()

client = TelegramClient('monitor_session', API_ID, API_HASH)
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

class TelegramMonitor:
    def __init__(self, keywords, groups, callback):
        self.keywords = [k.lower() for k in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        log.info("[MONITOR] Запуск Telethon...")
        await client.connect()

        if not await client.is_user_authorized():
            if not CODE:
                log.info(f"[MONITOR] Отправляю код на {PHONE}...")
                await client.send_code_request(PHONE)
                log.info("КОД ОТПРАВЛЕН! Введи его в Render → CODE → Deploy")
                raise Exception("Жду CODE")
            else:
                log.info("[MONITOR] Ввожу код и завершаю авторизацию...")
                await client.sign_in(PHONE, code=CODE)  # ← ВАЖНО: code=CODE
                log.info("АВТОРИЗОВАН НАВСЕГДА! Сессия сохранена.")

        log.info("[DASHBOAT v5.3] АВТОРИЗОВАН. ГОТОВ К БОЮ 24/7")

        # Подключение к группам
        for gid in self.groups:
            try:
                entity = await client.get_entity(gid)
                title = getattr(entity, "title", str(gid))
                self.group_titles[gid] = title
                log.info(f"[OK] Подключено: {title}")
            except Exception as e:
                log.error(f"[FAIL] Группа {gid}: {e}")

        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message: return
            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Неизвестно")
            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"
                    self.callback({'keyword': kw, 'group': group_title, 'message': event.message.message, 'link': link})
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(ALERT_CHAT_ID, f"{kw.upper()} → {group_title}\n{link}", disable_web_page_preview=True)
                        except: pass

        log.info(f"[DASHBOAT] Слушаю {len(self.groups)} групп. Алерты летят!")
        await client.run_until_disconnected()
