#!/usr/bin/env python3
"""Read-only Zabbix client. Credentials live in the session's Secret Service."""
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULTS = dict(url='', username='',
                auth_mode='password', interval=30, min_severity=0, notifications=True,
                panel_position='right', theme='dark', font_size=11, icon_size=16, spacing=5, window_font_size=13)
PREFERENCE_KEYS = ('interval', 'min_severity', 'notifications', 'panel_position', 'theme',
                   'font_size', 'icon_size', 'spacing', 'window_font_size')
SEVERITIES = ['Não classificado', 'Informação', 'Advertência', 'Médio', 'Alto', 'Desastre']


class MonitorError(Exception):
    def __init__(self, message, kind='connection'):
        super().__init__(message)
        self.kind = kind


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'alert-zabbix/settings.json'


def normalize(config, require_connection=False):
    result = {**DEFAULTS, **{key: value for key, value in config.items() if key in DEFAULTS}}
    url = str(result['url']).strip().rstrip('/')
    if url.endswith('/api_jsonrpc.php'):
        url = url[:-len('/api_jsonrpc.php')]
    parts = urllib.parse.urlsplit(url)
    if url and (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment):
        raise MonitorError('Informe uma URL HTTP ou HTTPS válida, sem usuário ou senha.', 'config')
    result['url'] = url
    result['username'] = str(result['username']).strip()
    if result['auth_mode'] not in ('password', 'token'):
        raise MonitorError('Modo de autenticação inválido.', 'config')
    if result['panel_position'] not in ('left', 'right'):
        raise MonitorError('Posição da barra inválida.', 'config')
    if result['theme'] not in ('dark', 'light', 'system'):
        raise MonitorError('Tema inválido.', 'config')
    if require_connection and not url:
        raise MonitorError('Informe o endereço do Zabbix em Configurar conexão.', 'config')
    if require_connection and result['auth_mode'] == 'password' and not result['username']:
        raise MonitorError('Informe o usuário da interface web do Zabbix.', 'config')
    try:
        result['interval'] = max(30, min(900, int(result['interval'])))
        result['min_severity'] = max(0, min(5, int(result['min_severity'])))
    except (ValueError, TypeError):
        raise MonitorError('Intervalo ou severidade inválidos.', 'config') from None
    try:
        for key, low, high in [('font_size', 9, 20), ('icon_size', 10, 32), ('spacing', 2, 20), ('window_font_size', 11, 18)]:
            result[key] = max(low, min(high, int(result[key])))
    except (ValueError, TypeError):
        raise MonitorError('Tamanho da letra, ícone ou espaçamento inválido.', 'config') from None
    result['notifications'] = bool(result['notifications'])
    return result


