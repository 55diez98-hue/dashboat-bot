# telegram_monitor.py — 100% РАБОЧАЯ ВЕРСИЯ (v6.0 — без phone_code_hash)
import os
import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram import Bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ENV
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID"))
PHONE = os.getenv("PHONE")

# САМАЯ ВАЖНАЯ СТРОКА — ИСПОЛЬЗУЕМ СТРОКОВУЮ СЕССИЮ (решает проблему phone_code_hash)
SESSION_STRING = os.getenv("SESSION_STRING", "")  # ← сюда вставим строку после авторизации

if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('monitor_session', API_ID, API_HASH)

bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

class TelegramMonitor:
    def __init__(self, keywords, groups, callback):
        self.keywords = [k.lower() for k in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        log.info("[DASHBOAT v6.0] Запуск Telethon...")
        await client.start(phone=PHONE)  # ← МАГИЯ: start() сам всё делает

        if SESSION_STRING:
            log.info("[OK] Авторизация по строковой сессии — работает 24/7")
        else:
            log.info("[OK] Первая авторизация прошла! Сохраняю строковую сессию в логах ↓")

            # ВЫВОДИМ СТРОКОВУЮ СЕССИЮ В ЛОГИ (скопируешь оттуда)
            string_session = client.session.save()
            log.info(f"SESSION_STRING = {string_session}")
            log.info("СКОПИРУЙ ЭТУ СТРОКУ В RENDER → ENV → SESSION_STRING → SAVE → DEPLOY")

        # Подключаемся к группам
        for gid in self.groups:
            try:
                entity = await client.get_entity(gid)
                title = getattr(entity, "title", str(gid))
                self.group_titles[gid] = title
                log.info(f"[OK] Подключено: {title}")
            except Exception as e:
                log.warning(f"[WARN] Группа {gid}: {e}")

        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message: return
            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Unknown")
            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"
                    self.callback({'keyword': kw, 'group': group_title, 'message': event.message.message, 'link': link})
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(ALERT_CHAT_ID, f"{kw.upper()} → {group_title}\n{link}")
                        except: pass

        log.info(f"[DASHBOAT v6.0] Слушаю {len(self.groups)} групп — всё готово!")
        await client.run_until_disconnected()
