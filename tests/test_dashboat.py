"""Offline regression tests: run via python -m unittest discover -s tests -v.
Telegram dependencies are stubbed so this suite works without a live account.
"""
import base64
import http.client
import importlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub only if dependencies are unavailable; do not connect to Telegram.
try:
    import telethon
except ImportError:
    telethon = types.ModuleType('telethon')
    telethon.TelegramClient = object
    telethon.events = types.SimpleNamespace(NewMessage=lambda: None)
    telethon.utils = types.SimpleNamespace(get_peer_id=lambda e: e.id)
    sessions = types.ModuleType('telethon.sessions')
    sessions.StringSession = lambda s: s
    sys.modules.update({'telethon':telethon,'telethon.sessions':sessions})
try:
    import telegram
except ImportError:
    telegram = types.ModuleType('telegram')
    telegram.Bot = object
    errors = types.ModuleType('telegram.error')
    errors.RetryAfter = type('RetryAfter', (Exception,), {})
    errors.TelegramError = type('TelegramError', (Exception,), {})
    sys.modules.update({'telegram':telegram,'telegram.error':errors})

import storage
import telegram_monitor as tm
import simple_server as server

class DashboatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oldpath = storage.DATA_FILE
        self.olddb = storage.DATABASE_URL
        storage.DATA_FILE = pathlib.Path(self.tmp.name) / 'state.json'
        storage.DATABASE_URL = ''
        server._cancel_requested.clear()
        server.status('stopped')
    def tearDown(self):
        storage.DATA_FILE = self.oldpath
        storage.DATABASE_URL = self.olddb
        self.tmp.cleanup()

    def test_defaults_and_persistence(self):
        storage.update(lambda d: d['groups'].extend(['-1001234567890']))
        self.assertEqual(storage.read()['groups'], ['-1001234567890'])
        self.assertEqual(storage.read()['matches_log'], [])

    def test_bulk_validation_and_distinct(self):
        ids, invalid = server.parse_group_list('-1001234567890, -1001234567890\n-1009876543210')
        self.assertEqual(ids, ['-1001234567890', '-1009876543210'])
        self.assertEqual(invalid, [])

    def test_same_group_repost_after_72_hours(self):
        state = storage.defaults()
        self.assertFalse(tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1001234567890', 1000000)[0])
        self.assertTrue(tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1001234567890', 1000060)[0])
        self.assertTrue(tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1001234567890', 1000000 + 72 * 3600 - 1)[0])
        self.assertFalse(tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1001234567890', 1000000 + 72 * 3600)[0])

    def test_cross_group_duplicate(self):
        state = storage.defaults()
        tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1001234567890', 1000000)
        self.assertTrue(tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1009876543210', 1000000 + 90000)[0])

    def test_different_price_not_duplicate(self):
        state = storage.defaults()
        tm.is_duplicate(state, 'Продам велосипед 100 лари', '-1001234567890', 1000000)
        self.assertFalse(tm.is_duplicate(state, 'Продам велосипед 200 лари', '-1009876543210', 1000001)[0])

    def test_running_flag_only_after_connect(self):
        server.status('starting')
        self.assertFalse(storage.read()['monitoring_active'])
        server.status('running', 'Подключено групп: 1')
        self.assertTrue(storage.read()['monitoring_active'])

    def test_dashboard_shows_failed_groups_and_duplicates(self):
        class FakeMonitor:
            counts = {'messages': 2, 'matches': 2, 'sent': 1}
            last_message = None
            group_ids = set()
            resolved_inputs = {'-1001234567890'}
            failed_groups = {'-1009876543210': 'Could not find entity'}
            client = None
        storage.update(lambda d: (d['groups'].extend(['-1001234567890','-1009876543210']),
                                  d['matches_log'].append({'duplicate': True,'message':'Повтор объявления', 'group':'Барахолка'})))
        with server._lock:
            original = server._monitor
            server._monitor = FakeMonitor()
            server._state = 'running'
        try:
            page = server.Handler.html(None)
        finally:
            server._monitor = original
        self.assertIn('Недоступные группы', page)
        self.assertIn('-1009876543210', page)
        self.assertIn('ДУБЛЬ', page)

    def test_http_ping_and_auth(self):
        with patch.dict(os.environ, {'ADMIN_PASSWORD':'test-super-secret'}):
            httpd = ThreadingHTTPServer(('127.0.0.1',0), server.Handler)
            worker = threading.Thread(target=httpd.serve_forever,daemon=True)
            worker.start()
            try:
                def request(path,headers=None,method='GET'):
                    conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=3)
                    conn.request(method,path,headers=headers or {})
                    res=conn.getresponse(); code=res.status;res.read();conn.close();return code
                self.assertEqual(request('/'),200)
                self.assertEqual(request('/ping'),200)
                self.assertEqual(request('/dashboard'),401)
                hdr={'Authorization':'Basic '+base64.b64encode(b'admin:test-super-secret').decode()}
                self.assertEqual(request('/dashboard',hdr),200)
            finally:
                httpd.shutdown(); httpd.server_close(); worker.join(timeout=2)

    def test_failed_worker_clears_autostart(self):
        storage.update(lambda d: d.update(monitoring_active=True))
        class FailedMonitor:
            def __init__(self,*a,**kw):pass
            async def start(self):raise RuntimeError('Telegram auth failed')
        with patch.object(server,'TelegramMonitor', FailedMonitor):
            server.worker()
        self.assertFalse(storage.read()['monitoring_active'])
        self.assertEqual(server._state,'error')

if __name__=='__main__':unittest.main()

class MobileAPIIntegrationTests(unittest.TestCase):
    """Exercise the same HTTP routes/JSON fields that the Android APK uses."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oldpath, self.olddb = storage.DATA_FILE, storage.DATABASE_URL
        storage.DATA_FILE = pathlib.Path(self.tmp.name) / 'state.json'
        storage.DATABASE_URL = ''
        self.env = patch.dict(os.environ, {'ADMIN_PASSWORD': 'unit-test-secret'})
        self.env.start()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.auth = 'Basic ' + base64.b64encode(b'admin:unit-test-secret').decode()
    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(timeout=2)
        self.env.stop()
        storage.DATA_FILE, storage.DATABASE_URL = self.oldpath, self.olddb
        self.tmp.cleanup()
    def call(self, method, path, payload=None, auth=True, extra_headers=None):
        headers = dict(extra_headers or {})
        if auth: headers['Authorization'] = self.auth
        if payload is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'
            body = json.dumps(payload).encode('utf-8')
        else: body = None
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=4)
        conn.request(method, path, body=body, headers=headers)
        res=conn.getresponse(); result=(res.status, res.read(), dict(res.getheaders()))
        conn.close(); return result
    def test_android_state_authorized_shape(self):
        code, body, _ = self.call('GET','/api/v1/state')
        self.assertEqual(code,200)
        obj=json.loads(body)
        self.assertTrue(obj['ok'])
        for key in ('keywords','groups','alerts','matches','monitoring_active','runtime','failed_groups','connected_groups'):
            self.assertIn(key,obj['data'])
        for key in ('monitor','detail','counts','connected','last_message'):
            self.assertIn(key,obj['data']['runtime'])
    def test_android_auth_required(self):
        self.assertEqual(self.call('GET','/api/v1/state',auth=False)[0],401)
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'add_keyword','value':'Bike'},auth=False)[0],401)
        self.assertEqual(storage.read()['keywords'],[])
    def test_android_web_shared_state(self):
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'add_keyword','value':'Велосипед'})[0],200)
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'add_groups_bulk','value':'-1001635935081 -1001635935081, -1001993420914'})[0],200)
        self.assertEqual(storage.read()['keywords'],['велосипед'])
        self.assertEqual(len(storage.read()['groups']),2)
        data=json.loads(self.call('GET','/api/v1/state')[1])['data']
        self.assertEqual(data['keywords'],['велосипед'])
        self.assertEqual([g['id'] for g in data['groups']],['-1001635935081','-1001993420914'])
        # Browser page is fed by the same stored state.
        html=self.call('GET','/dashboard')[1].decode()
        self.assertIn('ВЕЛОСИПЕД',html)
        self.assertIn('-1001635935081',html)
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'delete_keyword','value':'велосипед'})[0],200)
        self.assertEqual(storage.read()['keywords'],[])
    def test_json_error_and_csrf(self):
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'unknown'})[0],400)
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'add_keyword','value':'bike'},extra_headers={'Origin':'https://attacker.invalid'})[0],403)
        self.assertEqual(storage.read()['keywords'],[])
        self.assertEqual(self.call('POST','/api/v1/command',{'action':'add_groups_bulk','value':'bad-data'})[0],400)
    def test_monitoring_commands_same_functions(self):
        with patch.object(server,'start_monitoring') as start, patch.object(server,'stop_monitoring',return_value=True) as stop, patch.object(server,'restart_monitoring') as restart:
            self.assertEqual(self.call('POST','/api/v1/command',{'action':'start'})[0],200)
            self.assertEqual(self.call('POST','/api/v1/command',{'action':'stop'})[0],200)
            self.assertEqual(self.call('POST','/api/v1/command',{'action':'restart'})[0],200)
            start.assert_called_once();stop.assert_called_once();restart.assert_called_once()
    def test_public_uptimerobot_and_no_api_leak(self):
        self.assertEqual(self.call('HEAD','/')[0],200)
        self.assertEqual(self.call('GET','/ping')[0],200)
        self.assertEqual(self.call('GET','/api/v1/state',auth=False)[0],401)
