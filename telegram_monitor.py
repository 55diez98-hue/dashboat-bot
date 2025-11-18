# telegram_monitor.py — КРАСИВЫЕ АЛЕРТЫ В БАРАХЛО (18.11.2025)
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
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID"))  # твой канал Барахло

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

class TelegramMonitor:
    def __init__(self, keywords, groups):
        self.keywords = [k.strip().lower() for k in keywords if k.strip()]
        self.groups = [int(g) for g in groups]
        self.callback = None
        self.group_titles = {}

    def set_callback(self, callback):
        self.callback = callback

    async def start(self):
        log.info("[DASHBOAT] Подключение Telethon...")
        await client.start()
        log.info("[SUCCESS] Telethon подключился!")

        # Тестовое красивое сообщение
        try:
            await client.send_message("me", "DASHBOAT v15 FINAL — всё работает идеально!")
            if bot and ALERT_CHAT_ID:
                await bot.send_message(
                    ALERT_CHAT_ID,
                    "DASHBOAT v15 FINAL запущен\n"
                    "Красивые алерты в Барахло включены\n"
                    "Готов ловить всё!",
                    disable_web_page_preview=True
                )
        except: pass

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
            group_title = self.group_titles.get(event.chat_id, "Неизвестно")
            original_text = event.message.message

            for kw in self.keywords:
                if kw.replace(" ", "").replace("-", "") in text.replace(" ", "").replace("-", ""):
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"

                    # ←←← КРАСИВОЕ СООБЩЕНИЕ В БАРАХЛО
                    pretty_message = (
                        f"Найдено: {group_title}\n"
                        f"Ключевое слово: <b>{kw.upper()}</b>\n\n"
                        f"{original_text[:800]}{'...' if len(original_text) > 800 else ''}\n\n"
                        f"<a href='{link}'>Перейти к сообщению</a>"
                    )

                    # Отправляем в канал
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(
                                chat_id=ALERT_CHAT_ID,
                                text=pretty_message,
                                parse_mode="HTML",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            log.error(f"Ошибка отправки в канал: {e}")

                    # Отправляем в дашборд
                    if self.callback:
                        self.callback({
                            "keyword": kw,
                            "group": group_title,
                            "message": original_text,
                            "link": link
                        })

                    log.info(f"АЛЕРТ! {kw.upper()} → {group_title}")
                    break  # один алерт на сообщение

        log.info(f"[DASHBOAT v15 FINAL] Мониторим {len(self.groups)} групп — красивые алерты включены!")
        await client.run_until_disconnected()
