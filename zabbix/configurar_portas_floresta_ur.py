#!/usr/bin/env python3
"""Floresta/UrTelecom: banda em SFP/QSFP; cobre Ethernet alerta somente perda de link."""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import time

PROFILE = 'GEST - MikroTik Alertas Rapidos'
RULE = 'gest.mikrotik.interface.discovery'
TRAFFIC = 'queda de pelo menos '
LINK = 'sem link por 15 segundos'
MACROS = {'{$GEST.FAST.TRAFFIC.IFTYPE.MATCHES}': '^(6|135|136)$',
          '{$GEST.FAST.LINK.IFTYPE.MATCHES}': '^(6|135|136)$',
          '{$GEST.FAST.TRAFFIC.IFNAME.MATCHES}': '.*'}
TARGET_MACROS = {'{$GEST.FAST.TRAFFIC.IFTYPE.MATCHES}': '^6$',
                 '{$GEST.FAST.TRAFFIC.IFNAME.MATCHES}': '^(sfp|qsfp)',
                 '{$GEST.FAST.LINK.IFTYPE.MATCHES}': '^6$'}
POLICIES = ['GEST: banda por tipo de interface',
            'GEST: queda de link somente Ethernet',
            'GEST: banda por nome de interface']
OWN_POLICIES = set(POLICIES) | {'GEST: sem alertas por variação de tráfego'}


def overrides(existing):
    kept = [{k: deepcopy(o[k]) for k in ['name', 'step', 'stop', 'filter', 'operations']}
            for o in existing if o['name'] not in OWN_POLICIES]
    if any(str(o['stop']) == '1' for o in kept):
        raise RuntimeError('Há uma exceção com interrupção de processamento; revisar a precedência.')
    step = max([int(o['step']) for o in kept] or [0])
    for offset, (name, pattern, macro, value) in enumerate([
            (POLICIES[0], TRAFFIC, '{#IFTYPE}', '{$GEST.FAST.TRAFFIC.IFTYPE.MATCHES}'),
            (POLICIES[1], LINK, '{#IFTYPE}', '{$GEST.FAST.LINK.IFTYPE.MATCHES}'),
            (POLICIES[2], TRAFFIC, '{#IFNAME}', '{$GEST.FAST.TRAFFIC.IFNAME.MATCHES}')], 1):
        kept.append({'name': name, 'step': step + offset, 'stop': 0,
            'filter': {'evaltype': 0, 'conditions': [
                {'macro': macro, 'operator': 9, 'value': value, 'formulaid': 'A'}]},
            'operations': [{'operationobject': 1, 'operator': 2,
                            'value': pattern, 'opstatus': {'status': 1}}]})
    return kept


def desired_status(trigger):
    if not any(t['tag'] == 'profile' and t['value'] == 'GEST-fast' for t in trigger['tags']):
        return None
    if TRAFFIC not in trigger['description'] and LINK not in trigger['description']:
        return None
    iftype = next((t['value'] for t in trigger['tags'] if t['tag'] == 'ifType'), None)
    if iftype not in ('6', '135', '136'):
        raise RuntimeError('Tipo de interface não validado em ' + trigger['description'])
    if TRAFFIC in trigger['description']:
        match = re.search(r': interface (.*?) \(', trigger['description'])
        if match is None:
            raise RuntimeError('Nome de interface não validado em ' + trigger['description'])
        return '0' if iftype == '6' and re.match(r'^(sfp|qsfp)', match.group(1)) else '1'
    return '1' if iftype != '6' else None