def load_config():
    try:
        value = json.loads(config_path().read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return normalize(value)
    except FileNotFoundError:
        return normalize({})
    except (ValueError, OSError):
        raise MonitorError('Não foi possível ler a configuração. Abra Configurar conexão.', 'config') from None


def save_config(config, require_connection=True):
    config = normalize(config, require_connection=require_connection)
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_preferences(changes):
    config = load_config()
    config.update({key: changes[key] for key in PREFERENCE_KEYS if key in changes})
    save_config(config, require_connection=False)
    return config


def secret_access(config, value=None):
    config = normalize(config, require_connection=True)
    try:
        import gi
        gi.require_version('Secret', '1')
        from gi.repository import Secret
        schema = Secret.Schema.new('org.gezer.AlertZabbix', Secret.SchemaFlags.NONE,
                                   {key: Secret.SchemaAttributeType.STRING
                                    for key in ('application', 'server', 'user', 'mode')})
        attrs = dict(application='alert-zabbix', server=config['url'],
                     user=config['username'], mode=config['auth_mode'])
        if value is None:
            return Secret.password_lookup_sync(schema, attrs, None)
        if not Secret.password_store_sync(schema, attrs, Secret.COLLECTION_DEFAULT,
                                          'Alertas Zabbix · ' + config['url'], value, None):
            raise RuntimeError('Secret Service recusou a gravação.')
    except Exception:
        raise MonitorError('Não foi possível acessar o chaveiro do Ubuntu. Verifique se ele está desbloqueado.', 'config') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, config):
        self.config = normalize(config, require_connection=True)
        self.endpoint = self.config['url'] + '/api_jsonrpc.php'
        self.opener = urllib.request.build_opener(NoRedirect())
        self.auth = None
        self.request_id = 0

    def call(self, method, params):
        self.request_id += 1
        body = dict(jsonrpc='2.0', method=method, params=params, id=self.request_id)
        if self.auth:
            body['auth'] = self.auth
        req = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json-rpc'})
        try:
            with self.opener.open(req, timeout=10) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise MonitorError('Resposta do Zabbix excedeu o limite de 4 MB.')
            result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise MonitorError(f'Zabbix respondeu HTTP {exc.code}. Confira a URL e as permissões.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise MonitorError('Sem conexão com o Zabbix. Confira a rede ou VPN.') from None
        except (ValueError, UnicodeError):
            raise MonitorError('A URL não retornou uma resposta JSON válida da API.') from None
        if not isinstance(result, dict):
            raise MonitorError('Resposta inválida da API.')
        if 'error' in result:
            if method == 'user.login':
                raise MonitorError('Login recusado: confira usuário, senha ou bloqueio da conta.', 'auth')
            error = str(result['error']).lower()
            if 'permission' in error or 'authoriz' in error or 'session' in error or 'token' in error:
                raise MonitorError('Acesso recusado. Confira a credencial e as permissões da API.', 'auth')
            raise MonitorError('A API recusou a consulta ' + method + '.', 'api')
        if 'result' not in result:
            raise MonitorError('Resposta incompleta da API.')
        return result['result']

    def snapshot(self, secret):
        if not secret:
            raise MonitorError('Configure a senha ou o token no chaveiro do Ubuntu.', 'config')
        version = self.call('apiinfo.version', {})
        if str(version).split('.')[:2] != ['6', '4']:
            raise MonitorError('Esta versão do aplicativo foi preparada para Zabbix 6.4. Servidor: ' + str(version), 'config')
        logged_in = self.config['auth_mode'] == 'password'
        self.auth = self.call('user.login', {'username': self.config['username'], 'password': secret}) if logged_in else secret
        try:
            problems = self.call('problem.get', {'output': ['eventid', 'objectid', 'name', 'severity', 'clock', 'acknowledged', 'r_eventid'],
                                                'source': 0, 'object': 0, 'suppressed': False, 'recent': False})
            problems = [p for p in problems if str(p['r_eventid']) == '0'
                        and int(p['severity']) >= self.config['min_severity']]
            triggers = self.call('trigger.get', {'output': ['triggerid'], 'triggerids': list({p['objectid'] for p in problems}),
                                                  'active': True, 'selectHosts': ['hostid', 'name', 'status']}) if problems else []
            # A multi-host trigger is eligible only while all its hosts are enabled.
            # Missing/filtered triggers must not reappear as "Host não disponível".
            hosts = {t['triggerid']: ', '.join(h['name'] for h in t['hosts']) for t in triggers
                     if t.get('hosts') and all(str(h.get('status')) == '0' for h in t['hosts'])}
            rows = [dict(id=p['eventid'], trigger=p['objectid'], name=p['name'],
                         host=hosts[p['objectid']], severity=int(p['severity']),
                         clock=int(p['clock']), acknowledged=p['acknowledged'] == '1',
                         url=self.config['url'] + '/tr_events.php?' + urllib.parse.urlencode({'triggerid': p['objectid'], 'eventid': p['eventid']}))
                    for p in problems if p['objectid'] in hosts]
            rows.sort(key=lambda p: (-p['severity'], -p['clock'], p['id']))
            return dict(ok=True, version=version, checked_at=time.time(), problems=rows, config=self.config)
        finally:
            if logged_in:
                try:
                    self.call('user.logout', [])
                except MonitorError:
                    pass
            self.auth = None


def main():
    try:
        config = normalize(load_config(), require_connection=True)
        state = API(config).snapshot(secret_access(config))
    except MonitorError as error:
        state = dict(ok=False, error=str(error), kind=error.kind)
    except Exception:
        state = dict(ok=False, error='Falha ao consultar o Zabbix. Confira a configuração.', kind='api')
    print(json.dumps(state, ensure_ascii=False))


if __name__ == '__main__':
    main()
