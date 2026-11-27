#!/usr/bin/env python3
"""Prepara e ativa agrupamento apenas nas mídias WhatsApp/Telegram existentes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
from client import API, load_config, secret_access

MEDIA = {'TelegramHome': 'telegram', 'WhatsappAstro': 'astro',
         'WhatsappAtivDurvs': 'ativ', 'WhatsApp Ur Telecom': 'astro'}
TOKEN_MACRO = '{$NOTIFY.GROUP.TOKEN}'
TOKEN_DESCRIPTION = 'Chave da fila local de entregas WhatsApp/Telegram (agrupamento).'
ROOT = Path(__file__).resolve().parent / 'media'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def media_state(media):
    return {key: media[key] for key in ('mediatypeid', 'name', 'type', 'script', 'parameters')}


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def prepare(api, directory):
    if directory.exists():
        raise RuntimeError('Use uma pasta nova para preservar o pacote e o backup anteriores.')
    media = api.call('mediatype.get', {'filter': {'name': list(MEDIA)}, 'output': 'extend',
                                      'selectMessageTemplates': 'extend'})
    if {m['name'] for m in media} != set(MEDIA):
        raise RuntimeError('Não foram encontradas exatamente as quatro mídias esperadas.')
    macros = api.call('usermacro.get', {'globalmacro': True, 'output': 'extend'})
    if any(m['macro'] == TOKEN_MACRO for m in macros):
        raise RuntimeError('A macro da fila já existe; reutilize o pacote original ou revise a instalação.')
    macro_values = {m['macro']: m['value'] for m in macros if m.get('type', '0') == '0'}
    config = {'token': secrets.token_urlsafe(48), 'window_seconds': 30, 'routes': {}}
    changes = []
    script = (ROOT / 'grouped-delivery.js').read_text()
    for m in media:
        provider = MEDIA[m['name']]
        params = {p['name']: p['value'] for p in m['parameters']}
        if m['type'] != '4' or m['status'] != '0':
            raise RuntimeError('Mídia não está habilitada como webhook: ' + m['name'])
        if any(name.startswith('Queue') for name in params):
            raise RuntimeError('Mídia já configurada para uma fila: ' + m['name'])
        if provider == 'telegram' and params.get('ParseMode', '').lower() not in ('', 'html', 'plain'):
            raise RuntimeError('Este agrupador suporta Telegram em HTML ou texto simples.')
        if provider == 'astro' and params.get('Method', 'POST') != 'POST':
            raise RuntimeError('Serviço Astro precisa usar POST para preservar o contrato.')
        route = {'provider': provider, 'max_chars': 3500}
        if provider != 'telegram':
            url = params['Url']
            if url.startswith('{$'):
                if url not in macro_values:
                    raise RuntimeError('URL precisa estar em uma macro global de texto disponível.')
                url = macro_values[url]
            route['url'] = url
        config['routes'][m['mediatypeid']] = route
        extra = {'QueueProvider': provider, 'QueueRoute': m['mediatypeid'],
                 'QueueUrl': 'http://127.0.0.1:8791/enqueue', 'QueueToken': TOKEN_MACRO,
                 'EventValue': '{EVENT.VALUE}', 'UpdateStatus': '{EVENT.UPDATE.STATUS}'}
        updated = [p for p in m['parameters'] if p['name'] not in extra]
        updated.extend({'name': k, 'value': v} for k, v in extra.items())
        changes.append({'original': media_state(m),
                        'updated': dict(media_state(m), script=script, parameters=updated)})
    # Valida também URLs, limites e configuração do serviço sem usar a rede.
    sys.path.insert(0, str(ROOT / 'grouping'))
    from service import Queue
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        Queue(Path(temporary) / 'check.sqlite3', config)
    directory.mkdir(mode=0o700, parents=True)
    write_private(directory / 'service-config.json', config)
    write_private(directory / 'plan.json', {'api_url': api.endpoint, 'media': changes,
                                           'config_sha256': fingerprint(config)})
    write_private(directory / 'media-before.json', media)
    for name in ('service.py', 'install.py', 'zabbix-message-group.service'):
        shutil.copyfile(ROOT / 'grouping' / name, directory / name)
        os.chmod(directory / name, 0o600)
    print('Pacote preparado em ' + str(directory) + '. Nenhuma mídia foi alterada.')
    print('Instale a fila no servidor e depois execute --apply com --ssh.')


def check_health(directory, ssh, port, expected, control_path=None):
    token = json.loads((directory / 'service-config.json').read_text())['token']
    # O token passa no stdin do SSH, nunca na linha de comando ou no terminal.
    code = ("import sys,json,urllib.request; "
            "t=json.load(sys.stdin)['token']; "
            "o=urllib.request.build_opener(urllib.request.ProxyHandler({})); "
            "r=urllib.request.Request('http://127.0.0.1:8791/health',headers={'Authorization':'Bearer '+t}); "
            "print(o.open(r,timeout=5).read().decode())")
    import shlex
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-p', str(port)]
    if control_path:
        command.extend(['-S', control_path])
    command.extend([ssh, 'python3 -c ' + shlex.quote(code)])
    response = subprocess.run(command, input=json.dumps({'token': token}),
                              text=True, capture_output=True, timeout=20)
    if response.returncode:
        raise RuntimeError('Não foi possível verificar a fila pelo SSH; mídias preservadas.')
    health = json.loads(response.stdout)
    if health.get('ok') is not True or health.get('config_sha256') != expected:
        raise RuntimeError('A fila instalada não está saudável ou não corresponde ao pacote.')
    return health


def apply(api, directory, ssh, port, restore=False, control_path=None):
    plan = json.loads((directory / 'plan.json').read_text())
    config = json.loads((directory / 'service-config.json').read_text())
    if plan['api_url'] != api.endpoint or fingerprint(config) != plan['config_sha256']:
        raise RuntimeError('Pacote não corresponde ao servidor ou foi alterado.')
    health = check_health(directory, ssh, port, plan['config_sha256'], control_path)
    if restore and (health['incoming'] or health['outbox']):
        raise RuntimeError('Espere a fila esvaziar antes de restaurar as mídias originais.')
    ids = [item['original']['mediatypeid'] for item in plan['media']]
    live = api.call('mediatype.get', {'mediatypeids': ids, 'output': 'extend'})
    current = {m['mediatypeid']: media_state(m) for m in live}
    # Ordem dos parâmetros não é significativa na API.
    def canonical(state):
        return dict(state, parameters=sorted(state['parameters'], key=lambda p: p['name']))
    for item in plan['media']:
        mid = item['original']['mediatypeid']
        if mid not in current or canonical(current[mid]) not in (
            canonical(item['original']), canonical(item['updated'])
        ):
            raise RuntimeError('Mídia mudou desde o backup; não sobrescrever: ' + item['original']['name'])
    if not restore:
        macros = api.call('usermacro.get', {'globalmacro': True,
                                           'filter': {'macro': TOKEN_MACRO}, 'output': 'extend'})
        data = {'value': config['token'], 'type': 1, 'description': TOKEN_DESCRIPTION}
        if macros:
            if len(macros) != 1 or macros[0].get('description') != TOKEN_DESCRIPTION:
                raise RuntimeError('Macro de fila existente pertence a outra configuração.')
            api.call('usermacro.updateglobal', dict(data, globalmacroid=macros[0]['globalmacroid']))
        else:
            api.call('usermacro.createglobal', dict(data, macro=TOKEN_MACRO))
    changed = []
    try:
        for item in plan['media']:
            target = item['original' if restore else 'updated']
            mid = target['mediatypeid']
            if canonical(current[mid]) == canonical(target):
                continue
            api.call('mediatype.update', {k: target[k] for k in ('mediatypeid', 'script', 'parameters')})
            changed.append(mid)
        verified = api.call('mediatype.get', {'mediatypeids': ids, 'output': 'extend'})
        actual = {m['mediatypeid']: media_state(m) for m in verified}
        for item in plan['media']:
            target = item['original' if restore else 'updated']
            if canonical(actual[target['mediatypeid']]) != canonical(target):
                raise RuntimeError('Verificação de mídia divergente.')
    except Exception:
        failures = []
        for mid in reversed(changed):
            try:
                api.call('mediatype.update', {k: current[mid][k] for k in ('mediatypeid', 'script', 'parameters')})
            except Exception:
                failures.append(mid)
        if failures:
            print('Restauração automática pendente para IDs: ' + ', '.join(failures), file=sys.stderr)
        raise
    print(('Mídias restauradas.' if restore else 'Agrupamento ativado nas quatro mídias.')
          + ' Dashboards, triggers, ações e destinatários não foram alterados.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', type=Path, metavar='PASTA_PRIVADA')
    group.add_argument('--apply', type=Path, metavar='PACOTE')
    group.add_argument('--restore', type=Path, metavar='PACOTE')
    parser.add_argument('--ssh', help='Usuário@servidor para verificar a fila antes de ativar.')
    parser.add_argument('--ssh-port', type=int, default=22)
    parser.add_argument('--ssh-control-path', help='Socket de uma conexão SSH autenticada existente.')
    args = parser.parse_args()
    if (args.apply or args.restore) and not args.ssh:
        parser.error('--apply/--restore requer --ssh para verificar a fila.')
    config = load_config()
    api = API(config)
    if not str(api.call('apiinfo.version', {})).startswith('6.4.'):
        raise RuntimeError('Configurador preparado para Zabbix 6.4.')
    api.auth = (secret_access(config) if config['auth_mode'] == 'token' else
                api.call('user.login', {'username': config['username'], 'password': secret_access(config)}))
    try:
        if args.prepare:
            prepare(api, args.prepare)
        else:
            apply(api, args.apply or args.restore, args.ssh, args.ssh_port, bool(args.restore),
                  args.ssh_control_path)
    finally:
        if config['auth_mode'] == 'password':
            api.call('user.logout', [])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Não imprimir tracebacks que possam carregar parâmetros/segredos.
        print('Não foi possível concluir: ' + str(error), file=sys.stderr)
        sys.exit(1)
