#!/usr/bin/env python3
"""Aplica os alertas de ocupação GEST usando a conexão local do aplicativo."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
from client import API, load_config, secret_access


TEMPLATE = 'GEST-cpu-hd-mysql'
LEGACY = {'{#FSNAME}: Disk space is low', '{#FSNAME}: Disk space is critically low'}
THRESHOLDS = {
    '{$GEST.FS.PUSED.WARN}': ('90', 'Percentual para aviso de ocupação; exige três coletas consecutivas.'),
    '{$GEST.FS.PUSED.CRIT}': ('95', 'Percentual para alerta alto de ocupação; exige três coletas consecutivas.'),
    '{$GEST.FS.PUSED.WARN.RECOVERY}': ('88', 'Recupera o aviso abaixo deste percentual.'),
    '{$GEST.FS.PUSED.CRIT.RECOVERY}': ('93', 'Recupera o alerta alto abaixo deste percentual.')
}


def configure(api, template_name=TEMPLATE):
    templates = api.call('template.get', {
        'filter': {'host': [template_name]}, 'output': ['templateid'],
        'selectMacros': ['macro', 'value', 'description', 'type']
    })
    if len(templates) != 1:
        raise RuntimeError(f'Importe o template {template_name} antes de configurar os alertas.')
    template = templates[0]
    tid = template['templateid']
    rules = api.call('discoveryrule.get', {
        'hostids': [tid], 'filter': {'key_': 'vfs.fs.dependent.discovery'}, 'output': ['itemid']
    })
    if len(rules) != 1:
        raise RuntimeError('A descoberta de sistemas de arquivos Linux não foi encontrada no template.')
    prototypes = api.call('triggerprototype.get', {
        'hostids': [tid], 'output': ['triggerid', 'description', 'expression',
                                  'recovery_mode', 'recovery_expression', 'priority',
                                  'status', 'templateid', 'comments', 'opdata'],
        'selectDependencies': ['triggerid']
    })
    hosts = api.call('host.get', {'templateids': [tid], 'output': ['hostid', 'name']})
    hostids = [host['hostid'] for host in hosts]
    host_prototypes = api.call('triggerprototype.get', {
        'hostids': hostids, 'output': ['triggerid', 'description', 'status']
    }) if hostids else []
    host_triggers = api.call('trigger.get', {
        'hostids': hostids, 'output': ['triggerid', 'description', 'status']
    }) if hostids else []

    backup_dir = Path.home() / '.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / f'gest-disk-alerts-before-{time.time_ns()}.json'
    snapshot = {
        'template': template, 'prototype_settings': prototypes,
        'host_prototypes': host_prototypes, 'host_triggers': host_triggers
    }
    with open(backup, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)

    # Preserve every unrelated macro, including any host-specific override.
    macros = [m for m in template['macros'] if m['macro'] not in THRESHOLDS]
    macros += [{'macro': key, 'value': value, 'description': description}
               for key, (value, description) in THRESHOLDS.items()]
    api.call('template.update', {'templateid': tid, 'macros': macros})
    own = {p['description']: p['triggerid'] for p in prototypes if p['templateid'] == '0'}
    item = f'/{template_name}/vfs.fs.dependent.size[{{#FSNAME}},pused]'
    ids = {}
    for level, priority in [('CRIT', 4), ('WARN', 2)]:
        name = '{#FSNAME}: disco com uso a partir de {$GEST.FS.PUSED.' + level + '}%'
        data = {
            'description': name,
            'expression': 'count(' + item + ',#3,"ge",{$GEST.FS.PUSED.' + level + '})=3',
            'recovery_mode': 1,
            'recovery_expression': 'last(' + item + ')<{$GEST.FS.PUSED.' + level + '.RECOVERY}',
            'priority': priority, 'status': 0, 'opdata': 'Ocupação: {ITEM.LASTVALUE1}',
            'comments': 'Ocupação percentual por três coletas consecutivas. Recuperação com margem para evitar oscilações. Não exige espaço livre absoluto ou previsão adicional.',
            'dependencies': [{'triggerid': ids['CRIT']}] if level == 'WARN' else [],
            'tags': [{'tag': 'component', 'value': 'storage'}, {'tag': 'scope', 'value': 'capacity'}]
        }
        if name in own:
            ids[level] = own[name]
            api.call('triggerprototype.update', dict(data, triggerid=ids[level]))
        else:
            ids[level] = api.call('triggerprototype.create', data)['triggerids'][0]

    # Status changes on inherited prototypes do not reliably change objects
    # that have already been discovered. Disable those explicitly as well.
    legacy_prototypes = [p for p in prototypes + host_prototypes if p['description'] in LEGACY]
    pending = [{'triggerid': p['triggerid'], 'status': 1}
               for p in legacy_prototypes if p['status'] != '1']
    if pending:
        api.call('triggerprototype.update', pending)
    legacy_triggers = [t for t in host_triggers
                       if t['description'].endswith((': Disk space is low', ': Disk space is critically low'))]
    pending = [{'triggerid': t['triggerid'], 'status': 1}
               for t in legacy_triggers if t['status'] != '1']
    if pending:
        api.call('trigger.update', pending)

    masters = api.call('item.get', {
        'hostids': hostids, 'filter': {'key_': 'vfs.fs.get', 'status': '0'},
        'monitored': True, 'output': ['itemid']
    }) if hostids else []
    if masters:
        api.call('task.create', [{'type': 6, 'request': {'itemid': m['itemid']}} for m in masters])
    return {'templateid': tid, 'prototypeids': ids, 'hosts': hosts,
            'legacy_prototypeids': [p['triggerid'] for p in legacy_prototypes],
            'legacy_triggerids': [t['triggerid'] for t in legacy_triggers],
            'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', default=TEMPLATE, help='Nome técnico do template GEST de destino.')
    args = parser.parse_args()
    config = load_config()
    api = API(config)
    if config['auth_mode'] == 'password':
        api.auth = api.call('user.login', {'username': config['username'],
                                           'password': secret_access(config)})
    else:
        api.auth = secret_access(config)
    try:
        result = configure(api, args.template)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if config['auth_mode'] == 'password':
            api.call('user.logout', [])


if __name__ == '__main__':
    main()
