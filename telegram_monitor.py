# telegram_monitor.py
from telethon import TelegramClient, events
from telegram import Bot
import asyncio
import os

# === ENV (обязательно в Render) ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID"))
PHONE = os.getenv("PHONE")  # +995xxxxxxxxx — твой номер
CODE = os.getenv("CODE")    # 12345 — код из SMS (только для первой авторизации)

if not all([API_ID, API_HASH, BOT_TOKEN, ALERT_CHAT_ID]):
    raise ValueError("Установите API_ID, API_HASH, BOT_TOKEN, ALERT_CHAT_ID в Render")

client = TelegramClient('monitor_session', API_ID, API_HASH)
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

class TelegramMonitor:
    def __init__(self, keywords, groups, callback):
        self.keywords = [kw.lower() for kw in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        print("[MONITOR] Запуск Telethon...")
        try:
            # === АВТО-АВТОРИЗАЦИЯ ЧЕРЕЗ ENV (без input) ===
            if os.path.exists('monitor_session.session'):
                # Сессия есть — подключаемся
                await client.connect()
                if not await client.is_user_authorized():
                    raise Exception("Сессия не авторизована — удалите monitor_session.session и добавьте CODE в ENV")
                print("[MONITOR] Авторизован (по сессии)!")
            else:
                # Первая авторизация
                if not PHONE or not CODE:
                    raise Exception("Добавьте PHONE и CODE в Render ENV для первой авторизации")
                
                await client.start(phone=PHONE)
                await client.sign_in(phone=PHONE, code=CODE)
                print("[MONITOR] Авторизован (по коду из ENV)!")
        except Exception as e:
            print(f"[ОШИБКА] Авторизация: {e}")
            raise

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
                    # Формируем ссылку
                    clean_id = str(group_id)[4:] if str(group_id).startswith('-100') else str(group_id)
                    msg_link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    # Сохраняем в JSON
                    self.callback({
                        'keyword': kw,
                        'group': group_title,
                        'group_id': group_id,
                        'message': event.message.message,
                        'link': msg_link
                    })

                    # Отправляем алерт
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
