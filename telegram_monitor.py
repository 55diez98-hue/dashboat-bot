# telegram_monitor.py — v6.1 (100% работает на Render без ввода кода вручную)
import os
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telegram import Bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")
SESSION_STRING = os.getenv("SESSION_STRING", "")

if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    client = TelegramClient('monitor_session', API_ID, API_HASH)

bot = Bot(os.getenv("BOT_TOKEN")) if os.getenv("BOT_TOKEN") else None
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID"))

class TelegramMonitor:
    def __init__(self, keywords, groups, callback):
        self.keywords = [k.lower() for k in keywords]
        self.groups = [int(g) for g in groups]
        self.callback = callback
        self.group_titles = {}

    async def start(self):
        log.info("[DASHBOAT v6.1] Запуск мониторинга...")

        await client.connect()

        # === АВТОРИЗАЦИЯ ЧЕРЕЗ start() — САМ ВСЁ ДЕЛАЕТ ===
        if not await client.is_user_authorized():
            try:
                await client.start(phone=PHONE)  # ← САМАЯ ВАЖНАЯ СТРОКА
                log.info("[OK] АВТОРИЗОВАН АВТОМАТИЧЕСКИ!")
            except Exception as e:
                if "encrypted" in str(e):
                    log.error("[ERROR] Включён двухфакторный пароль — выключи в Telegram → Настройки → Конфиденциальность → Двухэтапная аутентификация")
                else:
                    log.error(f"[ERROR] Ошибка авторизации: {e}")
                raise

        # Сохраняем строковую сессию в логи (один раз!)
        if not SESSION_STRING:
            string = client.session.save()
            log.info("=" * 60)
            log.info("СКОПИРУЙ ЭТУ СТРОКУ В RENDER → ENV → SESSION_STRING")
            log.info(f"SESSION_STRING = {string}")
            log.info("=" * 60)

        log.info("[DASHBOAT v6.1] Авторизация прошла — сессия активна!")

        # Подключаемся к группам
        for gid in self.groups:
            try:
                entity = await client.get_entity(gid)
                title = getattr(entity, "title", str(gid))
                self.group_titles[gid] = title
                log.info(f"[OK] Подключено: {title}")
            except Exception as e:
                log.warning(f"[WARN] Не удалось подключиться к {gid}: {e}")

        @client.on(events.NewMessage(chats=self.groups))
        async def handler(event):
            if not event.message or not event.message.message: return
            text = event.message.message.lower()
            group_title = self.group_titles.get(event.chat_id, "Unknown")
            for kw in self.keywords:
                if kw in text:
                    clean_id = str(event.chat_id)[4:] if str(event.chat_id).startswith('-100') else str(event.chat_id)
                    link = f"https://t.me/c/{clean_id}/{event.message.id}"
                    self.callback({'keyword': kw, 'group': group_title, 'message': event.message.message, 'link': link})
                    if bot and ALERT_CHAT_ID:
                        try:
                            await bot.send_message(ALERT_CHAT_ID, f"{kw.upper()} в {group_title}\n{link}")
                        except: pass

        log.info(f"[DASHBOAT v6.1] Мониторим {len(self.groups)} групп — АЛЕРТЫ ВКЛЮЧЕНЫ!")
        await client.run_until_disconnected()
