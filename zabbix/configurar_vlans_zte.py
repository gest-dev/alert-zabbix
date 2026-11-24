#!/usr/bin/env python3
"""Acrescenta a aba VLANs ao dashboard detalhado da OLT, usando SNMP somente leitura."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

from configurar_dashboard_zte import BASE, HOST, DASHBOARD, TEMPLATE, f, widget, card

PAGE = 'VLANs'
PREFIX = 'zte.dashboard.vlan.'
ROOTS = ['1.3.6.1.2.1.17.7.1.4.3.1.1', '1.3.6.1.2.1.17.7.1.4.3.1.5',
         '1.3.6.1.2.1.17.7.1.4.5.1.1', '1.3.6.1.2.1.17.1.4.1.2',
         '1.3.6.1.2.1.31.1.1.1.1', '1.3.6.1.2.1.2.2.1.8']


def configure(api):
    hosts = api.call('host.get', {'filter': {'host': HOST},
        'output': ['hostid'], 'selectParentTemplates': ['templateid', 'host']})
    if len(hosts) != 1:
        raise RuntimeError('Host OLT não encontrado ou ambíguo.')
    host = hosts[0]
    tid = next(t['templateid'] for t in host['parentTemplates'] if t['host'] == TEMPLATE)
    dashboards = api.call('dashboard.get', {'filter': {'name': DASHBOARD},
        'output': 'extend', 'selectPages': 'extend',
        'selectUsers': 'extend', 'selectUserGroups': 'extend'})
    if len(dashboards) != 1:
        raise RuntimeError('Dashboard detalhado da OLT não encontrado ou ambíguo.')
    before = dashboards[0]
    old_pages = [p for p in before['pages'] if p['name'] == PAGE]
    if len(old_pages) > 1:
        raise RuntimeError('Há páginas VLANs duplicadas.')
    backup_dir = Path.home() / '.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / f'zte-before-vlans-{time.time_ns()}.json'
    snapshot = {'dashboard': before, 'template': api.call('configuration.export',
        {'format': 'yaml', 'options': {'templates': [tid]}})}
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as out:
        json.dump(snapshot, out, ensure_ascii=False, indent=2)
    existing = {i['key_']: i['itemid'] for i in api.call('item.get',
        {'hostids': [tid], 'output': ['itemid', 'key_']})}

    def item(key, name, type_, value_type, **extra):
        data = {'hostid': tid, 'key_': PREFIX + key, 'name': name,
                'type': type_, 'value_type': value_type, 'delay': '0',
                'history': '7d' if value_type == 3 else '1h',
                'trends': '90d' if value_type == 3 else '0',
                'tags': [{'tag': 'component', 'value': 'vlan'},
                         {'tag': 'vendor', 'value': 'ZTE'}]}
        data.update(extra)
        if data['key_'] in existing:
            ident = existing[data['key_']]
            data.pop('hostid')
            api.call('item.update', dict(data, itemid=ident))
            return ident
        return api.call('item.create', data)['itemids'][0]

    master = item('walk', 'VLANs: inventário e PVID das portas', 20, 4,
                  delay='1m', history='0', snmp_oid='walk[' + ','.join(ROOTS) + ']')
    source = (BASE / 'widgets/zte-vlan-summary.js').read_text()
    modes = [('total', 'VLANs: total cadastrado', 3),
             ('active', 'VLANs: configurações ativas', 3),
             ('ports', 'VLANs: uplinks Ethernet com PVID', 3),
             ('vlans_html', 'VLANs: inventário visual', 4),
             ('ports_html', 'VLANs: PVID visual dos uplinks', 4)]
    for mode, label, value_type in modes:
        item(mode, label, 18, value_type, master_itemid=master,
             preprocessing=[{'type': 21, 'params': source.replace('__MODE__', mode),
                             'error_handler': 0, 'error_handler_params': ''}])
    items = {i['key_']: i for i in api.call('item.get', {'hostids': [host['hostid']],
             'output': ['itemid', 'key_', 'name']})}
    widgets = []
    for x, mode, label, desc, color in [
            (0, 'total', 'VLANs · cadastradas', 'Inventário de VLANs', 'blue'),
            (6, 'active', 'VLANs · configuração ativa', 'Não representa tráfego', 'green'),
            (12, 'ports', 'Uplinks · PVID informado', 'Portas Ethernet identificadas', 'purple')]:
        widgets.append(card(items[PREFIX + mode], label, x, 0, height=2,
                            desc=desc, color=color, value_size=56))
    widgets.append(card(items['zabbix[host,snmp,available]'], 'Conexão · SNMP',
                        18, 0, height=2, color='red', desc='UrTelecom · OLT ZTE Titan',
                        value_size=40, thresholds=[(1, 'green'), (2, 'amber')]))
    for w in widgets:
        for field in w['fields']:
            if field['name'] == 'desc_size':
                field['value'] = '14'
            elif field['name'] == 'time_size':
                field['value'] = '12'
    for x, mode, label in [(0, 'vlans_html', 'VLANs · IDs, nomes e configuração'),
                           (12, 'ports_html', 'Uplinks · PVID e estado do link')]:
        widgets.append(widget('plaintext', label, x, 2, 12, 8,
            [f('itemids', items[PREFIX + mode]['itemid'], 4), f('show_lines', 1),
             f('style', 1), f('show_as_html', 1), f('rf_rate', 30)]))
    page = {'name': PAGE, 'display_period': 0, 'widgets': widgets}
    if old_pages:
        old = old_pages[0]
        page['dashboard_pageid'] = old['dashboard_pageid']
        ids = {(w['type'], w['name']): w['widgetid'] for w in old['widgets']}
        for w in widgets:
            if (w['type'], w['name']) in ids:
                w['widgetid'] = ids[(w['type'], w['name'])]
    pages = []
    for p in before['pages']:
        if p['name'] == PAGE:
            pages.append(page)
        else:
            pages.append({k: deepcopy(p[k]) for k in
                ['dashboard_pageid', 'name', 'display_period', 'widgets']})
    if not old_pages:
        pages.insert(2, page)
    api.call('dashboard.update', {'dashboardid': before['dashboardid'], 'pages': pages})
    after = api.call('dashboard.get', {'dashboardids': [before['dashboardid']],
        'output': 'extend', 'selectPages': 'extend',
        'selectUsers': 'extend', 'selectUserGroups': 'extend'})[0]
    assert {k: v for k, v in before.items() if k != 'pages'} == {
        k: v for k, v in after.items() if k != 'pages'}, 'Metadados do painel alterados'
    for p in before['pages']:
        if p['name'] != PAGE:
            assert p == next(x for x in after['pages'] if x['dashboard_pageid'] == p['dashboard_pageid']), 'Página existente alterada'
    assert sum(p['name'] == PAGE for p in after['pages']) == 1
    (BASE / 'dashboards/urtelecom-zte-titan.json').write_text(
        json.dumps(after, ensure_ascii=False, indent=2) + '\n')
    (BASE / 'templates/gest-zte-titan-c6xx.yaml').write_text(api.call('configuration.export',
        {'format': 'yaml', 'options': {'templates': [tid]}}))
    api.call('task.create', [{'type': 6, 'request': {
        'itemid': items[PREFIX + 'walk']['itemid']}}])
    return {'dashboardid': after['dashboardid'], 'pages': len(after['pages']),
            'page': PAGE, 'widgets': len(widgets), 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    sys.path.insert(0, str(BASE.parent / 'extension'))
    from client import API, load_config, secret_access
    cfg = load_config()
    api = API(cfg)
    api.auth = (api.call('user.login', {'username': cfg['username'], 'password': secret_access(cfg)})
                if cfg['auth_mode'] == 'password' else secret_access(cfg))
    try:
        print(json.dumps(configure(api), ensure_ascii=False, indent=2))
    finally:
        if cfg['auth_mode'] == 'password':
            api.call('user.logout', [])


if __name__ == '__main__':
    main()
