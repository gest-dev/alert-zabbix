#!/usr/bin/env python3
"""Adapta o material ZTE C600/C620 fornecido, preservando os originais e sem segredos."""
import argparse
import hashlib
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

NAME = 'GEST - ZTE TITAN C6xx SNMP'
BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / 'zte titan 6xx' / 'Template ZTE Gpon C620 Full - Bee Solutions-v2.xml'


def put(node, tag, text):
    child = node.find(tag)
    if child is None:
        child = ET.SubElement(node, tag)
    child.text = str(text)
    return child


def uid(text):
    return uuid.UUID(bytes=hashlib.sha256(('gest-zte-titan/' + text).encode()).digest()[:16], version=4).hex


def preprocess(node, kind, value):
    p = node.find('preprocessing')
    if p is None:
        p = ET.SubElement(node, 'preprocessing')
    step = ET.SubElement(p, 'step')
    put(step, 'type', kind)
    put(ET.SubElement(step, 'parameters'), 'parameter', value)


def build():
    root = ET.parse(SOURCE).getroot()
    for element in root.iter('uuid'):
        element.text = uid(element.text)
    # Um grupo próprio evita colisão com UUIDs de grupos existentes.
    for group in root.findall('./groups/group') + root.findall('./templates/template/groups/group'):
        put(group, 'name', 'GEST/ZTE')
    template = root.find('./templates/template')
    put(template, 'template', NAME)
    put(template, 'name', NAME)
    put(template, 'description',
        'Adaptado do Template ZTE C600 Gpon Full - Bee Solutions fornecido pelo usuário. '
        'Validado em ZXA10 C620 V1.2.2 com Zabbix 6.4.21. SNMP v2c pela interface do host, '
        'inclusive portas alternativas. Definir {$SNMP_COMMUNITY} como macro secreta no host. '
        'Sem script externo nem comunidade de escrita. ONUs OffLine (estado 7) mantém a '
        'semântica do original; ONUs não online inclui todos os estados diferentes de online. '
        'O JSON de dashboard fornecido é para Grafana e não é importado aqui.')
    items = template.find('items')
    for item in items:
        put(item, 'delay', '30s')
        put(item, 'history', '7d')
    master = ET.SubElement(items, 'item')
    for k, v in {
        'uuid': uid('onu-state-walk'), 'name': 'GPON: estados das ONUs (coleta única)',
        'type': 'SNMP_AGENT', 'snmp_oid': 'walk[1.3.6.1.4.1.3902.1082.500.10.2.3.8.1.4]',
        'key': 'zte.onu.states.walk', 'delay': '1m', 'history': '0', 'trends': '0',
        'value_type': 'TEXT', 'description': 'Uma coleta compartilhada para todas as PONs; utiliza a porta e comunidade da interface SNMP.'
    }.items():
        put(master, k, v)
    for name, key, oid in [
        ('ZTE: modelo e versão', 'zte.system.description', '1.3.6.1.2.1.1.1.0'),
        ('ZTE: nome do equipamento', 'zte.system.name', '1.3.6.1.2.1.1.5.0'),
    ]:
        item = ET.SubElement(items, 'item')
        for k, v in {'uuid': uid(key), 'name': name, 'type': 'SNMP_AGENT', 'snmp_oid': oid,
                     'key': key, 'delay': '1h', 'history': '7d', 'trends': '0', 'value_type': 'CHAR'}.items():
            put(item, k, v)
    avail = ET.SubElement(items, 'item')
    for k, v in {'uuid': uid('available'), 'name': 'ZTE: disponibilidade SNMP',
                 'type': 'INTERNAL', 'key': 'zabbix[host,snmp,available]', 'delay': '10s', 'history': '7d'}.items():
        put(avail, k, v)
    for rule in template.findall('./discovery_rules/discovery_rule'):
        put(rule, 'delay', '1h')
        if rule.findtext('key') == 'descobertas.atenuacao.gpon.b':
            put(rule.find('./filter/conditions/condition'), 'value', '^2147483647$')
        if rule.findtext('key') == 'descobertas.cpu.gpon.b':
            put(rule, 'status', 'ENABLED')
        for item in rule.findall('./item_prototypes/item_prototype'):
            put(item, 'history', '7d')
            if item.findtext('type') != 'EXTERNAL':
                put(item, 'delay', '1m' if 'Card' in item.findtext('key') else '30s')
            if item.findtext('key', '').startswith('Sinal['):
                # 2147483647 significa medição indisponível e não potência óptica real.
                item.remove(item.find('preprocessing'))
                preprocess(item, 'JAVASCRIPT',
                    'var n = Number(value); if (!isFinite(n) || n === 2147483647) '
                    '{ return null; } return n / 1000;')
                put(item, 'name', 'Interface {#INTDESC}: medição óptica')
                put(item, 'description', 'Escala /1000 do template original. Não trata o valor sentinela 2147483647 como medição. Unidade deve ser conferida no MIB antes de definir limites.')
            if item.findtext('type') == 'EXTERNAL':
                put(item, 'type', 'DEPENDENT')
                put(item, 'name', 'ONUs OffLine (estado 7): {#OLTGPON}')
                put(item, 'key', 'zte.onu.state7[{#SNMPINDEX}]')
                put(item, 'delay', '0')
                put(ET.SubElement(item, 'master_item'), 'key', 'zte.onu.states.walk')
                preprocess(item, 'JAVASCRIPT',
                    'if (value.indexOf("No Such")>=0 || value.indexOf("INTEGER:")<0) throw "Tabela de ONUs indisponível";\n'
                    'var lines = value.split(/\\r?\\n/), count = 0;\n'
                    'var prefix = ".1.3.6.1.4.1.3902.1082.500.10.2.3.8.1.4.{#SNMPINDEX}.";\n'
                    'for (var i=0; i<lines.length; i++) {\n'
                    ' var line=lines[i].trim(); if (line.charAt(0)!==".") line="."+line;\n'
                    ' if (line.indexOf(prefix)!==0) continue;\n'
                    ' var m=line.match(/=\\s*(?:INTEGER:\\s*)?(?:[A-Za-z][\\w-]*\\()?([0-9]+)\\)?\\s*$/);\n'
                    ' if (!m) throw "Estado ONU inválido"; if(Number(m[1])===7) count++;\n'
                    '}\nreturn count;')
                put(item, 'description', 'Conta exatamente o estado 7 do OID ZTE, como o helper original. Falhas de comunicação ficam no item mestre e não são convertidas em zero.')
        if rule.findtext('key') == 'descobertas.interfaces.gpon.b':
            extra = ET.SubElement(rule.find('item_prototypes'), 'item_prototype')
            for k, v in {'uuid': uid('notonline'), 'name': 'ONUs não online (todos os estados): {#OLTGPON}',
                         'type': 'CALCULATED', 'key': 'zte.onu.notonline[{#SNMPINDEX}]',
                         'delay': '30s', 'history': '7d',
                         'params': 'last(//chave.gpon.zte.autorizadas.b.[{#OLTGPON}])-last(//chave.gpon.zte.onlines.b.[{#OLTGPON}])',
                         'description': 'Autorizadas menos online. Inclui LOS, energia e demais estados; não equivale apenas ao estado 7.'}.items():
                put(extra, k, v)
    # O template original não inclui alertas; acrescenta disponibilidade e recursos.
    alert_specs = [
        (avail, '{HOST.NAME}: comunicação SNMP indisponível',
         f'max(/{NAME}/zabbix[host,snmp,available],30s)=0', 'HIGH'),
        (items[1], '{HOST.NAME}: uso de memória acima de 90%',
         f'min(/{NAME}/{items[1].findtext("key")},1m)>90', 'AVERAGE'),
        (items[2], '{HOST.NAME}: uso de CPU acima de 90%',
         f'min(/{NAME}/{items[2].findtext("key")},1m)>90', 'AVERAGE'),
    ]
    for item, name, expression, priority in alert_specs:
        alert = ET.SubElement(ET.SubElement(item, 'triggers'), 'trigger')
        for k, v in {'uuid': uid(name), 'name': name, 'expression': expression, 'priority': priority}.items():
            put(alert, k, v)
    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='unicode', xml_declaration=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(build(), encoding='utf-8')
    print(f'Template sem credenciais gerado em {args.output}')
