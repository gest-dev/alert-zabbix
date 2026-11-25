#!/usr/bin/env python3
"""Inclui uiluolt no grupo GEST e nos comparativos do dashboard operacional."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import time

BASE = Path(__file__).resolve().parent
DASHBOARD = 'GEST · Operação e servidores'
HOST = 'uiluolt'


def configure(api):
    hosts = api.call('host.get', {'filter': {'host': HOST},
        'output': ['hostid', 'host', 'name'], 'selectHostGroups': ['groupid', 'name']})
    groups = api.call('hostgroup.get', {'filter': {'name': 'GEST'}, 'output': ['groupid']})
    dashboards = api.call('dashboard.get', {'filter': {'name': DASHBOARD},
        'output': 'extend', 'selectPages': 'extend', 'selectUsers': 'extend',
        'selectUserGroups': 'extend'})
    if len(hosts) != 1 or len(groups) != 1 or len(dashboards) != 1:
        raise RuntimeError('Host, grupo GEST ou dashboard ausente/ambíguo.')
    host, before = hosts[0], dashboards[0]
    hid, gid = host['hostid'], groups[0]['groupid']
    pages = [{k: deepcopy(p[k]) for k in
              ['dashboard_pageid', 'name', 'display_period', 'widgets']}
             for p in before['pages']]
    updates = {}
    targets = {
        ('Visão geral', 'Servidores · ocupação de disco, espaço livre e CPU'),
        ('Servidores', 'Servidores · comparação de capacidade por host'),
        ('Servidores', 'Servidores · problemas atuais'),
        ('Servidores', 'CPU · comparação entre servidores'),
        ('Servidores', 'Disco / · ocupação por servidor')}
    # As VMs foram renomeadas depois da criação dos gráficos; a seleção SVG
    # usa nomes, enquanto tabelas e problemas usam IDs estáveis.
    current_hosts = {h['hostid']: h for h in api.call('host.get', {
        'hostids': ['10635', '10641'], 'output': ['hostid', 'host', 'name']})}
    aliases = {'Http AtivBeneficios 200': current_hosts['10635']['name'],
               'Banco AtivBeneficios Prod': current_hosts['10641']['name']}

    def field(name, value, type_=0):
        return {'name': name, 'value': str(value), 'type': str(type_)}

    def set_field(widget, name, value, type_=0):
        old = next((f for f in widget['fields'] if f['name'] == name), None)
        if old is None:
            widget['fields'].append(field(name, value, type_))
        else:
            old['value'] = str(value)

    for page in pages:
        for widget in page['widgets']:
            target = (page['name'], widget['name'])
            if target not in targets:
                continue
            if widget['type'] in ('tophosts', 'problems'):
                if not any(f['name'] == 'hostids' and f['value'] == hid
                           for f in widget['fields']):
                    widget['fields'].append(field('hostids', hid, 3))
            elif widget['type'] == 'svggraph':
                for f in widget['fields']:
                    if f['name'].startswith('ds.hosts.') and f['value'] in aliases:
                        f['value'] = aliases[f['value']]
                series = [int(re.match(r'ds\.hosts\.(\d+)\.', f['name'])[1])
                          for f in widget['fields'] if f['name'].startswith('ds.hosts.')]
                if not any(f['name'].startswith('ds.hosts.') and f['value'] == host['name']
                           for f in widget['fields']):
                    index = max(series, default=-1) + 1
                    item_name = ('Linux: CPU utilization' if widget['name'].startswith('CPU')
                                 else '/: Space utilization')
                    for name, value, type_ in [
                        (f'ds.hosts.{index}.0', host['name'], 1),
                        (f'ds.items.{index}.0', item_name, 1),
                        (f'ds.color.{index}', '22D3EE', 1),
                        (f'ds.width.{index}', 3, 0), (f'ds.fill.{index}', 0, 0),
                        (f'ds.transparency.{index}', 1, 0)]:
                        widget['fields'].append(field(name, value, type_))
                set_field(widget, 'legend', 1)
                set_field(widget, 'legend_lines', 3)
                set_field(widget, 'legend_columns', 2)
            else:
                raise RuntimeError('Tipo inesperado no comparativo: ' + widget['name'])
            updates[widget['widgetid']] = widget
            targets.remove(target)
    if targets:
        raise RuntimeError('Comparativos esperados não encontrados: ' + repr(targets))
    comparison_ids = list(updates)
    # Cinco linhas precisam de quatro unidades para aparecer sem rolagem.
    # Desloque os widgets abaixo, mantendo IDs, conteúdo e filtros existentes.
    for page in pages:
        if page['name'] not in ('Visão geral', 'Servidores'):
            continue
        table = next(w for w in page['widgets']
                     if w['type'] == 'tophosts' and w['widgetid'] in updates)
        delta = max(0, 4 - int(table['height']))
        if not delta:
            continue
        old_bottom = int(table['y']) + int(table['height'])
        table['height'] = str(int(table['height']) + delta)
        for widget in page['widgets']:
            if widget is not table and int(widget['y']) >= old_bottom:
                widget['y'] = str(int(widget['y']) + delta)
                updates[widget['widgetid']] = widget

    directory = Path.home() / '.local/share/alert-zabbix/backups'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = directory / f'gest-before-uiluolt-comparisons-{time.time_ns()}.json'
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump({'dashboard': before, 'host': host}, stream, ensure_ascii=False, indent=2)
    groupids = {g['groupid'] for g in host['hostgroups']}
    if gid not in groupids:
        api.call('host.update', {'hostid': hid,
            'groups': [{'groupid': ident} for ident in sorted(groupids | {gid})]})
    api.call('dashboard.update', {'dashboardid': before['dashboardid'], 'pages': pages})
    after = api.call('dashboard.get', {'dashboardids': [before['dashboardid']],
        'output': 'extend', 'selectPages': 'extend', 'selectUsers': 'extend',
        'selectUserGroups': 'extend'})[0]
    if {k: v for k, v in before.items() if k != 'pages'} != {
            k: v for k, v in after.items() if k != 'pages'}:
        raise RuntimeError('Propriedades do dashboard alteradas.')
    if len(before['pages']) != len(after['pages']):
        raise RuntimeError('Quantidade de páginas alterada.')
    for old_page, new_page in zip(before['pages'], after['pages']):
        if any(old_page[k] != new_page[k] for k in ['dashboard_pageid', 'name', 'display_period']):
            raise RuntimeError('Ordem ou propriedades das páginas alteradas.')
        old_widgets = {w['widgetid']: w for w in old_page['widgets']}
        new_widgets = {w['widgetid']: w for w in new_page['widgets']}
        if old_widgets.keys() != new_widgets.keys():
            raise RuntimeError('IDs de widgets alterados.')
        for ident, old in old_widgets.items():
            if new_widgets[ident] != updates.get(ident, old):
                raise RuntimeError('Widget não corresponde ao esperado: ' + old['name'])
    current = api.call('host.get', {'hostids': [hid], 'output': ['hostid'],
        'selectHostGroups': ['groupid', 'name']})[0]
    if {g['groupid'] for g in current['hostgroups']} != groupids | {gid}:
        raise RuntimeError('Grupos anteriores não foram preservados.')
    (BASE / 'dashboards/gest-servidores-comparativos.json').write_text(json.dumps({
        'dashboardid': after['dashboardid'], 'widgets': [w for p in after['pages']
            for w in p['widgets'] if w['widgetid'] in comparison_ids]},
        ensure_ascii=False, indent=2) + '\n')
    return {'host': host['name'], 'groups': current['hostgroups'],
        'comparison_widgets': comparison_ids, 'updated_widgets': list(updates),
        'other_widget_content_preserved': True,
        'backup': str(backup)}


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
