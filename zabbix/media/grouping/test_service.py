import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from service import (DeliveryError, Handler, Queue, deliver, messages,
                     split_text, units, visible_text)

CONFIG = {'token': 'FAKE_QUEUE_TOKEN_FOR_OFFLINE_TESTS_ONLY', 'window_seconds': 30,
          'routes': {
              '42': {'provider': 'telegram', 'max_chars': 3500},
              '43': {'provider': 'astro', 'url': 'https://astro.invalid/send', 'max_chars': 3500},
              '44': {'provider': 'ativ', 'url': 'https://ativ.invalid/api/message-by-id', 'max_chars': 3500}}}
EVENT = {'route': '44', 'provider': 'ativ', 'recipient': '120000000000@g.us',
         'token': 'FAKE_PROVIDER_TOKEN', 'text': 'Host A: CPU alta', 'format': 'plain',
         'kind': 'problem', 'group': '', 'proxy': ''}


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'queue.sqlite3'
        self.q = Queue(self.path, copy.deepcopy(CONFIG))
        self.sent = []

    def tearDown(self):
        self.temp.cleanup()

    def send(self, route, envelope, text):
        self.sent.append((route, envelope, text))

    def event(self, now=0, **changes):
        self.q.enqueue(dict(EVENT, **changes), now=now)

    def test_waits_window_and_groups_without_modifying_original_text(self):
        self.event(now=10)
        self.event(now=39, text='Host B: disco cheio')
        self.assertFalse(self.q.step(self.send, now=39.9))
        self.assertTrue(self.q.step(self.send, now=40))
        self.assertEqual(len(self.sent), 1)
        text = self.sent[0][2]
        self.assertIn('2 alertas', text)
        self.assertIn(EVENT['text'], text)
        self.assertIn('Host B: disco cheio', text)
        self.assertEqual(self.q.stats(), {'incoming': 0, 'outbox': 0})

    def test_fixed_window_does_not_grow_forever_or_include_future_events(self):
        self.event(now=0)
        self.event(now=31, text='Chegou depois da janela')
        self.q.step(self.send, now=31)
        self.assertNotIn('Chegou depois', self.sent[0][2])
        self.assertEqual(self.q.stats()['incoming'], 1)
        self.q.step(self.send, now=61)
        self.assertIn('Chegou depois', self.sent[1][2])

    def test_destinations_routes_and_event_kinds_are_isolated(self):
        self.event()
        self.event(recipient='120000000001@g.us', text='Destino B')
        self.event(kind='recovery', text='Recuperou A')
        self.event(route='43', provider='astro', text='Astro A')
        for now in range(30, 40):
            self.q.step(self.send, now=now)
        self.assertEqual(len(self.sent), 4)
        self.assertTrue(all('1 alerta)' in x[2] for x in self.sent))
        self.assertEqual(self.sent[1][1]['recipient'], '120000000001@g.us')
        self.assertTrue(any('RECUPERAÇÕES' in x[2] for x in self.sent))

    def test_queue_survives_restart_before_and_after_sealing(self):
        self.event()
        self.q = Queue(self.path, CONFIG)
        self.q.seal(30)
        self.q = Queue(self.path, CONFIG)
        self.q.step(self.send, now=30)
        self.assertIn(EVENT['text'], self.sent[0][2])

    def test_partial_failure_retries_only_unsent_parts_in_order(self):
        for n in range(5):
            self.event(text=str(n) + ': ' + 'x' * 2500)
        self.q.step(self.send, now=30)
        self.assertEqual(len(self.sent), 1)
        def fail(*_):
            raise DeliveryError('HTTP 429', retry_after=60)
        self.q.step(fail, now=32)
        self.q = Queue(self.path, CONFIG)
        self.assertFalse(self.q.step(self.send, now=91))
        for now in range(92, 110, 2):
            self.q.step(self.send, now=now)
        self.assertEqual(len(self.sent), 5)
        self.assertTrue(all(units(x[2]) <= 3500 for x in self.sent))
        self.assertEqual(self.q.stats()['outbox'], 0)
        for n, record in enumerate(self.sent):
            self.assertIn('Parte ' + str(n + 1) + '/5', record[2])

    def test_html_visible_text_links_and_unicode_are_preserved(self):
        text = '<b>Servidor</b>: uso &gt; 90%\n<a href="https://example.invalid">Abrir</a> 🚨'
        expected = 'Servidor: uso > 90%\nAbrir (https://example.invalid) 🚨'
        self.assertEqual(visible_text(text, 'html'), expected)
        self.assertEqual(visible_text('Uso < 90% e <90% &amp; ok', 'html'),
                         'Uso < 90% e <90% & ok')
        original = 'Á🚨\n' * 5000
        parts = split_text(original, 3400)
        self.assertEqual(''.join(parts), original)
        self.assertTrue(all(units(p) <= 3400 for p in parts))
        summaries = messages([original], 'problem', 3500)
        rebuilt = ''.join(p.split('\n\n', 1)[1] for p in summaries)
        self.assertEqual(rebuilt, original)
        self.assertTrue(all(units(p) <= 3500 for p in summaries))

    def test_telegram_rate_limit_is_shared_between_problem_and_recovery(self):
        self.event(route='42', provider='telegram', recipient='-1001')
        self.event(route='42', provider='telegram', recipient='-1001', kind='recovery')
        self.q.step(self.send, now=30)
        self.assertFalse(self.q.step(self.send, now=33))
        self.assertTrue(self.q.step(self.send, now=33.1))

    def test_acceptance_requires_known_route_valid_format_and_content(self):
        for changed in ({'route': 'bad'}, {'provider': 'bad'}, {'format': 'markdown'},
                        {'token': 'x\ny'}, {'text': ''}, {'text': 'x' * 200001}, {'kind': 'bad'}):
            with self.assertRaises(ValueError):
                self.event(**changed)
        self.assertEqual(self.q.stats()['incoming'], 0)

    def test_empty_html_does_not_create_a_poisoned_batch(self):
        with self.assertRaises(ValueError):
            self.event(route='42', provider='telegram', format='html', text='<b></b>')

    def test_http_auth_and_acceptance_only_after_persistence(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.queue = self.q
        server.worker = threading.current_thread()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = 'http://127.0.0.1:' + str(server.server_port)
        headers = {'Authorization': 'Bearer ' + CONFIG['token'], 'Content-Type': 'application/json'}
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                opener.open(urllib.request.Request(url + '/enqueue', data=json.dumps(EVENT).encode()))
            self.assertEqual(ctx.exception.code, 401)
            ctx.exception.close()
            with opener.open(urllib.request.Request(url + '/enqueue', data=json.dumps(EVENT).encode(),
                                                   headers=headers)) as response:
                self.assertEqual(response.status, 202)
            self.assertEqual(Queue(self.path, CONFIG).stats()['incoming'], 1)
            with patch.object(self.q, 'enqueue', side_effect=__import__('sqlite3').OperationalError('disk')):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    opener.open(urllib.request.Request(url + '/enqueue', data=json.dumps(EVENT).encode(),
                                                       headers=headers))
                self.assertEqual(ctx.exception.code, 503)
                ctx.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


class TransportTest(unittest.TestCase):
    def result(self, provider, body=b'{"ok":true}', status=200):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = status
        response.read.return_value = body
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        route = next(v for v in CONFIG['routes'].values() if v['provider'] == provider)
        with patch('urllib.request.build_opener', return_value=opener):
            deliver(route, dict(EVENT, group='true'), 'Resumo completo')
        return opener.open.call_args[0][0]

    def test_contracts_are_preserved(self):
        ativ = self.result('ativ')
        self.assertEqual(json.loads(ativ.data), {'id': EVENT['recipient'], 'text': 'Resumo completo'})
        astro = self.result('astro')
        self.assertEqual(json.loads(astro.data), {'id': EVENT['recipient'], 'message': 'Resumo completo', 'group': 'true'})
        telegram = self.result('telegram')
        self.assertEqual(json.loads(telegram.data)['chat_id'], EVENT['recipient'])
        self.assertNotIn('parse_mode', json.loads(telegram.data))
        self.assertIn('Authorization', ativ.headers)
        self.assertNotIn('Authorization', telegram.headers)

    def test_explicit_provider_failure_is_not_acknowledged(self):
        for provider in ('ativ', 'astro', 'telegram'):
            with self.assertRaises(DeliveryError):
                self.result(provider, b'{"ok":false}')

    def test_transport_error_does_not_expose_token_or_response(self):
        opener = unittest.mock.Mock()
        opener.open.side_effect = OSError(EVENT['token'])
        with patch('urllib.request.build_opener', return_value=opener):
            with self.assertRaises(DeliveryError) as ctx:
                deliver(CONFIG['routes']['42'], EVENT, 'text')
        self.assertNotIn(EVENT['token'], str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
