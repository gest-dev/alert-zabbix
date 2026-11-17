import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
from client import API, DEFAULTS, MonitorError, NoRedirect, config_path, load_config, normalize, save_config, save_preferences

TEST_CONFIG = {**DEFAULTS, 'url': 'https://zabbix.example.test/zabbix', 'username': 'test-user'}


class FakeTransport:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

        self.values = {
            'apiinfo.version': '6.4.21', 'user.login': 'test-session', 'user.logout': True,
            'problem.get': [
                dict(eventid='1', objectid='10', name='CPU alta', severity='2', clock='100', acknowledged='0', r_eventid='0'),
                dict(eventid='2', objectid='20', name='Disco cheio', severity='4', clock='200', acknowledged='1', r_eventid='0'),
                dict(eventid='3', objectid='30', name='Já resolvido', severity='5', clock='300', acknowledged='0', r_eventid='4')],
            'trigger.get': [dict(triggerid='10', hosts=[dict(hostid='1', name='Servidor A', status='0')]),
                            dict(triggerid='20', hosts=[dict(hostid='2', name='Servidor B', status='0')])],
        }

    def open(self, req, timeout):
        body = json.loads(req.data)
        self.calls.append(body)
        method = body['method']
        response = {'jsonrpc': '2.0', 'id': body['id'], 'result': self.values[method]}
        if method == self.fail:
            response = {'jsonrpc': '2.0', 'id': body['id'],
                        'error': {'message': 'Application error.', 'data': 'Incorrect user name or password.'}}
        return io.BytesIO(json.dumps(response).encode())


