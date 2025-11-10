# telegram_monitor.py
from telethon import TelegramClient, events
import asyncio
from datetime import datetime
import logging
import requests

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

class TelegramMonitor:
    def __init__(self, api_id, api_hash, keywords, groups, callback=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.keywords = [kw.strip().lower() for kw in keywords if kw.strip()]
        self.group_ids = [str(g).strip() for g in groups if g]
        self.callback = callback
        self.running = False

        # === TELETHON (личный аккаунт) ===
        self.client = TelegramClient("monitor_session", self.api_id, self.api_hash)
        self.client.parse_mode = "html"

        # === БОТ ДЛЯ УВЕДОМЛЕНИЙ ===
        self.bot_token = "8273686092:AAGzLB6U6bog-itMWK4b8lUulrxFzNmcknk"  # ← ваш токен
        self.channel_id = "@barahlo_alert"  # ← ваш канал

    async def start(self):
        if self.running:
            logger.warning("Мониторинг уже запущен!")
            return

        @self.client.on(events.NewMessage(incoming=True))
        async def message_handler(event):
            try:
                message = event.message
                if not message or not message.message:
                    return

                text = message.message
                text_lower = text.lower()

                # Получаем чат
                chat = await event.get_chat()
                chat_id_raw = getattr(chat, "id", None)
                if chat_id_raw is None:
                    return

                # КОНВЕРТИРУЕМ ID: 1466725454 → -1001466725454
                chat_id = str(chat_id_raw)
                if not chat_id.startswith("-"):
                    chat_id = f"-100{chat_id}"

                chat_title = getattr(chat, "title", "Без названия")

                logger.info(f"Новое сообщение:")
                logger.info(f"   Raw ID: {chat_id_raw} → API ID: {chat_id}")
                logger.info(f"   Группа: {chat_title}")
                logger.info(f"   Текст: {text[:100]}")
                logger.info(f"   Наши группы: {self.group_ids}")

                # Проверяем, наша ли группа
                if chat_id not in self.group_ids:
                    logger.info(f"Группа {chat_id} НЕ в списке")
                    return

                logger.info(f"ГРУППА НАЙДЕНА: {chat_title}")

                # Ищем ключевое слово
                found_kw = None
                for kw in self.keywords:
                    if kw in text_lower:
                        found_kw = kw
                        break

                if not found_kw:
                    logger.info("Ключевое слово НЕ найдено")
                    return

                logger.info(f"СРАБОТАЛО: '{found_kw}'")

                # === ФОРМИРУЕМ АЛЕРТ ===
                alert = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%m:%S"),
                    "group": chat_title,
                    "keyword": found_kw,
                    "message": text
                }

                # === СОХРАНЯЕМ В DASHBOARD ===
                if self.callback:
                    try:
                        self.callback(alert)
                        logger.info("АЛЕРТ СОХРАНЁН в dashboard")
                    except Exception as e:
                        logger.error(f"Ошибка callback: {e}")

                # === ОТПРАВЛЯЕМ ЧЕРЕЗ БОТА (всегда со звуком!) ===
                notify_msg = (
                    f"<b>Найдено в {chat_title}</b>\n"
                    f"<b>Ключевое слово:</b> <code>{found_kw}</code>\n\n"
                    f"{text}"
                )

                try:
                    url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                    payload = {
                        "chat_id": self.channel_id,
                        "text": notify_msg,
                        "parse_mode": "HTML",
                        "disable_notification": False  # ← ЗВУК ВКЛЮЧЁН
                    }
                    response = requests.post(url, data=payload, timeout=10)
                    if response.status_code == 200:
                        logger.info(f"УВЕДОМЛЕНИЕ ОТПРАВЛЕНО ЧЕРЕЗ БОТА в {self.channel_id}")
                    else:
                        logger.error(f"Ошибка бота: {response.status_code} — {response.text}")
                except Exception as e:
                    logger.error(f"Ошибка отправки через бота: {e}")

            except Exception as e:
                logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
                import traceback
                traceback.print_exc()

        # === ЗАПУСК ===
        self.running = True
        logger.info("Подключение к Telegram (Telethon)...")
        await self.client.start()
        logger.info("Мониторинг запущен. Ожидаю новые сообщения...")
        await self.client.run_until_disconnected()

    async def stop(self):
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            logger.info("Telethon клиент отключён")
        self.running = False

    def update_keywords(self, keywords):
        self.keywords = [kw.strip().lower() for kw in keywords if kw.strip()]
        logger.info(f"Ключевые слова обновлены: {self.keywords}")

    def update_groups(self, groups):
        self.group_ids = [str(g).strip() for g in groups if g]
        logger.info(f"Группы обновлены: {self.group_ids}")