#!/usr/bin/env python3
"""Migra os títulos grandes para a faixa fina do módulo GEST do frontend."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parent
DASHBOARD = 'GEST · Operação e servidores'
TITLE_PREFIX = 'Identificação · '
MODULE_ID = 'gest_dashboard_title'


def is_title(widget):
    return widget['type'] == 'item' and widget['name'].startswith(TITLE_PREFIX)


def without_legacy_title(page):
    """Remove o cartão antigo e recupera o espaço ocupado na grade."""
    result = deepcopy(page)
    previous = [w for w in result['widgets'] if is_title(w)]
    if len(previous) > 1:
        raise RuntimeError('Identificação duplicada em ' + page['name'])
    result['widgets'] = [w for w in result['widgets'] if not is_title(w)]
    if previous:
        height = int(previous[0]['height'])
        for widget in result['widgets']:
            if int(widget['y']) < height:
                raise RuntimeError('Conteúdo sobreposto à identificação antiga.')
            widget['y'] = str(int(widget['y']) - height)
    return result


def canonical(widget):
    result = deepcopy(widget)
    result['fields'] = sorted(result['fields'],
                              key=lambda f: (f['name'], f['type'], f['value']))
    return result


def configure(api, dashboard_name=DASHBOARD):
    found = api.call('dashboard.get', {
        'filter': {'name': dashboard_name}, 'output': 'extend',
        'selectPages': 'extend', 'selectUsers': 'extend',
        'selectUserGroups': 'extend'})
    if len(found) != 1:
        raise RuntimeError('Dashboard não encontrado ou nome ambíguo.')
    before = found[0]
    modules = api.call('module.get', {'filter': {'id': MODULE_ID}, 'output': 'extend'})
    if len(modules) != 1 or modules[0]['status'] != '1':
        raise RuntimeError('Instale e ative primeiro o módulo modules/gest-dashboard-title.')
    pages = [without_legacy_title({k: p[k] for k in
             ['dashboard_pageid', 'name', 'display_period', 'widgets']})
             for p in before['pages']]

    backup_dir = Path.home() / '.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / f'gest-before-page-titles-{time.time_ns()}.json'
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(before, stream, ensure_ascii=False, indent=2)
    api.call('dashboard.update', {'dashboardid': before['dashboardid'], 'pages': pages})
    after = api.call('dashboard.get', {
        'dashboardids': [before['dashboardid']], 'output': 'extend',
        'selectPages': 'extend', 'selectUsers': 'extend',
        'selectUserGroups': 'extend'})[0]
    if {k: v for k, v in before.items() if k != 'pages'} != {
            k: v for k, v in after.items() if k != 'pages'}:
        raise RuntimeError('As configurações do dashboard foram alteradas.')
    if [p['dashboard_pageid'] for p in before['pages']] != [
            p['dashboard_pageid'] for p in after['pages']]:
        raise RuntimeError('A ordem das páginas foi alterada.')
    for old, expected, actual in zip(before['pages'], pages, after['pages']):
        if any(old[k] != actual[k] for k in ['name', 'display_period']):
            raise RuntimeError('Nome ou período de página alterado.')
        if len(actual['widgets']) != len(expected['widgets']):
            raise RuntimeError('Quantidade de widgets inesperada.')
        stored = {w['widgetid']: canonical(w) for w in actual['widgets']}
        for w in expected['widgets']:
            if 'widgetid' in w and stored.get(w['widgetid']) != canonical(w):
                raise RuntimeError('Widget existente não foi preservado: ' + w['name'])
        if any(is_title(w) for w in actual['widgets']):
            raise RuntimeError('O cartão antigo ainda ocupa espaço na grade.')
    export = BASE / 'dashboards'
    export.mkdir(exist_ok=True)
    (export / 'gest-identificacoes.json').write_text(json.dumps({
        'dashboardid': after['dashboardid'], 'module': MODULE_ID,
        'height_px': 32, 'pages': [
            {'dashboard_pageid': p['dashboard_pageid'], 'name': p['name']}
            for p in after['pages']]}, ensure_ascii=False, indent=2) + '\n')

    return {'dashboardid': after['dashboardid'], 'pages': len(after['pages']),
            'height_px': 32, 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    sys.path.insert(0, str(BASE.parent / 'extension'))
    from client import API, load_config, secret_access
    cfg = load_config()
    api = API(cfg)
    api.auth = (api.call('user.login', {'username': cfg['username'],
                                      'password': secret_access(cfg)})
                if cfg['auth_mode'] == 'password' else secret_access(cfg))
    try:
        print(json.dumps(configure(api), ensure_ascii=False, indent=2))
    finally:
        if cfg['auth_mode'] == 'password':
            api.call('user.logout', [])


if __name__ == '__main__':
    main()
