# telegram_monitor.py — v10.2 — С ЖЁСТКИМ ТЕСТОМ СВЯЗИ (18.11.2025)
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
    raise ValueError("Нужны API_ID, API_HASH, SESSION_STRING в переменных окружения!")

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
        log.info("[DASHBOAT v10.2] Запуск с тестом связи...")

        # === ПОДКЛЮЧЕНИЕ ===
        try:
            await client.start()
            log.info("[SUCCESS] Telethon успешно подключился!")
        except Exception as e:
            log.error(f"[КРИТИЧЕСКАЯ ОШИБКА] client.start() упал: {e}")
            return

        # === ТЕСТ 1: Кто я? ===
        try:
            me = await client.get_me()
            log.info(f"[ТЕСТ] Аккаунт живой: {me.first_name} (@{me.username or 'нет'}) | {me.phone}")
        except Exception as e:
            log.error(f"[ТЕСТ ПРОВАЛЕН] Не смог получить данные аккаунта: {e}")

        # === ТЕСТ 2: Пишу в Избранное ===
        try:
            await client.send_message("me", "DASHBOAT ТЕСТ УСПЕШЕН! Telethon работает — 18.11.2025")
            log.info("[ТЕСТ] Сообщение отправлено в «Избранное»!")
        except Exception as e:
            log.error(f"[ТЕСТ ПРОВАЛЕН] Не смог написать в Избранное: {e}")

        # === ТЕСТ 3: Пишу в канал ===
        if bot and ALERT_CHAT_ID:
            try:
                await bot.send_message(ALERT_CHAT_ID, "DASHBOAT ТЕСТ — Telethon жив и готов ловить алерты! 18.11.2025")
                log.info("[ТЕСТ] Сообщение отправлено в канал алертов!")
            except Exception as e:
                log.error(f"[ТЕСТ ПРОВАЛЕН] Не смог написать в канал: {e}")

        # === Подключаем группы ===
        for gid in self.groups:
            try:
                entity = await client.get_entity(gid)
                title = getattr(entity, "title", str(gid))
                self.group_titles[gid] = title
                log.info(f"[OK] Подключено: {title}")
            except Exception as e:
                log.warning(f"[WARN] Не удалось подключить группу {gid}: {e}")

        # === Обработчик новых сообщений ===
        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return

            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Unknown")

            # Логируем ВСЁ, что приходит (чтобы видеть в логах Render)
            log.info(f"[НОВОЕ СООБЩЕНИЕ] {group_title}: {event.message.message[:100]}")

            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    log.info(f"АЛЕРТ! Найдено «{kw.upper()}» в {group_title}")

                    alert_data = {
                        "keyword": kw,
                        "group": group_title,
                        "message": event.message.message,
                        "link": link
                    }

                    if self.callback:
                        self.callback(alert_data)

                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(
                                ALERT_CHAT_ID,
                                f"{kw.upper()} → {group_title}\n{link}",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            log.error(f"Ошибка отправки в канал: {e}")

        log.info(f"[DASHBOAT v10.2] Мониторим {len(self.groups)} групп — тесты пройдены, ждём алерты!")
        await client.run_until_disconnected()
