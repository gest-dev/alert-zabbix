#!/usr/bin/env python3
"""Adiciona a VM uiluolt ao dashboard operacional, preservando as outras páginas."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

from configurar_dashboard_zte import card, f, graph, widget

BASE = Path(__file__).resolve().parent
DASHBOARD = 'GEST · Operação e servidores'
HOST = 'uiluolt'


def configure(api):
    dashboards = api.call('dashboard.get', {
        'filter': {'name': DASHBOARD}, 'output': 'extend', 'selectPages': 'extend',
        'selectUsers': 'extend', 'selectUserGroups': 'extend'})
    hosts = api.call('host.get', {
        'filter': {'host': HOST}, 'output': ['hostid', 'host', 'name'],
        'selectInterfaces': ['interfaceid', 'type', 'main']})
    if len(dashboards) != 1 or len(hosts) != 1:
        raise RuntimeError('Dashboard ou host ausente/ambíguo.')
    before, host = dashboards[0], hosts[0]
    existing = [p for p in before['pages'] if p['name'] == HOST]
    if len(existing) > 1:
        raise RuntimeError('Há páginas uiluolt duplicadas.')
    interface = next(i for i in host['interfaces']
                     if i['type'] == '1' and i['main'] == '1')
    raw = api.call('item.get', {
        'hostids': [host['hostid']], 'output': ['itemid', 'key_', 'name', 'status']})
    items = {i['key_']: i for i in raw}
    required = ['system.cpu.util', 'vm.memory.utilization', 'system.uptime',
                'vfs.fs.dependent.size[/,pused]', 'vfs.fs.dependent.size[/,total]',
                'vfs.fs.dependent.size[/,used]', 'net.if.in["ens18"]',
                'net.if.out["ens18"]']
    if any(key not in items or items[key]['status'] != '0' for key in required):
        raise RuntimeError('As métricas esperadas da VM não estão disponíveis.')

    backup_dir = Path.home() / '.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / f'gest-before-uiluolt-{time.time_ns()}.json'
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump({'dashboard': before, 'host': host, 'items': raw}, stream,
                  ensure_ascii=False, indent=2)

    # Complementos exclusivos deste host; os templates compartilhados não mudam.
    def ensure_item(key, name, **extra):
        if key in items:
            return items[key]
        data = {'hostid': host['hostid'], 'name': name, 'key_': key,
                'type': 0, 'value_type': 3, 'delay': '1m',
                'history': '7d', 'trends': '90d',
                'tags': [{'tag': 'component', 'value': 'dashboard'}]}
        data.update(extra)
        ident = api.call('item.create', data)['itemids'][0]
        result = {'itemid': ident, 'key_': key, 'name': name}
        items[key] = result
        return result

    free = ensure_item('vfs.fs.size[/,free]', 'Disco /: espaço livre',
                       interfaceid=interface['interfaceid'], units='B')
    availability = ensure_item('zabbix[host,agent,available]',
        'Zabbix agent: disponibilidade', type=5, delay='30s')
    cpu, memory = items['system.cpu.util'], items['vm.memory.utilization']
    disk = items['vfs.fs.dependent.size[/,pused]']
    inbound, outbound = items['net.if.in["ens18"]'], items['net.if.out["ens18"]']
    widgets = []
    for item, title, x, tone, thresholds in [
        (cpu, 'CPU · utilização', 0, 'blue', [(70, 'amber'), (90, 'red')]),
        (memory, 'Memória · utilização', 6, 'purple', [(80, 'amber'), (90, 'red')]),
        (disk, 'Disco / · ocupação', 12, 'blue', [(90, 'amber'), (95, 'red')]),
        (free, 'Disco / · espaço livre', 18, 'red', [('5G', 'amber'), ('10G', 'green')])]:
        widgets.append(card(item, title, x, 0, height=2, color=tone,
            desc=HOST, decimals=1, value_size=42, thresholds=thresholds))
    widgets.append(card(availability, 'Agente · disponibilidade', 0, 2, height=2,
        color='red', desc=HOST, value_size=28,
        thresholds=[(1, 'green'), (2, 'amber')]))
    widgets.append(card(items['system.uptime'], 'VM · tempo ligada', 6, 2,
        height=2, color='slate', desc=HOST, value_size=28))
    widgets.append(graph('Rede ens18 · entrada e saída',
        [(inbound, '34D399'), (outbound, '60A5FA')], HOST, 12, 2, height=3))
    # O gráfico de rede ocupa três linhas; CPU/memória começam abaixo.
    widgets.append(graph('CPU · histórico de utilização', [(cpu, '60A5FA')],
        HOST, 0, 4, width=6, height=4, percent=True))
    widgets.append(graph('Memória · histórico de utilização', [(memory, 'A78BFA')],
        HOST, 6, 4, width=6, height=4, percent=True))
    widgets.append(graph('Disco / · histórico de ocupação', [(disk, 'FBBF24')],
        HOST, 12, 5, width=12, height=3, percent=True))

    fields = [f('rf_rate', 30), f('column', 1), f('count', 1),
              f('hostids', host['hostid'], 3), f('columns.name.0', 'Servidor', 1),
              f('columns.data.0', 2), f('columns.base_color.0', '', 1),
              f('columns.aggregate_function.0', 0), f('columns.decimal_places.0', 2)]
    for index, (label, item) in enumerate([
        ('Capacidade', items['vfs.fs.dependent.size[/,total]']),
        ('Usado', items['vfs.fs.dependent.size[/,used]']), ('Livre', free)], 1):
        fields.extend([f(f'columns.name.{index}', label, 1),
            f(f'columns.data.{index}', 1), f(f'columns.item.{index}', item['name'], 1),
            f(f'columns.timeshift.{index}', '', 1),
            f(f'columns.aggregate_function.{index}', 0), f(f'columns.history.{index}', 1),
            f(f'columns.display.{index}', 1), f(f'columns.decimal_places.{index}', 1),
            f(f'columns.base_color.{index}', '', 1)])
    widgets.append(widget('tophosts', 'Disco / · capacidade e uso', 0, 8, 12, 3, fields))
    widgets.append(widget('problems', 'uiluolt · problemas atuais', 12, 8, 12, 3,
        [f('rf_rate', 30), f('show', 3), f('show_tags', 1), f('sort_triggers', 1),
         f('show_lines', 5), f('hostids', host['hostid'], 3)]))
    for index, current in enumerate(widgets):
        for other in widgets[:index]:
            if (current['x'] < other['x'] + other['width'] and
                other['x'] < current['x'] + current['width'] and
                current['y'] < other['y'] + other['height'] and
                other['y'] < current['y'] + current['height']):
                raise RuntimeError('Widgets sobrepostos.')
    page = {'name': HOST, 'display_period': 0, 'widgets': widgets}
    if existing:
        page['dashboard_pageid'] = existing[0]['dashboard_pageid']
        identities = {(w['type'], w['name']): w['widgetid'] for w in existing[0]['widgets']}
        for w in widgets:
            if (w['type'], w['name']) in identities:
                w['widgetid'] = identities[(w['type'], w['name'])]
    pages = []
    for old in before['pages']:
        if not existing and old['name'] == 'Aplicações':
            pages.append(page)
        pages.append(page if old['name'] == HOST else {
            k: deepcopy(old[k]) for k in ['dashboard_pageid', 'name', 'display_period', 'widgets']})
    if not any(p['name'] == HOST for p in pages):
        pages.append(page)
    api.call('dashboard.update', {'dashboardid': before['dashboardid'], 'pages': pages})
    after = api.call('dashboard.get', {'dashboardids': [before['dashboardid']],
        'output': 'extend', 'selectPages': 'extend', 'selectUsers': 'extend',
        'selectUserGroups': 'extend'})[0]
    if {k: v for k, v in before.items() if k != 'pages'} != {
            k: v for k, v in after.items() if k != 'pages'}:
        raise RuntimeError('Propriedades do dashboard alteradas.')
    for old in before['pages']:
        if old['name'] != HOST:
            if next(p for p in after['pages']
                    if p['dashboard_pageid'] == old['dashboard_pageid']) != old:
                raise RuntimeError('Página anterior alterada: ' + old['name'])
    stored = next(p for p in after['pages'] if p['name'] == HOST)
    (BASE / 'dashboards/gest-uiluolt.json').write_text(json.dumps({
        'dashboardid': after['dashboardid'], 'page': stored},
        ensure_ascii=False, indent=2) + '\n')
    titles_path = BASE / 'dashboards/gest-identificacoes.json'
    if titles_path.exists():
        titles = json.loads(titles_path.read_text())
        titles['pages'] = [{'dashboard_pageid': p['dashboard_pageid'], 'name': p['name']}
                           for p in after['pages']]
        titles_path.write_text(json.dumps(titles, ensure_ascii=False, indent=2) + '\n')
    return {'dashboardid': after['dashboardid'], 'pageid': stored['dashboard_pageid'],
            'widgets': len(stored['widgets']), 'pages': len(after['pages']),
            'other_pages_preserved': True, 'backup': str(backup)}


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
