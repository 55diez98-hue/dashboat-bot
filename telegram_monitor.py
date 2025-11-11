# telegram_monitor.py
import asyncio
import logging
from telegram import Bot  # ← ПРАВИЛЬНЫЙ ИМПОРТ

# ТВОЙ БОТ
TOKEN = "8273686092:AAGzLB6U6bog-itMWK4b8lUulrxFzNmcknk"
ALERT_CHAT_ID = -1003268583096  # ← Группа "барахло"

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN)

class TelegramMonitor:
    def __init__(self, api_id, api_hash, keywords, groups, callback):
        self.keywords = [kw.lower() for kw in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.last_update_id = 0

    async def start(self):
        print("[MONITOR] Запуск get_updates...")

        # Названия групп (опционально)
        self.group_titles = {}
        for group_id in self.groups:
            try:
                chat = await bot.get_chat(group_id)
                self.group_titles[group_id] = chat.title or str(group_id)
            except Exception as e:
                print(f"[ОШИБКА] get_chat {group_id}: {e}")
                self.group_titles[group_id] = f"Группа {group_id}"

        while True:
            try:
                updates = await bot.get_updates(offset=self.last_update_id + 1, timeout=30)
                for update in updates:
                    self.last_update_id = update.update_id
                    message = update.message
                    if not message or not message.text:
                        continue

                    chat_id = message.chat.id
                    if chat_id not in self.groups:
                        continue

                    text = message.text.lower()
                    group_title = self.group_titles.get(chat_id, "Неизвестно")

                    for kw in self.keywords:
                        if kw in text:
                            # Ссылка
                            clean_id = str(chat_id)[4:] if str(chat_id).startswith('-100') else str(chat_id)
                            msg_link = f"https://t.me/c/{clean_id}/{message.message_id}"

                            # Дашборд
                            self.callback({
                                'keyword': kw,
                                'group': group_title,
                                'group_id': chat_id,
                                'message': message.text,
                                'link': msg_link
                            })

                            # В "барахло"
                            alert_text = (
                                f"<b>Найдено:</b> <a href='{msg_link}'>{group_title}</a>\n"
                                f"<b>Ключевое слово:</b> <code>{kw}</code>\n\n"
                                f"<i>{message.text[:300]}{'...' if len(message.text) > 300 else ''}</i>"
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
                                print(f"[ОШИБКА] send_message: {e}")

                await asyncio.sleep(1)
            except Exception as e:
                print(f"[ОШИБКА] get_updates: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        print("[MONITOR] Остановка...")
                    
