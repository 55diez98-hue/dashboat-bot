"""Thread-safe Dashboat state; optional durable PostgreSQL storage."""
import copy
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)
_LOCK = threading.RLock()
DATA_FILE = Path(os.environ.get('DATA_FILE', 'dashboat_data.json'))
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()


def defaults():
    return {'keywords': [], 'groups': [], 'group_titles': {}, 'alerts': [],
            'seen': [], 'monitoring_active': False}


def _clean(raw):
    data = defaults()
    if isinstance(raw, dict):
        data.update(raw)
    for name in ('keywords', 'groups', 'alerts', 'seen'):
        if not isinstance(data[name], list):
            data[name] = []
    data['groups'] = [str(g).strip() for g in data['groups'] if str(g).strip()]
    if not isinstance(data['group_titles'], dict):
        data['group_titles'] = {}
    return data


def _connect():
    import psycopg
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def initialize():
    if DATABASE_URL:
        with _connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS dashboat_state (id INTEGER PRIMARY KEY, data JSONB NOT NULL)')
            conn.execute('INSERT INTO dashboat_state (id, data) VALUES (1, %s::jsonb) ON CONFLICT DO NOTHING',
                         (json.dumps(_local_read(), ensure_ascii=False),))
        log.info('State persistence: PostgreSQL')
    else:
        log.warning('DATABASE_URL not configured: local JSON data may disappear on Render redeploy')


def _local_read():
    try:
        if DATA_FILE.exists():
            return _clean(json.loads(DATA_FILE.read_text(encoding='utf-8')))
    except Exception:
        log.exception('Cannot load JSON state; leaving file unchanged')
    return defaults()


def read():
    with _LOCK:
        if DATABASE_URL:
            with _connect() as conn:
                row = conn.execute('SELECT data FROM dashboat_state WHERE id=1').fetchone()
            return _clean(row[0] if row else defaults())
        return _local_read()


def update(mutator):
    """Atomic read-modify-write; mutator receives editable state and may return a result."""
    with _LOCK:
        if DATABASE_URL:
            with _connect() as conn:
                row = conn.execute('SELECT data FROM dashboat_state WHERE id=1 FOR UPDATE').fetchone()
                data = _clean(row[0] if row else defaults())
                result = mutator(data)
                conn.execute('UPDATE dashboat_state SET data=%s::jsonb WHERE id=1',
                             (json.dumps(data, ensure_ascii=False),))
            return result
        data = _local_read()
        result = mutator(data)
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = DATA_FILE.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, DATA_FILE)
        return result
