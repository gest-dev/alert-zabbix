#!/usr/bin/env python3
"""Aplica o padrão GEST e verificações dos serviços da VM uiluolt."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from configurar_alerta_agente_rapido import configure as configure_agent
from configurar_alertas_disco import configure as configure_disk

BASE = Path(__file__).resolve().parent
HOST = 'uiluolt'
TEMPLATE = 'GEST-cpu-hd-uiluolt'
LINUX = 'Linux by Zabbix agent'
SERVICES = [
    ('PM2', 'PM2', 'pm2-root.service'),
    ('MONGODB', 'MongoDB', 'mongod.service'),
    ('GENIEACS.CWMP', 'GenieACS CWMP', 'genieacs-cwmp.service'),
    ('GENIEACS.FS', 'GenieACS FS', 'genieacs-fs.service'),
    ('GENIEACS.NBI', 'GenieACS NBI', 'genieacs-nbi.service'),
    ('GENIEACS.UI', 'GenieACS UI', 'genieacs-ui.service'),
    ('OPENVPN', 'OpenVPN', 'openvpn-server@server.service'),
    ('OPENVPN.ROUTEROS6', 'OpenVPN RouterOS 6', 'openvpn-server@server-routeros6.service')]


def configure(api):
    hosts = api.call('host.get', {'filter': {'host': HOST}, 'output': 'extend',
        'selectParentTemplates': ['templateid', 'host'], 'selectMacros': 'extend'})
    linux = api.call('template.get', {'filter': {'host': LINUX}, 'output': ['templateid']})
    groups = api.call('templategroup.get', {'filter': {'name': 'GEST'}, 'output': ['groupid']})
    found = api.call('template.get', {'filter': {'host': TEMPLATE}, 'output': 'extend'})
    if len(hosts) != 1 or len(linux) != 1 or len(groups) != 1 or len(found) > 1:
        raise RuntimeError('Host, base Linux ou grupo GEST ausente/ambíguo.')
    host = hosts[0]
    hid, lid = host['hostid'], linux[0]['templateid']
    before_items = api.call('item.get', {'hostids': [hid], 'output': ['itemid', 'key_', 'status']})
    before_dashboard = api.call('dashboard.get', {'dashboardids': ['1'],
        'output': 'extend', 'selectPages': 'extend'})
    directory = Path.home() / '.local/share/alert-zabbix/backups'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = directory / f'uiluolt-before-gest-template-{time.time_ns()}.json'
    snapshot = {'host': host, 'items': before_items, 'dashboard': before_dashboard,
        'triggers': api.call('trigger.get', {'hostids': [hid], 'output': 'extend'}),
        'discovery_rules': api.call('discoveryrule.get', {'hostids': [hid], 'output': 'extend'}),
        'templates': found}
    if found:
        snapshot['template_export'] = api.call('configuration.export', {
            'format': 'yaml', 'options': {'templates': [found[0]['templateid']]}})
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)

    if found:
        tid = found[0]['templateid']
    else:
        tid = api.call('template.create', {
            'host': TEMPLATE, 'name': TEMPLATE,
            'groups': [{'groupid': groups[0]['groupid']}],
            'templates': [{'templateid': lid}],
            'description': 'VM uiluolt com base Linux: CPU, memória, discos, rede e uptime. '
                'Padrão GEST de disco 90%/95% por três coletas e falha TCP do agente '
                'por 1 minuto. Verifica processo e porta uiluolt, MongoDB, PM2, GenieACS '
                'e OpenVPN pelo Agent 2. Serviços: 1 minuto de falha e 30 segundos de '
                'recuperação. Reaplicar configurar_template_uiluolt.py após importar '
                'para ajustar os status herdados. Não usa credenciais de banco.'
        })['templateids'][0]
    macros = {
        '{$UILUOLT.INTERVAL}': ('15s', 'Intervalo das verificações dos serviços.'),
        '{$UILUOLT.APP.PORT}': ('3333', 'Porta da aplicação, consultada pelo servidor Zabbix.'),
        '{$UILUOLT.MONGODB.PORT}': ('27017', 'Porta MongoDB consultada localmente pelo agente.'),
        '{$UILUOLT.PROCESS.MATCHES}': ('/root/uiluolt/build/bin/server\\.js',
            'Expressão regular do processo da aplicação, sem considerar outros processos Node.js.')}
    for suffix, label, unit in SERVICES:
        macros['{$UILUOLT.SERVICE.' + suffix + '}'] = (unit, 'Unidade systemd de ' + label + '.')
    old_macros = {m['macro']: m for m in api.call('usermacro.get', {'hostids': [tid],
        'output': ['hostmacroid', 'macro']})}
    for name, (value, description) in macros.items():
        data = {'value': value, 'description': description}
        if name in old_macros:
            api.call('usermacro.update', dict(data, hostmacroid=old_macros[name]['hostmacroid']))
        else:
            api.call('usermacro.create', dict(data, hostid=tid, macro=name))
    maps = api.call('valuemap.get', {'hostids': [tid],
        'filter': {'name': 'GEST - Serviço disponível'}, 'output': ['valuemapid']})
    mapid = maps[0]['valuemapid'] if maps else api.call('valuemap.create', {
        'hostid': tid, 'name': 'GEST - Serviço disponível', 'mappings': [
            {'value': '0', 'newvalue': 'Indisponível'},
            {'value': '1', 'newvalue': 'Disponível'}]})['valuemapids'][0]
    items = {i['key_']: i['itemid'] for i in api.call('item.get', {
        'hostids': [tid], 'output': ['itemid', 'key_']})}
    triggers = {t['description']: t['triggerid'] for t in api.call('trigger.get', {
        'hostids': [tid], 'output': ['triggerid', 'description', 'templateid']})
        if t['templateid'] == '0'}

    def item(key, name, **extra):
        data = {'key_': key, 'name': name, 'type': 0, 'value_type': 3,
            'delay': '{$UILUOLT.INTERVAL}', 'history': '7d', 'trends': '90d',
            'tags': [{'tag': 'component', 'value': 'service'}, {'tag': 'application', 'value': HOST}]}
        data.update(extra)
        if key in items:
            api.call('item.update', dict(data, itemid=items[key]))
        else:
            items[key] = api.call('item.create', dict(data, hostid=tid))['itemids'][0]

    def service(key, name, **extra):
        item(key, name, **extra)
        path = '/' + TEMPLATE + '/' + key
        title = '{HOST.NAME}: ' + name + ' indisponível'
        data = {'description': title,
            'expression': f'max({path},1m)=0 and last({path},#1:now-1m)=0',
            'recovery_mode': 1,
            'recovery_expression': f'min({path},30s)>=1 and last({path},#1:now-30s)>=1',
            'priority': 4, 'status': 0,
            'comments': 'Falha contínua por 1 minuto, recuperação após 30 segundos estáveis. '
                'As expressões conferem também o início da janela para evitar confirmação '
                'com poucas amostras. Porta e processo não confirmam operações internas da aplicação.',
            'tags': [{'tag': 'component', 'value': 'service'}, {'tag': 'application', 'value': HOST}]}
        if title in triggers:
            api.call('trigger.update', dict(data, triggerid=triggers[title]))
        else:
            triggers[title] = api.call('trigger.create', data)['triggerids'][0]

    item('vfs.fs.size[/,free]', 'Disco /: espaço livre', units='B', delay='1m',
        tags=[{'tag': 'component', 'value': 'storage'}])
    service('proc.num[,,,"{$UILUOLT.PROCESS.MATCHES}"]', 'uiluolt: processo Node.js')
    service('net.tcp.service[tcp,,{$UILUOLT.APP.PORT}]', 'uiluolt: porta da aplicação',
        type=3, valuemapid=mapid)
    service('net.tcp.service[tcp,127.0.0.1,{$UILUOLT.MONGODB.PORT}]',
        'MongoDB: porta local', valuemapid=mapid)
    for suffix, label, unit in SERVICES:
        service('systemd.unit.info[{$UILUOLT.SERVICE.' + suffix + '},ActiveState]',
            label + ': serviço systemd', valuemapid=mapid,
            preprocessing=[{'type': 21, 'params':
                'return (value === "active" || value === "reloading") ? 1 : 0;',
                'error_handler': 0, 'error_handler_params': ''}])

    parents = [p['templateid'] for p in host['parentTemplates']]
    if tid not in parents:
        # Desvincula SEM limpar para incorporar os mesmos itens, regras e gráficos.
        retained = [p for p in parents if p != lid]
        if lid in parents:
            api.call('host.update', {'hostid': hid,
                'templates': [{'templateid': p} for p in retained]})
        api.call('host.update', {'hostid': hid,
            'templates': [{'templateid': p} for p in retained + [tid]]})

    disk = configure_disk(api, TEMPLATE)
    agent = configure_agent(api, TEMPLATE)
    after_items = api.call('item.get', {'hostids': [hid], 'output': ['itemid', 'key_', 'type']})
    bykey = {i['key_']: i for i in after_items}
    for old in before_items:
        if old['key_'] not in bykey or old['itemid'] != bykey[old['key_']]['itemid']:
            raise RuntimeError('ID de item anterior não foi preservado: ' + old['key_'])
    after_dashboard = api.call('dashboard.get', {'dashboardids': ['1'],
        'output': 'extend', 'selectPages': 'extend'})
    if after_dashboard != before_dashboard:
        raise RuntimeError('O dashboard foi alterado durante a configuração.')
    poll = [i['itemid'] for i in after_items if i['key_'] in items
            and i['type'] in ('0', '3')]
    api.call('task.create', [{'type': 6, 'request': {'itemid': ident}} for ident in poll])
    exported = api.call('configuration.export', {'format': 'yaml',
        'options': {'templates': [tid]}})
    (BASE / 'templates/gest-cpu-hd-uiluolt.yaml').write_text(exported + '\n')
    return {'template': TEMPLATE, 'templateid': tid, 'hostid': hid,
        'original_items_preserved': len(before_items), 'dashboard_preserved': True,
        'disk': disk, 'agent': agent, 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    sys.path.insert(0, str(BASE.parent / 'extension'))
    from client import API, load_config, secret_access
    cfg = load_config()
    api = API(cfg)
    api.auth = (api.call('user.login', {'username': cfg['username'],
        'password': secret_access(cfg)}) if cfg['auth_mode'] == 'password' else secret_access(cfg))
    try:
        print(json.dumps(configure(api), ensure_ascii=False, indent=2))
    finally:
        if cfg['auth_mode'] == 'password':
            api.call('user.logout', [])


if __name__ == '__main__':
    main()
