#!/usr/bin/env python3
"""Configura confirmação de falha e recuperação da conexão TCP dos agentes GEST."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
from client import API, load_config, secret_access

TEMPLATES = ['GEST-cpu-hd-mysql', 'GEST-cpu-hd-nginx-php']
KEY = 'net.tcp.service[tcp,,{$GEST.AGENT.PORT}]'
NAME = '{HOST.NAME}: conexão com o agente Zabbix indisponível'
LEGACY = 'Linux: Zabbix agent is not available'
MACROS = {
    '{$GEST.AGENT.PORT}': ('10050', 'Porta TCP do agente, consultada pelo servidor/proxy.'),
    '{$GEST.AGENT.CHECK.INTERVAL}': ('5s', 'Intervalo da checagem TCP. Confirma falha por 1 minuto e recuperação por 30 segundos.')
}
ITEM_DESCRIPTION = ('Servidor/proxy verifica a porta TCP do agente, independentemente da espera '
                    'do poller de agentes indisponíveis. Confirma conectividade TCP, não a '
                    'execução das métricas. Abre alerta após 1 minuto de falhas observadas '
                    'e recupera após 30 segundos de respostas positivas estáveis.')
TRIGGER_DESCRIPTION = ('Confirma falha TCP por 1 minuto e recuperação por 30 segundos, '
                       'com coleta padrão a cada 5 segundos. O valor no início de cada '
                       'janela também é conferido para não confirmar estabilidade com '
                       'uma única amostra após intervalo sem coleta. Timeout, processamento '
                       'e entrega do mensageiro podem acrescentar atraso.')


def connection_expressions(template_name):
    item = f'/{template_name}/{KEY}'
    # A amostra anterior ao início da janela impede confirmação antecipada
    # quando todas as amostras disponíveis cobrem menos que o tempo exigido.
    return (f'max({item},1m)=0 and last({item},#1:now-1m)=0',
            f'min({item},30s)=1 and last({item},#1:now-30s)=1')


def configure(api, template_name):
    found = api.call('template.get', {
        'filter': {'host': [template_name]}, 'output': ['templateid', 'host'],
        'selectMacros': ['hostmacroid', 'macro', 'value', 'description', 'type']
    })
    if len(found) != 1:
        raise RuntimeError(f'Template não encontrado: {template_name}')
    template = found[0]
    tid = template['templateid']
    hosts = api.call('host.get', {'templateids': [tid], 'output': ['hostid', 'host']})
    scope = [tid] + [h['hostid'] for h in hosts]
    triggers = api.call('trigger.get', {
        'hostids': scope,
        'output': ['triggerid', 'description', 'status', 'templateid', 'expression',
                   'recovery_mode', 'recovery_expression', 'priority', 'comments', 'opdata'],
        'expandExpression': True, 'selectTags': 'extend'
    })
    items = api.call('item.get', {
        'hostids': [tid], 'filter': {'key_': KEY}, 'output': 'extend'
    })
    directory = Path.home() / '.local/share/alert-zabbix/backups'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = directory / f'gest-agent-fast-before-{time.time_ns()}.json'
    with open(backup, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump({'template': template, 'hosts': hosts, 'triggers': triggers,
                   'items': items}, stream, ensure_ascii=False, indent=2)

    # Atualize somente as macros desta verificação, preservando inclusive
    # macros secretas que a API não devolve em texto claro.
    for name, (value, description) in MACROS.items():
        existing = next((m for m in template['macros'] if m['macro'] == name), None)
        if existing:
            api.call('usermacro.update', {'hostmacroid': existing['hostmacroid'],
                                         'value': value, 'description': description})
        else:
            api.call('usermacro.create', {'hostid': tid, 'macro': name,
                                         'value': value, 'description': description})
    maps = api.call('valuemap.get', {
        'hostids': [tid], 'filter': {'name': 'GEST - Conexão agente TCP'}, 'output': ['valuemapid']
    })
    mapid = maps[0]['valuemapid'] if maps else api.call('valuemap.create', {
        'hostid': tid, 'name': 'GEST - Conexão agente TCP',
        'mappings': [{'value': '0', 'newvalue': 'Indisponível'},
                     {'value': '1', 'newvalue': 'Disponível'}]
    })['valuemapids'][0]
    data = {
        'name': 'Zabbix agent: conexão TCP rápida', 'key_': KEY, 'type': 3,
        'value_type': 3, 'delay': '{$GEST.AGENT.CHECK.INTERVAL}',
        'history': '7d', 'trends': '90d', 'valuemapid': mapid, 'status': 0,
        'description': ITEM_DESCRIPTION,
        'tags': [{'tag': 'component', 'value': 'zabbix-agent'},
                 {'tag': 'scope', 'value': 'availability'}]
    }
    if items:
        itemid = items[0]['itemid']
        api.call('item.update', dict(data, itemid=itemid))
    else:
        itemid = api.call('item.create', dict(data, hostid=tid))['itemids'][0]
    own = next((t for t in triggers if t['description'] == NAME and t['templateid'] == '0'), None)
    problem_expression, recovery_expression = connection_expressions(template_name)
    data = {
        'description': NAME,
        'expression': problem_expression,
        'recovery_mode': 1,
        'recovery_expression': recovery_expression,
        'priority': 3, 'status': 0,
        'comments': TRIGGER_DESCRIPTION,
        'opdata': 'Conexão TCP: {ITEM.LASTVALUE1}',
        'tags': [{'tag': 'component', 'value': 'zabbix-agent'},
                 {'tag': 'scope', 'value': 'availability'}]
    }
    if own:
        triggerid = own['triggerid']
        api.call('trigger.update', dict(data, triggerid=triggerid))
    else:
        triggerid = api.call('trigger.create', data)['triggerids'][0]
    # O status herdado não é exportado no YAML 6.4: reaplicar após importação.
    legacy = [t for t in triggers if t['description'] == LEGACY]
    pending = [{'triggerid': t['triggerid'], 'status': 1}
               for t in legacy if t['status'] != '1']
    if pending:
        api.call('trigger.update', pending)
    return {'template': template_name, 'itemid': itemid, 'triggerid': triggerid,
            'hosts': hosts, 'disabled_legacy_ids': [t['triggerid'] for t in legacy],
            'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', action='append', help='Template de destino; padrão: banco e web GEST.')
    args = parser.parse_args()
    config = load_config()
    api = API(config)
    api.auth = api.call('user.login', {'username': config['username'], 'password': secret_access(config)})
    try:
        for name in args.template or TEMPLATES:
            print(json.dumps(configure(api, name), ensure_ascii=False, indent=2))
    finally:
        api.call('user.logout', [])


if __name__ == '__main__':
    main()
