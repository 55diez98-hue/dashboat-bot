 # telegram_monitor.py
from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel
import asyncio

# ТВОЯ ГРУППА "БАРАХЛО" — куда приходят алерты
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
        await self.client.start()
        print("[MONITOR] Клиент запущен")

        # Подключаемся к группам и сохраняем названия
        for group_id in self.groups:
            try:
                entity = await self.client.get_entity(PeerChannel(group_id))
                title = entity.title or "Без названия"
                self.group_titles[group_id] = title
                print(f"[MONITOR] Подключено: {title} ({group_id})")
            except Exception as e:
                print(f"[ОШИБКА] Группа {group_id}: {e}")
                self.group_titles[group_id] = f"Группа {group_id}"

        # Обработчик новых сообщений
        @self.client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message:
                return

            text = event.message.message.lower()
            group_id = event.message.chat_id
            group_title = self.group_titles.get(group_id, "Неизвестная группа")

            for kw in self.keywords:
                if kw in text:
                    # Ссылка на сообщение
                    clean_id = str(group_id)[4:]  # убираем -100
                    msg_link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    # Текст для Telegram (Markdown)
                    alert_text = (
                        f"*Найдено в:* [{group_title}]({msg_link})\n"
                        f"*Ключевое слово:* `{kw}`\n\n"
                        f"_{event.message.message[:300]}{'...' if len(event.message.message) > 300 else ''}_"
                    )

                    # 1. Отправляем в дашборд
                    alert_data = {
                        'keyword': kw,
                        'group': group_title,
                        'group_id': group_id,
                        'message': event.message.message,
                        'link': msg_link
                    }
                    self.callback(alert_data)

                    # 2. Отправляем в группу "барахло"
                    try:
                        await self.client.send_message(
                            ALERT_CHAT_ID,
                            alert_text,
                            parse_mode='markdown',
                            link_preview=False
                        )
                        print(f"[ALERT] Отправлено в 'барахло': {kw}")
                    except Exception as e:
                        print(f"[ОШИБКА] Не удалось отправить в 'барахло': {e}")

        print(f"[MONITOR] Мониторим {len(self.groups)} групп...")
        await self.client.run_until_disconnected()

    async def stop(self):
        await self.client.disconnect()
        print("[MONITOR] Клиент отключён")