class ClientTests(unittest.TestCase):
    def api(self, config=None, fail=None):
        api = API(config or TEST_CONFIG)
        api.opener = FakeTransport(fail)
        return api

    def test_read_only_snapshot_maps_hosts_and_severity(self):
        api = self.api()
        state = api.snapshot('test-password')
        self.assertEqual([p['id'] for p in state['problems']], ['2', '1'])
        self.assertEqual(state['problems'][0]['host'], 'Servidor B')
        self.assertTrue(state['problems'][0]['acknowledged'])
        self.assertNotIn('visible_hosts', state)
        self.assertNotIn('monitored_hosts', state)
        calls = api.opener.calls
        self.assertEqual(calls[-1]['method'], 'user.logout')
        self.assertTrue(all(c['method'] in {'apiinfo.version', 'user.login', 'user.logout', 'problem.get', 'trigger.get'} for c in calls))
        problems_call = next(c for c in calls if c['method'] == 'problem.get')
        self.assertIs(problems_call['params']['recent'], False)
        triggers_call = next(c for c in calls if c['method'] == 'trigger.get')
        self.assertNotIn('30', triggers_call['params']['triggerids'])
        self.assertIs(triggers_call['params']['active'], True)
        self.assertIn('status', triggers_call['params']['selectHosts'])
        self.assertNotIn('test-password', json.dumps(state))
        self.assertNotIn('test-session', json.dumps(state))
        self.assertIsNone(api.auth)

    def test_login_failure_does_not_repeat_or_query(self):
        api = self.api(fail='user.login')
        with self.assertRaises(MonitorError) as caught:
            api.snapshot('wrong')
        self.assertEqual(caught.exception.kind, 'auth')
        self.assertEqual([c['method'] for c in api.opener.calls], ['apiinfo.version', 'user.login'])

    def test_disabled_hosts_missing_triggers_and_mixed_host_triggers_do_not_alert(self):
        api = self.api()
        for trigger in ('40', '50', '60'):
            api.opener.values['problem.get'].append(dict(eventid=trigger, objectid=trigger,
                name='Problema antigo de host desativado', severity='5', clock='400', acknowledged='0', r_eventid='0'))
        api.opener.values['trigger.get'].extend([
            dict(triggerid='40', hosts=[dict(hostid='4', name='Desativado', status='1')]),
            # Trigger 50 was filtered out by the API; event must also disappear.
            dict(triggerid='60', hosts=[dict(hostid='1', name='Ativo', status='0'),
                                      dict(hostid='4', name='Desativado', status='1')])])
        state = api.snapshot('test-password')
        self.assertEqual([p['id'] for p in state['problems']], ['2', '1'])
        # This same list feeds the panel count and notification comparison.
        self.assertNotIn('Problema antigo', json.dumps(state))

    def test_enabled_host_that_is_unreachable_still_alerts(self):
        api = self.api()
        api.opener.values['problem.get'] = [dict(eventid='1', objectid='10', name='Zabbix agent is not available',
            severity='4', clock='100', acknowledged='0', r_eventid='0')]
        state = api.snapshot('test-password')
        self.assertEqual(len(state['problems']), 1)
        self.assertEqual(state['problems'][0]['name'], 'Zabbix agent is not available')

    def test_disabling_a_host_removes_its_existing_problem_on_next_refresh(self):
        api = self.api()
        self.assertEqual(len(api.snapshot('test-password')['problems']), 2)
        api.opener.values['trigger.get'][0]['hosts'][0]['status'] = '1'
        self.assertEqual([p['id'] for p in api.snapshot('test-password')['problems']], ['2'])
        api.opener.values['trigger.get'][1]['hosts'][0]['status'] = '1'
        self.assertEqual(api.snapshot('test-password')['problems'], [])

    def test_logout_even_when_problem_query_fails(self):
        api = self.api(fail='problem.get')
        with self.assertRaises(MonitorError):
            api.snapshot('test')
        self.assertEqual(api.opener.calls[-1]['method'], 'user.logout')
        self.assertIsNone(api.auth)

    def test_token_is_not_logged_out_and_filter_is_applied(self):
        api = self.api({**TEST_CONFIG, 'auth_mode': 'token', 'min_severity': 4})
        state = api.snapshot('test-token')
        self.assertEqual(len(state['problems']), 1)
        self.assertEqual(state['problems'][0]['severity'], 4)
        methods = [c['method'] for c in api.opener.calls]
        self.assertNotIn('user.login', methods)
        self.assertNotIn('user.logout', methods)
        self.assertEqual(api.opener.calls[1]['auth'], 'test-token')

    def test_config_strips_credentials_and_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            save_config({**TEST_CONFIG, 'password': 'never-save', 'token': 'never-save'})
            self.assertNotIn('never-save', config_path().read_text())
            self.assertEqual(config_path().stat().st_mode & 0o777, 0o600)
            self.assertEqual(config_path().parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(load_config(), TEST_CONFIG)

    def test_url_and_interval_validation(self):
        for url in ['file:///etc/passwd', 'http://user:secret@host/zabbix', 'https://host/?password=abc']:
            with self.assertRaises(MonitorError):
                normalize(dict(url=url))
        self.assertEqual(normalize(dict(url=TEST_CONFIG['url'] + '/api_jsonrpc.php'))['url'], TEST_CONFIG['url'])
        self.assertEqual(normalize(dict(interval=1))['interval'], 10)

    def test_credentials_are_not_forwarded_on_redirect(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 307, '', {}, 'https://other-host/'))

    def test_first_launch_has_no_server_or_account_and_does_not_make_requests(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            config = load_config()
        self.assertEqual(config['url'], '')
        self.assertEqual(config['username'], '')
        with patch('client.urllib.request.build_opener') as opener:
            with self.assertRaises(MonitorError) as caught:
                API(config)
            opener.assert_not_called()
        self.assertEqual(caught.exception.kind, 'config')

    def test_username_required_only_for_password_authentication(self):
        with self.assertRaises(MonitorError):
            API({**TEST_CONFIG, 'username': ''})
        self.assertEqual(API({**TEST_CONFIG, 'username': '', 'auth_mode': 'token'}).config['username'], '')

    def test_visual_preferences_save_without_a_server_and_preserve_connection(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            save_preferences({'panel_position': 'left', 'theme': 'light'})
            self.assertEqual(load_config()['panel_position'], 'left')
            self.assertEqual(load_config()['url'], '')
            save_config(TEST_CONFIG)
            save_preferences({'panel_position': 'left', 'url': 'https://wrong.example.test', 'username': 'wrong'})
            saved = load_config()
            self.assertEqual(saved['url'], TEST_CONFIG['url'])
            self.assertEqual(saved['username'], TEST_CONFIG['username'])
            self.assertEqual(saved['panel_position'], 'left')
            for changes in ({'panel_position': 'invalid'}, {'theme': 'invalid'}):
                with self.assertRaises(MonitorError):
                    save_preferences(changes)
                self.assertEqual(load_config(), saved)

    def test_sizes_migrate_validate_and_stay_within_supported_limits(self):
        old_config = {key: value for key, value in TEST_CONFIG.items()
                      if key not in ('font_size', 'icon_size', 'spacing', 'window_font_size')}
        self.assertEqual(normalize(old_config)['font_size'], 11)
        self.assertEqual(normalize(old_config)['icon_size'], 16)
        for key, low, high in [('font_size', 9, 20), ('icon_size', 10, 32), ('spacing', 2, 20), ('window_font_size', 11, 18)]:
            self.assertEqual(normalize({key: 0})[key], low)
            self.assertEqual(normalize({key: 999})[key], high)
            with self.assertRaises(MonitorError):
                normalize({key: 'invalid-css-value'})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            save_preferences(dict(font_size=9, icon_size=10, spacing=2, window_font_size=12))
            saved = load_config()
            self.assertEqual((saved['font_size'], saved['icon_size'], saved['spacing'], saved['window_font_size']), (9, 10, 2, 12))
            self.assertEqual(saved['url'], '')


if __name__ == '__main__':
    unittest.main()
