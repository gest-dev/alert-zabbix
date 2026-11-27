#!/usr/bin/env python3
"""Fila persistente local para agrupar entregas de mídia, sem acessar o Zabbix."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
from http.client import HTTPException
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

LOG = logging.getLogger('message-group')
MAX_REQUEST = 512 * 1024
LABELS = {'problem': 'PROBLEMAS', 'recovery': 'RECUPERAÇÕES', 'update': 'ATUALIZAÇÕES'}


def units(text):
    """Conta unidades UTF-16 conservadoramente, inclusive emojis fora do BMP."""
    return len(text.encode('utf-16-le')) // 2


def split_text(text, maximum):
    result = []
    while text:
        count = 0
        end = 0
        for char in text:
            size = 2 if ord(char) > 0xffff else 1
            if count + size > maximum:
                break
            count += size
            end += 1
        if not end:
            raise ValueError('Limite insuficiente.')
        if end < len(text):
            newline = text.rfind('\n', 0, end)
            if newline >= end // 2:
                end = newline + 1
        result.append(text[:end])
        text = text[end:]
    return result


class PlainHTML(HTMLParser):
    """Conserva o texto visível; evita cortar tags HTML ao dividir no Telegram."""
    TAGS = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
            'span', 'tg-spoiler', 'a', 'code', 'pre', 'blockquote', 'tg-emoji'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')
        elif tag == 'a':
            self.links.append((dict(attrs).get('href', ''), len(self.parts)))
        elif tag not in self.TAGS:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == 'a' and self.links:
            href, start = self.links.pop()
            if href and href != ''.join(self.parts[start:]):
                self.parts.append(' (' + href + ')')
        elif tag not in self.TAGS and tag != 'br':
            self.parts.append('</' + tag + '>')


def visible_text(text, fmt):
    if fmt != 'html':
        return text
    parser = PlainHTML()
    parser.feed(text)
    parser.close()
    return ''.join(parser.parts)


def messages(texts, kind, maximum):
    # Reserva espaço inclusive para a numeração final e títulos acentuados.
    title = ('Resumo Zabbix — ' + LABELS[kind] + ' (' + str(len(texts))
             + (' alerta)' if len(texts) == 1 else ' alertas)'))
    budget = maximum - units(title) - 48
    if budget < 16:
        raise ValueError('Limite insuficiente para o cabeçalho.')
    chunks, current = [], ''
    for text in texts:
        if current and units(current + '\n\n' + text) <= budget:
            current += '\n\n' + text
            continue
        if current:
            chunks.append(current)
        pieces = split_text(text, budget)
        chunks.extend(pieces[:-1])
        current = pieces[-1]
    if current:
        chunks.append(current)
    result = [title + '\nParte ' + str(i) + '/' + str(len(chunks)) + '\n\n' + chunk
              for i, chunk in enumerate(chunks, 1)]
    if any(units(text) > maximum for text in result):
        raise ValueError('Resumo excedeu o limite.')
    return result


class DeliveryError(Exception):
    def __init__(self, code='transport', retry_after=0):
        # Nunca carregar URL, token, texto ou resposta do provedor na exceção.
        super().__init__(str(code))
        self.retry_after = retry_after


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deliver(route, envelope, text):
    provider = route['provider']
    token = envelope['token']
    if provider == 'telegram':
        url = 'https://api.telegram.org/bot' + token + '/sendMessage'
        payload = {'chat_id': envelope['recipient'], 'text': text,
                   'disable_web_page_preview': True, 'disable_notification': False}
    elif provider == 'ativ':
        url = route['url']
        payload = {'id': envelope['recipient'], 'text': text}
    else:
        url = route['url']
        payload = {'id': envelope['recipient'], 'message': text, 'group': envelope['group']}
    headers = {'Content-Type': 'application/json'}
    if provider != 'telegram':
        headers['Authorization'] = 'Bearer ' + token
    proxy = envelope.get('proxy')
    proxies = {'http': proxy, 'https': proxy} if proxy else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), NoRedirect())
    request = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode(), headers)
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(MAX_REQUEST)
            status = response.status
    except urllib.error.HTTPError as error:
        retry_after = 0
        if error.code == 429:
            try:
                retry_after = int(error.headers.get('Retry-After', '0'))
                body = json.loads(error.read(MAX_REQUEST))
                retry_after = max(retry_after, int(body.get('parameters', {}).get('retry_after', 0)))
            except (ValueError, TypeError, AttributeError):
                pass
        raise DeliveryError('HTTP ' + str(error.code), min(86400, max(0, retry_after))) from None
    except (OSError, ValueError, HTTPException):
        raise DeliveryError() from None
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        result = None
    if not 200 <= status < 300:
        raise DeliveryError('HTTP ' + str(status))
    if provider == 'telegram' and (not isinstance(result, dict) or result.get('ok') is not True):
        raise DeliveryError('provider')
    if isinstance(result, dict) and (
        any(result.get(key) is False for key in ('success', 'ok', 'status'))
        or result.get('error') not in (None, False, '')
    ):
        raise DeliveryError('provider')


class Queue:
    def __init__(self, path, config):
        self.path, self.config = str(path), config
        self.window = int(config.get('window_seconds', 30))
        if not 1 <= self.window <= 300:
            raise ValueError('Janela inválida.')
        if len(config['token']) < 32 or '\n' in config['token'] or '\r' in config['token']:
            raise ValueError('Token de fila inválido.')
        for route in config['routes'].values():
            if route['provider'] not in ('ativ', 'astro', 'telegram'):
                raise ValueError('Provedor inválido.')
            if not 256 <= route.get('max_chars', 3500) <= 4096:
                raise ValueError('Limite inválido.')
            if route['provider'] != 'telegram':
                parts = urlsplit(route['url'])
                if (parts.scheme not in ('http', 'https') or not parts.hostname
                        or parts.username or parts.password or parts.fragment):
                    raise ValueError('URL de serviço inválida.')
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS incoming (
                    id INTEGER PRIMARY KEY, route TEXT NOT NULL, group_key TEXT NOT NULL,
                    destination TEXT NOT NULL, envelope TEXT NOT NULL, kind TEXT NOT NULL,
                    text TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS incoming_group ON incoming(group_key, created);
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY, route TEXT NOT NULL, destination TEXT NOT NULL,
                    envelope TEXT NOT NULL, text TEXT NOT NULL, ready REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS pacing (destination TEXT PRIMARY KEY, ready REAL NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, data, now=None):
        now = time.time() if now is None else now
        if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
            raise ValueError('Parâmetros inválidos.')
        route_id = data.get('route', '')
        route = self.config['routes'].get(route_id)
        if not route or data.get('provider') != route['provider']:
            raise ValueError('Rota inválida.')
        if data.get('kind') not in LABELS or data.get('format') not in ('plain', 'html'):
            raise ValueError('Formato inválido.')
        for key in ('recipient', 'token', 'text'):
            if not data.get(key) or len(data[key]) > (200000 if key == 'text' else 2048):
                raise ValueError('Campo inválido.')
        if '\r' in data['token'] or '\n' in data['token']:
            raise ValueError('Token inválido.')
        # Endpoints são fixados na configuração local, nunca fornecidos pelo webhook.
        envelope = {k: data.get(k, '') for k in ('recipient', 'token', 'group', 'proxy')}
        encoded = json.dumps(envelope, sort_keys=True, ensure_ascii=False)
        group_key = hashlib.sha256((route_id + encoded + data['kind']).encode()).hexdigest()
        # Compartilha o limite de frequência entre problema/recuperação e entre
        # mídias que utilizam o mesmo bot/serviço e destinatário.
        destination = hashlib.sha256(json.dumps([
            route['provider'], route.get('url', ''), data['token'], data['recipient']
        ]).encode()).hexdigest()
        text = visible_text(data['text'], data['format']) if route['provider'] == 'telegram' else data['text']
        if not text:
            raise ValueError('Mensagem vazia.')
        with self.connect() as db:
            db.execute('INSERT INTO incoming(route,group_key,destination,envelope,kind,text,created) '
                       'VALUES(?,?,?,?,?,?,?)',
                       (route_id, group_key, destination, encoded, data['kind'], text, now))

    def seal(self, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            groups = db.execute('SELECT group_key, MIN(created) AS first FROM incoming '
                                'GROUP BY group_key HAVING MIN(created)<=? ORDER BY first, MIN(id)',
                                (now - self.window,)).fetchall()
            for group in groups:
                rows = db.execute('SELECT * FROM incoming WHERE group_key=? AND created<=? '
                                  'ORDER BY id LIMIT 100',
                                  (group['group_key'], group['first'] + self.window)).fetchall()
                first = rows[0]
                route = self.config['routes'][first['route']]
                for text in messages([r['text'] for r in rows], first['kind'], route.get('max_chars', 3500)):
                    db.execute('INSERT INTO outbox(route,destination,envelope,text,ready) VALUES(?,?,?,?,?)',
                               (first['route'], first['destination'], first['envelope'], text, now))
                db.executemany('DELETE FROM incoming WHERE id=?', [(r['id'],) for r in rows])

    def step(self, sender=deliver, now=None):
        simulated = now is not None
        now = time.time() if now is None else now
        self.seal(now)
        with self.connect() as db:
            row = db.execute('''SELECT o.* FROM outbox o
                LEFT JOIN pacing p ON p.destination=o.destination
                WHERE o.ready<=? AND COALESCE(p.ready,0)<=?
                  AND NOT EXISTS (SELECT 1 FROM outbox older
                      WHERE older.destination=o.destination AND older.id<o.id)
                ORDER BY o.id LIMIT 1''', (now, now)).fetchone()
        if row is None:
            return False
        route = self.config['routes'][row['route']]
        try:
            sender(route, json.loads(row['envelope']), row['text'])
        except DeliveryError as error:
            delay = max(min(300, 5 * 2 ** min(row['attempts'], 6)), error.retry_after)
            finished = now if simulated else time.time()
            with self.connect() as db:
                db.execute('UPDATE outbox SET attempts=attempts+1,ready=? WHERE id=?', (finished + delay, row['id']))
                db.execute('INSERT OR REPLACE INTO pacing VALUES(?,?)', (row['destination'], finished + delay))
            LOG.warning('Entrega adiada: rota=%s tentativa=%d motivo=%s',
                        row['route'], row['attempts'] + 1, error)
        else:
            finished = now if simulated else time.time()
            interval = 3.1 if route['provider'] == 'telegram' else 1.1
            with self.connect() as db:
                db.execute('DELETE FROM outbox WHERE id=?', (row['id'],))
                db.execute('INSERT OR REPLACE INTO pacing VALUES(?,?)', (row['destination'], finished + interval))
            LOG.info('Parte entregue: rota=%s', row['route'])
        return True

    def stats(self):
        with self.connect() as db:
            return {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                    for table in ('incoming', 'outbox')}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        expected = 'Bearer ' + self.server.queue.config['token']
        supplied = self.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            self.reply(401, {'accepted': False})
            return False
        return True

    def do_GET(self):
        if not self.authenticated():
            return
        if self.path != '/health':
            return self.reply(404, {})
        digest = hashlib.sha256(json.dumps(self.server.queue.config, sort_keys=True).encode()).hexdigest()
        self.reply(200, {'ok': self.server.worker.is_alive(), 'config_sha256': digest,
                         **self.server.queue.stats()})

    def do_POST(self):
        self.connection.settimeout(10)
        if not self.authenticated():
            return
        if self.path != '/enqueue':
            return self.reply(404, {'accepted': False})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_REQUEST:
                return self.reply(413, {'accepted': False})
            data = json.loads(self.rfile.read(length))
            self.server.queue.enqueue(data)
        except (ValueError, UnicodeError, TypeError):
            return self.reply(400, {'accepted': False})
        except sqlite3.Error:
            LOG.error('Falha ao persistir notificação.')
            return self.reply(503, {'accepted': False})
        self.reply(202, {'accepted': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads(args.config.read_text())
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # Garante um único consumidor para não duplicar partes em processos concorrentes.
    lock = open(str(args.database) + '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    queue = Queue(args.database, config)
    stopped = threading.Event()

    def work():
        while not stopped.is_set():
            try:
                active = queue.step()
            except Exception:
                # Tracebacks de urllib podem conter token/URL do Telegram.
                LOG.error('Falha interna do consumidor; mensagens preservadas na fila.')
                active = False
            stopped.wait(0.1 if active else 0.5)

    worker = threading.Thread(target=work, daemon=True)
    server = ThreadingHTTPServer(('127.0.0.1', 8791), Handler)
    server.timeout = 0.5
    server.queue, server.worker = queue, worker
    worker.start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    LOG.info('Fila local iniciada; janela=%ds.', queue.window)
    try:
        while not stopped.is_set():
            server.handle_request()
    finally:
        server.server_close()
        stopped.set()
        worker.join(timeout=20)


if __name__ == '__main__':
    main()
