import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('configure_grouping',
    Path(__file__).resolve().parents[2] / 'configurar_agrupamento.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeAPI:
    endpoint = 'http://zabbix.example.invalid/api_jsonrpc.php'

    def __init__(self):
        self.media = []
        for i, (name, provider) in enumerate(module.MEDIA.items(), 42):
            params = {'Token': '{$PROVIDER.TOKEN}', 'To': '{ALERT.SENDTO}',
                      'Message': '{ALERT.MESSAGE}', 'Subject': '{ALERT.SUBJECT}'}
            if provider == 'telegram':
                params['ParseMode'] = 'HTML'
            else:
                params.update(Url='https://provider.example.invalid/send', Id='fixed-destination',
                              Group='true', Method='POST')
            self.media.append({'mediatypeid': str(i), 'name': name, 'type': '4', 'status': '0',
                               'script': '// Original ' + name,
                               'parameters': [{'name': k, 'value': v} for k, v in params.items()]})
        self.original = copy.deepcopy(self.media)
        self.macros = []
        self.mutations = []
        self.fail = None

    def call(self, method, params):
        if method == 'mediatype.get':
            return copy.deepcopy(self.media)
        if method == 'usermacro.get':
            return copy.deepcopy(self.macros)
        self.mutations.append((method, copy.deepcopy(params)))
        if method == 'mediatype.update':
            if params['mediatypeid'] == self.fail:
                self.fail = None
                raise RuntimeError('Falha simulada de atualização')
            found = next(m for m in self.media if m['mediatypeid'] == params['mediatypeid'])
            found.update(copy.deepcopy(params))
            return {'mediatypeids': [params['mediatypeid']]}
        if method == 'usermacro.createglobal':
            self.macros.append(dict(params, globalmacroid='100'))
            return {'globalmacroids': ['100']}
        if method == 'usermacro.updateglobal':
            self.macros[0].update(params)
            return {'globalmacroids': ['100']}
        raise AssertionError('Mutação fora do escopo: ' + method)


class ConfigureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.package = Path(self.temp.name) / 'package'
        self.api = FakeAPI()
        module.prepare(self.api, self.package)

    def tearDown(self):
        self.temp.cleanup()

    def healthy(self, *args):
        return {'ok': True, 'incoming': 0, 'outbox': 0}

    def test_preparation_is_read_only_and_private(self):
        self.assertEqual(self.api.mutations, [])
        self.assertEqual(self.package.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.package / 'service-config.json').stat().st_mode & 0o777, 0o600)
        config = json.loads((self.package / 'service-config.json').read_text())
        self.assertEqual(config['window_seconds'], 30)
        self.assertTrue(all(r['max_chars'] == 3500 for r in config['routes'].values()))

    def test_activation_only_changes_scripts_parameters_and_queue_macro(self):
        with patch.object(module, 'check_health', side_effect=self.healthy):
            module.apply(self.api, self.package, 'server', 22)
        for original, modified in zip(self.api.original, self.api.media):
            self.assertEqual(original['mediatypeid'], modified['mediatypeid'])
            self.assertEqual(original['name'], modified['name'])
            self.assertEqual(original['type'], modified['type'])
            self.assertEqual(original['status'], modified['status'])
            modified_params = {p['name']: p['value'] for p in modified['parameters']}
            for p in original['parameters']:
                self.assertEqual(modified_params[p['name']], p['value'])
        for method, params in self.api.mutations:
            if method == 'mediatype.update':
                self.assertEqual(set(params), {'mediatypeid', 'script', 'parameters'})
            else:
                self.assertEqual(method, 'usermacro.createglobal')
                self.assertEqual(params['macro'], module.TOKEN_MACRO)

    def test_unhealthy_queue_prevents_all_mutations(self):
        with patch.object(module, 'check_health', side_effect=RuntimeError('Fila indisponível')):
            with self.assertRaises(RuntimeError):
                module.apply(self.api, self.package, 'server', 22)
        self.assertEqual(self.api.mutations, [])

    def test_partial_api_failure_restores_previous_media(self):
        self.api.fail = '43'
        with patch.object(module, 'check_health', side_effect=self.healthy):
            with self.assertRaises(RuntimeError):
                module.apply(self.api, self.package, 'server', 22)
        self.assertEqual(self.api.media, self.api.original)

    def test_manual_changes_are_not_overwritten(self):
        self.api.media[0]['script'] = '// Alteração posterior de administrador'
        with patch.object(module, 'check_health', side_effect=self.healthy):
            with self.assertRaises(RuntimeError):
                module.apply(self.api, self.package, 'server', 22)
        self.assertEqual(self.api.mutations, [])

    def test_restore_recovers_original_scripts_and_parameters(self):
        with patch.object(module, 'check_health', side_effect=self.healthy):
            module.apply(self.api, self.package, 'server', 22)
            module.apply(self.api, self.package, 'server', 22, restore=True)
        self.assertEqual(self.api.media, self.api.original)


if __name__ == '__main__':
    unittest.main()
