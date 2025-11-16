# telegram_monitor.py
from telethon import TelegramClient, events
from telegram import Bot
import asyncio
import os

# === ENV (без raise на старте — только логи) ===
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "0"))

# Проверка ENV (логи, но не краш)
if API_ID == 0 or not API_HASH:
    print("[ОШИБКА] API_ID или API_HASH не установлены! Добавьте в Render ENV.")
if not BOT_TOKEN:
    print("[ОШИБКА] BOT_TOKEN не установлен!")
if ALERT_CHAT_ID == 0:
    print("[ОШИБКА] ALERT_CHAT_ID не установлен!")

# Клиент и бот (глобальные, но не переопределяем внутри функции)
client = TelegramClient('monitor_session', API_ID, API_HASH)
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None


class TelegramMonitor:
    def __init__(self, keywords, groups, callback):
        self.keywords = [kw.lower() for kw in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        global client  # ← Объявляем global В НАЧАЛЕ функции

        if API_ID == 0 or not API_HASH:
            print("[MONITOR] Пропуск запуска — нет API_ID/API_HASH")
            return

        print("[MONITOR] Запуск Telethon...")

        # Retry на случай TLObject ошибки
        for attempt in range(3):
            try:
                await client.start()
                print("[MONITOR] Авторизован!")
                break
            except Exception as e:
                if "matching constructor ID" in str(e).lower():
                    print(f"[RETRY] TLObject ошибка (попытка {attempt+1}/3): {e}")
                    await asyncio.sleep(10)
                    # Пересоздаём клиент (global уже объявлен выше)
                    client = TelegramClient('monitor_session', API_ID, API_HASH)
                else:
                    print(f"[ОШИБКА] Не удалось авторизоваться: {e}")
                    raise e
        else:
            print("[ОШИБКА] Не удалось запустить Telethon после 3 попыток")
            return

        # Получаем названия групп
        for group_id in self.groups:
            try:
                entity = await client.get_entity(group_id)
                self.group_titles[group_id] = entity.title
                print(f"[MONITOR] Подключено: {entity.title}")
            except Exception as e:
                print(f"[ОШИБКА] Группа {group_id}: {e}")
                self.group_titles[group_id] = f"Группа {group_id}"

        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return

            text = event.message.message.lower()
            group_id = event.message.chat_id
            group_title = self.group_titles.get(group_id, "Неизвестно")

            for kw in self.keywords:
                if kw in text:
                    clean_id = str(group_id)[4:] if str(group_id).startswith('-100') else str(group_id)
                    msg_link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    self.callback({
                        'keyword': kw,
                        'group': group_title,
                        'group_id': group_id,
                        'message': event.message.message,
                        'link': msg_link
                    })

                    if bot and ALERT_CHAT_ID != 0:
                        alert_text = (
                            f"<b>Найдено:</b> <a href='{msg_link}'>{group_title}</a>\n"
                            f"<b>Ключевое слово:</b> <code>{kw}</code>\n\n"
                            f"<i>{event.message.message[:300]}{'...' if len(event.message.message) > 300 else ''}</i>"
                        )
                        try:
                            await bot.send_message(
                                chat_id=ALERT_CHAT_ID,
                                text=alert_text,
                                parse_mode='HTML',
                                disable_web_page_preview=True
                            )
                            print(f"[ALERT] Отправлено: {kw}")
                        except Exception as e:
                            print(f"[ОШИБКА] Bot API: {e}")

        print(f"[MONITOR] Слушаем {len(self.groups)} групп...")
        await client.run_until_disconnected()

    async def stop(self):
        await client.disconnect()
        print("[MONITOR] Остановлен")
