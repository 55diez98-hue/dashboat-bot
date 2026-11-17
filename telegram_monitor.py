"""Dashboat v3 Telegram monitor. Compatible with python-telegram-bot 21.x and Telethon 1.x."""
import asyncio
import hashlib
import html
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from storage import read, update

log = logging.getLogger(__name__)


def normalized(value):
    value = unicodedata.normalize('NFKC', str(value)).casefold().replace('ё', 'е')
    return ''.join(ch for ch in value if ch.isalnum())


def canonical(value):
    # Space normalization retains word boundaries for conservative near-duplicate detection.
    value = unicodedata.normalize('NFKC', value).casefold().replace('ё', 'е')
    return ' '.join(re.findall(r'[^\W_]+', value, flags=re.UNICODE))


def is_duplicate(data, text, group_id, now):
    key = hashlib.sha256(normalized(text).encode('utf-8')).hexdigest()
    comparable = canonical(text)[:2500]
    numbers = re.findall(r'\d+', comparable)
    remaining = []
    matched = False
    for item in data.get('seen', []):
        if not isinstance(item, dict) or now - float(item.get('at', 0)) > 14 * 86400:
            continue
        remaining.append(item)
        if item.get('hash') == key:
            matched = True
        # Conservative similarity across DIFFERENT groups only, same numeric values.
        elif (str(item.get('group')) != str(group_id) and len(comparable) >= 100
              and abs(len(comparable) - len(item.get('text', ''))) <= max(10, len(comparable) * .03)
              and re.findall(r'\d+', item.get('text', '')) == numbers
              and SequenceMatcher(None, comparable, item.get('text', ''), autojunk=False).ratio() >= .98):
            matched = True
    data['seen'] = remaining[-2999:]
    if not matched:
        data['seen'].append({'hash': key, 'text': comparable, 'group': str(group_id), 'at': now})
    return matched, key


class TelegramMonitor:
    def __init__(self, keywords, groups, status_callback=None):
        self.keywords = [k.strip() for k in keywords if str(k).strip()]
        self.groups = [str(g).strip() for g in groups if str(g).strip()]
        self.status_callback = status_callback
        self.client = None
        self.bot = None
        self.group_titles = {}
        self.group_ids = set()
        self.group_public_names = {}
        self.stopping = False
        self.counts = {'messages': 0, 'matches': 0, 'sent': 0}
        self.last_message = None

    def _status(self, state, message=''):
        if self.status_callback:
            self.status_callback(state, message)

    async def start(self):
        api_id = os.getenv('API_ID', '')
        api_hash = os.getenv('API_HASH', '')
        session = os.getenv('SESSION_STRING', '')
        bot_token = os.getenv('BOT_TOKEN', '')
        alert_chat = os.getenv('ALERT_CHAT_ID', '')
        if not all([api_id, api_hash, session, bot_token, alert_chat]):
            raise RuntimeError('Missing API_ID, API_HASH, SESSION_STRING, BOT_TOKEN or ALERT_CHAT_ID')
        self._status('starting', 'Подключение к Telegram')
        try:
            self.client = TelegramClient(StringSession(session), int(api_id), api_hash)
            await self.client.connect()
            if not await self.client.is_user_authorized():
                raise RuntimeError('SESSION_STRING is not authorized')
            self.bot = Bot(bot_token)
            await self.bot.initialize()
            resolved = {}
            titles_by_input = {}
            for raw in self.groups:
                target = int(raw) if raw.lstrip('-').isdigit() else raw
                try:
                    try:
                        entity = await self.client.get_entity(target)
                    except (ValueError, TypeError):
                        # For -100... IDs Telethon may lack an access_hash until dialogs are fetched.
                        await self.client.get_dialogs()
                        entity = await self.client.get_entity(target)
                    peer_id = utils.get_peer_id(entity)
                    resolved[peer_id] = getattr(entity, 'title', raw)
                    titles_by_input[raw] = resolved[peer_id]
                    username = getattr(entity, 'username', None)
                    if username:
                        self.group_public_names[peer_id] = username
                except Exception as exc:
                    log.warning('Failed to resolve group %s: %s', raw, exc)
            if not resolved:
                raise RuntimeError('Ни одна из заданных групп не доступна Telegram-аккаунту')
            self.group_ids = set(resolved)
            self.group_titles = resolved
            def save_titles(data):
                data['group_titles'].update({str(k): v for k, v in resolved.items()})
                # Recognize original input IDs and usernames in interface too.
                data['group_titles'].update(titles_by_input)
            update(save_titles)
            self.client.add_event_handler(self._handle_message, events.NewMessage())
            self._status('running', f'Подключено групп: {len(resolved)}')
            log.info('Dashboat v3 monitors %d groups', len(resolved))
            await self.client.run_until_disconnected()
            if not self.stopping:
                raise RuntimeError('Telegram disconnected unexpectedly')
        finally:
            if self.client:
                await self.client.disconnect()
            if self.bot:
                await self.bot.shutdown()
            self._status('stopped' if self.stopping else 'error')

    async def stop(self):
        self.stopping = True
        self._status('stopping')
        if self.client:
            await self.client.disconnect()

    async def _send(self, text, chat_id):
        for attempt in range(3):
            try:
                await self.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML',
                                            disable_web_page_preview=True)
                return True
            except RetryAfter as exc:
                delay = min(float(exc.retry_after) + 1, 60)
                log.warning('Telegram rate limit: waiting %.1fs', delay)
                await asyncio.sleep(delay)
            except TelegramError:
                log.exception('Failed to send Telegram alert')
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        return False

    async def _handle_message(self, event):
        if self.stopping or event.chat_id not in self.group_ids or not event.raw_text:
            return
        original = event.raw_text
        self.counts['messages'] += 1
        self.last_message = datetime.now(timezone.utc).isoformat()
        text = normalized(original)
        keyword = next((kw for kw in self.keywords if normalized(kw) and normalized(kw) in text), None)
        if not keyword:
            return
        self.counts['matches'] += 1
        now = time.time()
        # Reserve fingerprint atomically so a cross-post doesn't send twice.
        def reserve(data):
            dup, key = is_duplicate(data, original, event.chat_id, now)
            return (dup, key)
        dup, key = update(reserve)
        if dup:
            return
        title = self.group_titles.get(event.chat_id, str(event.chat_id))
        username = self.group_public_names.get(event.chat_id)
        if username:
            link = f'https://t.me/{username}/{event.message.id}'
        elif str(event.chat_id).startswith('-100'):
            link = f'https://t.me/c/{str(event.chat_id)[4:]}/{event.message.id}'
        else:
            link = ''
        out = (f'Найдено: {html.escape(title)}\n'
               f'Ключевое слово: <b>{html.escape(keyword.upper())}</b>\n\n'
               f'{html.escape(original[:800])}{"..." if len(original)>800 else ""}\n\n')
        if link:
            out += f'<a href="{html.escape(link, quote=True)}">Перейти к сообщению</a>'
        sent = await self._send(out, os.getenv('ALERT_CHAT_ID'))
        if not sent:
            # Permit a future repost to be retried if delivery failed.
            def rollback(data):
                data['seen'] = [item for item in data['seen'] if not (item.get('hash') == key and item.get('at') == now)]
            update(rollback)
            return
        self.counts['sent'] += 1
        def record(data):
            data['alerts'].append({'keyword': keyword, 'group': title, 'message': original,
                                   'link': link, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            data['alerts'] = data['alerts'][-100:]
        update(record)
