#!/usr/bin/env python3
"""Cria o template GEST Fail2Ban e o vincula aos hosts informados."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parent
TEMPLATE = 'GEST - Fail2Ban Linux'
KEY = 'fail2ban.status'
TRIGGER = 'Fail2Ban está inativo em {HOST.NAME}'
DEFAULT_HOSTIDS = ['10635', '10641']


def configure(api, hostids):
    hostids = list(dict.fromkeys(map(str, hostids)))
    hosts = api.call('host.get', {'hostids': hostids,
        'output': ['hostid', 'host', 'name', 'status'],
        'selectParentTemplates': ['templateid', 'host'],
        'selectInterfaces': ['interfaceid', 'main', 'type']})
    if {h['hostid'] for h in hosts} != set(hostids):
        raise RuntimeError('Um dos hosts informados não foi encontrado.')
    if any(not any(i['main'] == '1' and i['type'] == '1'
                   for i in h['interfaces']) for h in hosts):
        raise RuntimeError('Todos os hosts precisam de uma interface de agente.')
    found = api.call('template.get', {'filter': {'host': TEMPLATE},
        'output': ['templateid', 'host']})
    groups = api.call('templategroup.get', {'filter': {'name': 'GEST'},
        'output': ['groupid']})
    if len(found) > 1 or len(groups) != 1:
        raise RuntimeError('Template duplicado ou grupo de templates GEST ausente.')
    old_items = api.call('item.get', {'hostids': hostids,
        'output': ['itemid', 'hostid', 'key_']})
    directory = Path.home() / '.local/share/alert-zabbix/backups'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = directory / f'fail2ban-before-{time.time_ns()}.json'
    snapshot = {'hosts': hosts, 'items': old_items, 'templates': found}
    if found:
        snapshot['template_export'] = api.call('configuration.export', {
            'format': 'yaml', 'options': {'templates': [found[0]['templateid']]}})
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
    tid = found[0]['templateid'] if found else api.call('template.create', {
        'host': TEMPLATE, 'name': TEMPLATE,
        'groups': [{'groupid': groups[0]['groupid']}],
        'description': 'Estado do serviço Fail2Ban pelo UserParameter fail2ban.status, '
            'compatível com Zabbix agent e Agent 2. Coleta a cada 30 segundos; '
            'alerta Alto após 2 minutos de valores zero, com amostras suficientes '
            'e conferência no início da janela. Recupera na primeira leitura 1. '
            'Requer o parâmetro personalizado nos agentes. Não consulta jails ou '
            'quantidade de IPs banidos. Manter os alertas de comunicação do agente.'
    })['templateids'][0]
    maps = api.call('valuemap.get', {'hostids': [tid],
        'filter': {'name': 'GEST - Fail2Ban'}, 'output': ['valuemapid']})
    mapid = maps[0]['valuemapid'] if maps else api.call('valuemap.create', {
        'hostid': tid, 'name': 'GEST - Fail2Ban',
        'mappings': [{'value': '0', 'newvalue': 'Inativo'},
                     {'value': '1', 'newvalue': 'Ativo'}]})['valuemapids'][0]
    items = api.call('item.get', {'hostids': [tid], 'filter': {'key_': KEY},
        'output': ['itemid']})
    item = {'name': 'Fail2Ban · estado do serviço', 'key_': KEY, 'type': 0,
        'value_type': 3, 'delay': '30s', 'history': '7d', 'trends': '90d',
        'status': 0, 'valuemapid': mapid,
        'description': '1: serviço ativo; 0: serviço inativo. Lê o UserParameter '
            'configurado no agente. Ausência de coleta não equivale a serviço parado.',
        'tags': [{'tag': 'component', 'value': 'security'},
                 {'tag': 'service', 'value': 'fail2ban'}]}
    if items:
        api.call('item.update', dict(item, itemid=items[0]['itemid']))
    else:
        api.call('item.create', dict(item, hostid=tid))
    path = '/' + TEMPLATE + '/' + KEY
    rule = {'description': TRIGGER,
        'expression': f'max({path},2m)=0 and count({path},2m)>=4 '
                      f'and last({path},#1:now-2m)=0',
        'priority': 4, 'status': 0, 'recovery_mode': 1,
        'recovery_expression': f'last({path})=1',
        'comments': 'Confirma 2 minutos de inatividade com coleta a cada 30 segundos. '
            'Exige pelo menos quatro amostras na janela e uma leitura zero no início '
            'do período para evitar alerta prematuro no cadastro ou após lacuna de dados. '
            'Recupera na primeira leitura ativa. Tempo de coleta e envio podem acrescentar atraso.',
        'opdata': 'Estado: {ITEM.LASTVALUE1}',
        'tags': [{'tag': 'component', 'value': 'security'},
                 {'tag': 'service', 'value': 'fail2ban'},
                 {'tag': 'scope', 'value': 'availability'}]}
    triggers = api.call('trigger.get', {'hostids': [tid],
        'filter': {'description': TRIGGER}, 'output': ['triggerid']})
    if triggers:
        api.call('trigger.update', dict(rule, triggerid=triggers[0]['triggerid']))
    else:
        api.call('trigger.create', rule)
    for host in hosts:
        parents = {t['templateid'] for t in host['parentTemplates']}
        if tid not in parents:
            api.call('host.update', {'hostid': host['hostid'],
                'templates': [{'templateid': ident} for ident in sorted(parents | {tid})]})
    after = api.call('item.get', {'hostids': hostids,
        'output': ['itemid', 'hostid', 'key_']})
    bykey = {(i['hostid'], i['key_']): i['itemid'] for i in after}
    if any(bykey.get((i['hostid'], i['key_'])) != i['itemid'] for i in old_items):
        raise RuntimeError('Um item anterior não foi preservado.')
    linked = api.call('host.get', {'hostids': hostids, 'output': ['hostid'],
        'selectParentTemplates': ['templateid']})
    for host in hosts:
        expected = {t['templateid'] for t in host['parentTemplates']} | {tid}
        actual = next(h for h in linked if h['hostid'] == host['hostid'])
        if {t['templateid'] for t in actual['parentTemplates']} != expected:
            raise RuntimeError('Os templates anteriores não foram preservados.')
    new_items = [i for i in after if i['key_'] == KEY]
    api.call('task.create', [{'type': 6, 'request': {'itemid': i['itemid']}}
                            for i in new_items])
    exported = api.call('configuration.export', {'format': 'yaml',
        'options': {'templates': [tid]}})
    (BASE / 'templates/gest-fail2ban-linux.yaml').write_text(exported + '\n')
    return {'template': TEMPLATE, 'templateid': tid,
        'hosts': [{'hostid': h['hostid'], 'name': h['name']} for h in hosts],
        'items': new_items, 'previous_items_preserved': len(old_items),
        'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.add_argument('--hostid', action='append', help='Pode repetir; padrão: as duas VMs AtivBenefícios.')
    args = parser.parse_args()
    sys.path.insert(0, str(BASE.parent / 'extension'))
    from client import API, load_config, secret_access
    cfg = load_config()
    api = API(cfg)
    api.auth = (api.call('user.login', {'username': cfg['username'],
        'password': secret_access(cfg)}) if cfg['auth_mode'] == 'password' else secret_access(cfg))
    try:
        print(json.dumps(configure(api, args.hostid or DEFAULT_HOSTIDS), ensure_ascii=False, indent=2))
    finally:
        if cfg['auth_mode'] == 'password':
            api.call('user.logout', [])


if __name__ == '__main__':
    main()
