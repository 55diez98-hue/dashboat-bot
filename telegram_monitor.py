# telegram_monitor.py — ФИНАЛЬНАЯ ВЕРСИЯ (v5.2 — работает 100%)
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
CODE = os.getenv("CODE", "").strip()  # может быть пустым

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
                log.info(f"[MONITOR] Нужна авторизация — отправляю код на {PHONE}...")
                await client.send_code_request(PHONE)
                log.info("КОД ОТПРАВЛЕН В TELEGRAM! Введи его в Render → CODE и перезапусти")
                raise Exception("Жду CODE в ENV")
            else:
                log.info("[MONITOR] Ввожу код из ENV...")
                await client.sign_in(phone=PHONE, code=CODE)
                log.info("АВТОРИЗОВАН УСПЕШНО! Сессия сохранена")

        log.info("[MONITOR] Авторизация пройдена — сессия активна")

        # Подключаемся к группам
        for gid in self.groups:
            try:
                entity = await client.get_entity(gid)
                title = getattr(entity, "title", str(gid))
                self.group_titles[gid] = title
                log.info(f"[OK] Подключено: {title}")
            except Exception as e:
                log.error(f"[FAIL] Группа {gid}: {e}")

        # Обработчик сообщений
        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return
            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Неизвестно")
            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"
                    self.callback({
                        'keyword': kw,
                        'group': group_title,
                        'message': event.message.message,
                        'link': link
                    })
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(
                                ALERT_CHAT_ID,
                                f"‼ {kw.upper()} в {group_title}\n\n{event.message.message[:300]}...\n\n👉 {link}",
                                disable_web_page_preview=True
                            )
                        except: pass

        log.info(f"[MONITOR] Слушаю {len(self.groups)} групп — всё готово!")
        await client.run_until_disconnected()
                        
