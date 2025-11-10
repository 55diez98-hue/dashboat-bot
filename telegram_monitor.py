# telegram_monitor.py
from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel
import asyncio

# ТВОЯ ГРУППА "БАРАХЛО" — КУДА ПРИХОДЯТ АЛЕРТЫ
ALERT_CHAT_ID = -1003268583096  # ← Твой ID

class TelegramMonitor:
    def __init__(self, api_id, api_hash, keywords, groups, callback):
        self.api_id = api_id
        self.api_hash = api_hash
        self.keywords = [kw.lower() for kw in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.client = TelegramClient('monitor_session', api_id, api_hash)
        self.group_titles = {}

    async def start(self):
        print("[MONITOR] Авторизация в Telegram...")
        await self.client.start()
        print("[MONITOR] Успешно авторизован!")

        # Подключаемся к группам
        for group_id in self.groups:
            try:
                entity = await self.client.get_entity(group_id)
                title = getattr(entity, 'title', str(group_id))
                self.group_titles[group_id] = title
                print(f"[MONITOR] Подключено: {title}")
            except Exception as e:
                print(f"[ОШИБКА] Группа {group_id}: {e}")
                self.group_titles[group_id] = f"Группа {group_id}"

        # Обработчик сообщений
        @self.client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return

            text = event.message.message.lower()
            group_id = event.message.to_id.channel_id if hasattr(event.message.to_id, 'channel_id') else event.message.chat_id
            group_title = self.group_titles.get(group_id, "Неизвестно")

            for kw in self.keywords:
                if kw in text:
                    # Ссылка на сообщение
                    clean_id = str(group_id)[4:] if str(group_id).startswith('-100') else str(group_id)
                    msg_link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    # Данные для дашборда
                    alert_data = {
                        'keyword': kw,
                        'group': group_title,
                        'group_id': group_id,
                        'message': event.message.message,
                        'link': msg_link
                    }
                    self.callback(alert_data)

                    # Текст для Telegram (HTML — надёжнее)
                    alert_text = (
                        f"<b>Найдено в:</b> <a href='{msg_link}'>{group_title}</a>\n"
                        f"<b>Ключевое слово:</b> <code>{kw}</code>\n\n"
                        f"<i>{event.message.message[:300]}{'...' if len(event.message.message) > 300 else ''}</i>"
                    )

                    # Отправляем в "барахло"
                    try:
                        await self.client.send_message(
                            ALERT_CHAT_ID,
                            alert_text,
                            parse_mode='html',
                            disable_web_page_preview=True
                        )
                        print(f"[ALERT] Отправлено: {kw}")
                    except Exception as e:
                        print(f"[ОШИБКА] Не отправлено: {e}")

        print(f"[MONITOR] Слушаем {len(self.groups)} групп...")
        await self.client.run_until_disconnected()

    async def stop(self):
        await self.client.disconnect()
        print("[MONITOR] Отключён")
                        