def configure(api, backup_dir=None):
    templates = api.call('template.get', {'filter': {'host': PROFILE}, 'output': ['templateid']})
    if len(templates) != 1:
        raise RuntimeError('Perfil MikroTik rápido não encontrado.')
    hosts = api.call('host.get', {'templateids': [templates[0]['templateid']],
        'output': ['hostid', 'name', 'host']})
    targets = [h for h in hosts if h['name'].casefold().replace(' ', '').startswith(
        ('florestatelecom', 'urtelecom'))]
    if not targets:
        raise RuntimeError('Nenhum host Floresta/UrTelecom com o perfil rápido.')
    ids = [h['hostid'] for h in targets]
    all_ids = [h['hostid'] for h in hosts]
    tid = templates[0]['templateid']
    rules = api.call('discoveryrule.get', {'hostids': all_ids + [tid], 'filter': {'key_': RULE},
        'output': ['itemid', 'hostid', 'key_'], 'selectOverrides': 'extend'})
    selected = [r for r in rules if r['hostid'] in ids]
    if len(selected) != len(targets):
        raise RuntimeError('Há host sem a descoberta rápida de interfaces.')
    source_rule = next(r for r in rules if r['hostid'] == tid)
    planned = {'itemid': source_rule['itemid'], 'overrides': overrides(source_rule['overrides'])}
    macro_rows = api.call('usermacro.get', {'hostids': all_ids + [tid],
        'filter': {'macro': list(MACROS)}, 'output': ['hostmacroid', 'hostid', 'macro', 'value']})
    for row in macro_rows:
        if row['hostid'] not in ids and row['value'] != MACROS[row['macro']]:
            raise RuntimeError('Há uma política anterior fora do escopo; revisar antes de alterar.')
    params = {'hostids': all_ids, 'output': ['triggerid', 'description', 'status'],
              'selectTags': 'extend', 'selectHosts': ['hostid']}
    triggers = api.call('trigger.get', params)
    statuses = {t['triggerid']: desired_status(t) for t in triggers
                if any(h['hostid'] in ids for h in t['hosts'])}
    statuses = {tid: status for tid, status in statuses.items() if status is not None}
    items_params = {'hostids': ids, 'search': {'key_': 'gest.mikrotik.if.'},
                    'output': ['itemid', 'hostid', 'key_', 'status', 'delay', 'history', 'trends']}
    items = api.call('item.get', items_params)
    if not items:
        raise RuntimeError('Nenhum item de interface encontrado para preservar.')
    backup_dir = backup_dir or Path.home() / '.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / f'floresta-ur-port-policy-before-{time.time_ns()}.json'
    with open(backup, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as out:
        json.dump({'hosts': hosts, 'target_hosts': targets, 'rules': rules,
                   'triggers': triggers, 'items': items, 'policy_macros': macro_rows}, out, ensure_ascii=False, indent=2)
    for hostid, values in [(tid, MACROS)] + [(hid, TARGET_MACROS) for hid in ids]:
        for macro, value in values.items():
            found = next((r for r in macro_rows if r['hostid'] == hostid and r['macro'] == macro), None)
            if found:
                if found['value'] != value:
                    api.call('usermacro.update', {'hostmacroid': found['hostmacroid'], 'value': value})
            else:
                api.call('usermacro.create', {'hostid': hostid, 'macro': macro, 'value': value, 'type': 0})
    api.call('discoveryrule.update', planned)
    pending = [{'triggerid': t['triggerid'], 'status': statuses[t['triggerid']]}
               for t in triggers if t['triggerid'] in statuses
               and t['status'] != statuses[t['triggerid']]]
    if pending:
        api.call('trigger.update', pending)
    after = api.call('trigger.get', params)
    stored = {t['triggerid']: t for t in after}
    for old in triggers:
        expected = deepcopy(old)
        if old['triggerid'] in statuses:
            expected['status'] = statuses[old['triggerid']]
        if stored[old['triggerid']] != expected:
            raise RuntimeError('Alteração inesperada em ' + old['description'])
    assert api.call('item.get', items_params) == items, 'Coleta de interfaces alterada'
    current_rules = api.call('discoveryrule.get', {'hostids': all_ids + [tid], 'filter': {'key_': RULE},
        'output': ['itemid', 'hostid', 'key_'], 'selectOverrides': 'extend'})
    for old in rules:
        current = next(r for r in current_rules if r['itemid'] == old['itemid'])
        assert all(any(o['name'] == name for o in current['overrides']) for name in POLICIES)
        assert [o for o in current['overrides'] if o['name'] not in OWN_POLICIES] == [
            o for o in old['overrides'] if o['name'] not in OWN_POLICIES], 'Exceção preexistente alterada'
    counts = Counter()
    for t in after:
        if not any(h['hostid'] in ids for h in t['hosts']):
            continue
        if TRAFFIC in t['description'] and t['status'] == '1':
            counts['traffic_disabled'] += 1
        if TRAFFIC in t['description'] and t['status'] == '0':
            assert desired_status(t) == '0', 'Alerta de banda habilitado fora de SFP/QSFP'
            counts['sfp_traffic_enabled'] += 1
        if LINK in t['description'] and t['status'] == '0':
            assert next(tag['value'] for tag in t['tags'] if tag['tag'] == 'ifType') == '6'
            counts['ethernet_link_enabled'] += 1
        if LINK in t['description'] and t['status'] == '1':
            counts['vlan_link_disabled'] += 1
    (Path(__file__).parent / 'templates/gest-mikrotik-alertas-rapidos.yaml').write_text(
        api.call('configuration.export', {'format': 'yaml', 'options': {'templates': [tid]}}))
    api.call('task.create', [{'type': 6, 'request': {'itemid': r['itemid']}} for r in selected])
    return {'hosts': [h['name'] for h in targets], 'changed_now': len(pending),
            **counts, 'interface_items_preserved': len(items), 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
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
