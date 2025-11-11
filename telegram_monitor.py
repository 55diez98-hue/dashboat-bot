# telegram_monitor.py
from telethon import TelegramClient, events
from telegram import Bot  # python-telegram-bot
import asyncio

# === TELETHON (чтение) ===
API_ID = 24777032
API_HASH = "12da668ad167c903820f8899ea202158"
client = TelegramClient('monitor_session', API_ID, API_HASH)

# === BOT API (отправка) ===
BOT_TOKEN = "8273686092:AAGzLB6U6bog-itMWK4b8lUulrxFzNmcknk"
ALERT_CHAT_ID = -1003268583096
bot = Bot(BOT_TOKEN)

class TelegramMonitor:
    def __init__(self, api_id, api_hash, keywords, groups, callback):
        self.keywords = [kw.lower() for kw in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        print("[MONITOR] Запуск Telethon...")
        await client.start()
        print("[MONITOR] Авторизован!")

        # Названия групп
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

                    # Дашборд
                    self.callback({
                        'keyword': kw,
                        'group': group_title,
                        'group_id': group_id,
                        'message': event.message.message,
                        'link': msg_link
                    })

                    # В "барахло"
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
