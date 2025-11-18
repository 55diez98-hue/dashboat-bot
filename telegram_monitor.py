# telegram_monitor.py — ФИНАЛЬНАЯ ВЕРСИЯ (18.11.2025) — алерты и в канал, и в дашборд
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
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID")) if os.getenv("ALERT_CHAT_ID") else None

if not all([API_ID, API_HASH, SESSION_STRING]):
    raise ValueError("Нужны API_ID, API_HASH, SESSION_STRING!")

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

class TelegramMonitor:
    def __init__(self, keywords, groups):
        self.keywords = [k.lower() for k in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = None
        self.group_titles = {}

    def set_callback(self, callback):
        self.callback = callback

    async def start(self):
        log.info("[DASHBOAT] Подключение Telethon...")
        await client.start()
        log.info("[SUCCESS] Telethon подключился!")

        # Тестовые сообщения
        try:
            me = await client.get_me()
            log.info(f"[ТЕСТ] Аккаунт: {me.first_name} @{me.username}")
            await client.send_message("me", "DASHBOAT v12 ЗАПУЩЕН — всё работает! 18.11.2025")
            if bot and ALERT_CHAT_ID:
                await bot.send_message(ALERT_CHAT_ID, "DASHBOAT v12 онлайн — алерты летят и в дашборд, и в канал!")
            log.info("[ТЕСТ] Тестовые сообщения отправлены")
        except Exception as e:
            log.error(f"[ТЕСТ] Ошибка теста: {e}")

        # Подключаем группы
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
            if not event.message or not event.message.message:
                return
            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Unknown")
            log.info(f"[НОВОЕ] {group_title}: {event.message.message[:70]}")

            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    log.info(f"АЛЕРТ! «{kw.upper()}» в {group_title}")

                    alert_data = {
                        "keyword": kw,
                        "group": group_title,
                        "message": event.message.message,
                        "link": link
                    }

                    # ←←← ЭТО ВАЖНО: отправляем в дашборд
                    if self.callback:
                        self.callback(alert_data)

                    # ←←← Отправляем в канал
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(
                                ALERT_CHAT_ID,
                                f"{kw.upper()} → {group_title}\n{link}",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            log.error(f"Ошибка отправки в канал: {e}")

        log.info(f"[DASHBOAT v12] Мониторим {len(self.groups)} групп — всё готово!")
        await client.run_until_disconnected()
