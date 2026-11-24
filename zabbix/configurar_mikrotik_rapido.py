#!/usr/bin/env python3
"""Perfil adicional de alertas rápidos apenas para os hosts do grupo Mikrotik."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

NAME = 'GEST - MikroTik Alertas Rapidos'
PREFIX = 'gest.mikrotik.'
IF = '1.3.6.1.2.1.'
STORAGE = IF + '25.2.3.1.'
CPU = IF + '25.3.3.1.2'
PING = 'icmpping[,3,200,56,1000]'
LATENCY = 'icmppingsec[,3,200,56,1000,avg]'
LOSS = 'icmppingloss[,3,200,56,1000]'
NET_DISCOVERY_JS = '''var rows=JSON.parse(value); if(!Array.isArray(rows)) rows=rows.data;
if(!Array.isArray(rows)) throw "Descoberta de interfaces inválida";
var out=[]; for(var i=0;i<rows.length;i++){
 var r=rows[i], t=String(r["{#IFTYPE}"]), n=r["{#IFNAME}"];
 if(!/^(6|135|136)$/.test(t) || typeof n!=="string" || !n.length) continue;
 if(typeof r["{#IFALIAS}"]!=="string") r["{#IFALIAS}"]=""; out.push(r);
} return JSON.stringify(out);'''


def ref(key):
    return '/' + NAME + '/' + key


def held(key, comparison, seconds=15, fn='min'):
    p = ref(key)
    return f'{fn}({p},{seconds}s){comparison} and last({p},#1:now-{seconds}s){comparison}'


def pp(kind, params):
    return {'type': kind, 'params': params, 'error_handler': 0, 'error_handler_params': ''}


def configure(api, backup_dir):
    groups = api.call('hostgroup.get', {'filter': {'name': 'Mikrotik'}, 'output': ['groupid']})
    if len(groups) != 1:
        raise RuntimeError('Grupo Mikrotik não encontrado; nenhum host alterado.')
    hosts = api.call('host.get', {'groupids': [groups[0]['groupid']], 'filter': {'status': 0},
        'output': ['hostid', 'host', 'name'], 'selectParentTemplates': ['templateid', 'host'],
        'selectInterfaces': ['interfaceid', 'type', 'ip', 'port']})
    if not hosts or any(not any(i['type'] == '2' for i in h['interfaces']) for h in hosts):
        raise RuntimeError('Grupo Mikrotik vazio ou host sem interface SNMP; conferir escopo.')
    hostids = [h['hostid'] for h in hosts]
    old_templates = sorted({t['templateid'] for h in hosts for t in h['parentTemplates']
                            if t['host'] != NAME})
    snapshot = {'hosts': hosts,
        'triggers': api.call('trigger.get', {'hostids': hostids + old_templates,
            'output': ['triggerid','description','status','expression','templateid','value']}),
        'prototypes': api.call('triggerprototype.get', {'hostids': hostids + old_templates,
            'output': ['triggerid','description','status','expression','templateid']})}
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / f'mikrotik-rapid-before-{time.time_ns()}.json'
    with open(backup, 'x', opener=lambda p,f: os.open(p,f,0o600)) as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
    templates = api.call('template.get', {'filter': {'host': NAME}, 'output': ['templateid']})
    macros = {'{$GEST.FAST.CPU.MAX}': '90', '{$GEST.FAST.MEMORY.MAX}': '90',
              '{$GEST.FAST.DISK.WARN}': '80', '{$GEST.FAST.DISK.HIGH}': '90',
              '{$GEST.FAST.LATENCY.WARN}': '0.09', '{$GEST.FAST.LATENCY.HIGH}': '0.10',
              '{$GEST.FAST.TRAFFIC.BASELINE}': '100000000',
              '{$GEST.FAST.TRAFFIC.DROP}': '0.20', '{$GEST.FAST.TRAFFIC.RECOVERY}': '0.70',
              '{$GEST.FAST.IF.NAME.EXCLUDE}': '^(<.*>|pppoe.*|l2tp.*|sstp.*|pptp.*|ovpn.*|veth.*)$'}
    if templates:
        tid = templates[0]['templateid']
    else:
        template_groups = api.call('templategroup.get', {'filter': {'name': 'GEST'}, 'output': ['groupid']})
        if len(template_groups) != 1:
            raise RuntimeError('Grupo de templates GEST não encontrado.')
        tid = api.call('template.create', {'host': NAME, 'name': NAME,
            'groups': [{'groupid': template_groups[0]['groupid']}],
            'description': 'Perfil adicional RouterOS: coleta rápida apenas de saúde e portas físicas/VLANs. Não acelera contadores individuais PPPoE. Falha ICMP e limites por janela completa de 15s; recuperação ICMP/recursos/banda por 30s estáveis. SNMP usa nodata mínimo de 30s e recupera com o retorno das coletas. Queda de banda >=80% por 15s contra 5min anteriores, base >100Mb/s; recupera por 30s acima de 70% da referência móvel e tráfego positivo. IP público compartilhado significa que ping verifica a borda/NAT, enquanto SNMP usa a porta específica da interface.',
            'macros': [{'macro': k, 'value': v} for k,v in macros.items()]})['templateids'][0]

    def upsert(entity, data, key='key_'):
        current = api.call(entity + '.get', {'hostids': [tid], 'output': 'extend',
                                             'filter': {key: data[key]}})
        identity = 'triggerid' if entity.startswith('trigger') else 'itemid'
        if current:
            changes=dict(data, **{identity: current[0][identity]})
            if entity in ('item','itemprototype','discoveryrule'):
                changes.pop('hostid',None)
            if entity=='itemprototype':changes.pop('ruleid',None)
            api.call(entity + '.update', changes)
            return current[0][identity]
        return api.call(entity + '.create', data)[identity + 's'][0]

    def item(key, name, oid=None, delay='5s', type_=20, value_type=3, **extra):
        data = {'hostid': tid, 'key_': key, 'name': name, 'type': type_, 'value_type': value_type,
                'delay': delay, 'history': '7d', 'trends': '90d',
                'tags': [{'tag': 'profile', 'value': 'GEST-fast'}]}
        if oid:
            data['snmp_oid'] = oid
        data.update(extra)
        return upsert('item', data)

    def trigger(name, expression, priority=3, recovery=None, deps=(), **extra):
        data = {'description': '{HOST.NAME}: ' + name, 'expression': expression,
                'priority': priority, 'status': 0,
                'recovery_mode': 1 if recovery else 0, 'recovery_expression': recovery or '',
                'dependencies': [{'triggerid': x} for x in deps],
                'tags': [{'tag': 'profile', 'value': 'GEST-fast'}]}
        data.update(extra)
        return upsert('trigger', data, 'description')

    item(PING, 'GEST: disponibilidade ICMP rápida', type_=3)
    item(LATENCY, 'GEST: latência ICMP rápida', type_=3, value_type=0, units='s')
    item(LOSS, 'GEST: perda ICMP rápida', type_=3, value_type=0, units='%')
    item(PREFIX+'uptime', 'GEST: heartbeat SNMP', '1.3.6.1.2.1.1.3.0',
         preprocessing=[pp(1,'0.01')], units='uptime')
    offline = trigger('sem resposta ICMP por 15 segundos', held(PING,'=0',fn='max'),4,
                      held(PING,'=1',30), comments='Janela completa de 15s com coleta de 5s. Timeout, agendamento e mensageiro podem acrescentar atraso. Em IP com NAT compartilhado, verifica a conectividade da borda.')
    snmp = trigger('sem coleta SNMP por pelo menos 30 segundos',
                   f'nodata({ref(PREFIX+"uptime")},30s)=1',3,
                   f'nodata({ref(PREFIX+"uptime")},30s)=0', deps=[offline],
                   comments='nodata tem mínimo de 30s e avaliação periódica. Porta SNMP específica do host; não confundir com ping do IP público/NAT.')
    lat_hi = trigger('latência ICMP acima de 100 ms por 15 segundos',
                     held(LATENCY,'>{$GEST.FAST.LATENCY.HIGH}') + f' and last({ref(PING)})=1',3,
                     held(LATENCY,'<0.08',30,fn='max'),deps=[offline])
    trigger('latência ICMP acima de 90 ms por 15 segundos',
            held(LATENCY,'>{$GEST.FAST.LATENCY.WARN}') + f' and last({ref(PING)})=1',2,
            held(LATENCY,'<0.08',30,fn='max'),deps=[offline,lat_hi])
    trigger('perda ICMP acima de 20% por 15 segundos',
            held(LOSS,'>20')+f' and max({ref(LOSS)},15s)<100',2,
            held(LOSS,'<10',30,fn='max'),deps=[offline])

    cpu_master = item(PREFIX+'cpu.walk','GEST: coleta de CPU por núcleo',f'walk[{CPU}]',
                      value_type=4,history='0',trends='0')
    cpu_key = PREFIX+'cpu.max'
    item(cpu_key,'GEST: maior utilização de CPU entre os núcleos',type_=18,delay='0',
         master_itemid=cpu_master,value_type=0,units='%',preprocessing=[
             pp(29,'{#LOAD}\n'+CPU+'\n0'),
             pp(21,'var a=JSON.parse(value); if(!a.length) throw "CPU sem dados"; var m=0; for(var i=0;i<a.length;i++){var n=Number(a[i]["{#LOAD}"]); if(!isFinite(n)) throw "CPU inválida"; m=Math.max(m,n);} return m;')])
    trigger('CPU acima de 90% por 15 segundos em pelo menos um núcleo',
            held(cpu_key,'>{$GEST.FAST.CPU.MAX}'),4,
            held(cpu_key,'<80',30,fn='max'),deps=[offline,snmp])
    # RAM no índice HOST-RESOURCES usado pelos templates RouterOS existentes.
    item(PREFIX+'memory.total','GEST: memória total (unidades SNMP)',STORAGE+'5.65536',delay='10s')
    item(PREFIX+'memory.used','GEST: memória usada (unidades SNMP)',STORAGE+'6.65536',delay='10s')
    item(PREFIX+'memory.pused','GEST: utilização de memória',type_=15,value_type=0,units='%',
         params='last(//'+PREFIX+'memory.used)/last(//'+PREFIX+'memory.total)*100')
    trigger('memória acima de 90% por 15 segundos',held(PREFIX+'memory.pused','>{$GEST.FAST.MEMORY.MAX}'),3,
            held(PREFIX+'memory.pused','<85',30,fn='max'),deps=[offline,snmp])

    disk_master = item(PREFIX+'disk.walk','GEST: coleta de discos',
        'walk['+','.join(STORAGE+x for x in ['2','3','4','5','6'])+']',
        value_type=4,history='0',trends='0')
    disk_rule = upsert('discoveryrule', {'hostid': tid,'name':'GEST: descoberta de discos fixos',
        'key_':PREFIX+'disk.discovery','type':18,'delay':'0','master_itemid':disk_master,
        'lifetime':'7d','filter':{'evaltype':0,'conditions':[{'macro':'{#TYPE}',
             'value':'(\\.4$|hrStorageFixedDisk$)','operator':8,'formulaid':'A'}]},
        'preprocessing':[pp(29,'{#TYPE}\n'+STORAGE+'2\n0\n{#DISK}\n'+STORAGE+'3\n0\n{#ALLOC}\n'+STORAGE+'4\n0'),pp(20,'1h')]})

    def prototype(rule, key, name, oid=None, type_=20, delay='5s', **extra):
        data = {'ruleid':rule,'hostid':tid,'key_':key,'name':name,'type':type_,
                'value_type':3,'delay':delay,'history':'7d','trends':'90d',
                'tags':[{'tag':'profile','value':'GEST-fast'}]}
        if oid:data['snmp_oid']=oid
        data.update(extra)
        return upsert('itemprototype',data)

    for col, kind in [('5','total'),('6','used')]:
        prototype(disk_rule,PREFIX+'disk.'+kind+'[{#SNMPINDEX}]','GEST: disco {#DISK}: '+kind,
            type_=18,delay='0',master_itemid=disk_master,units='B',
            preprocessing=[pp(28,STORAGE+col+'.{#SNMPINDEX}\n0'),pp(1,'{#ALLOC}')])
    disk = PREFIX+'disk.pused[{#SNMPINDEX}]'
    prototype(disk_rule,disk,'GEST: disco {#DISK}: ocupação',type_=15,value_type=0,units='%',
              params='last(//'+PREFIX+'disk.used[{#SNMPINDEX}])/last(//'+PREFIX+'disk.total[{#SNMPINDEX}])*100')

    def prototype_trigger(name, expression, priority, recovery, deps=(), **extra):
        data={'description':'{HOST.NAME}: '+name,'expression':expression,'priority':priority,
              'status':0,'recovery_mode':1,'recovery_expression':recovery,
              'dependencies':[{'triggerid':x} for x in deps],
              'tags':[{'tag':'profile','value':'GEST-fast'}]}
        data.update(extra)
        return upsert('triggerprototype',data,'description')

    disk_hi = prototype_trigger('disco {#DISK} acima de 90% por 15 segundos',
        held(disk,'>{$GEST.FAST.DISK.HIGH}'),4,held(disk,'<85',30,fn='max'),[offline,snmp])
    prototype_trigger('disco {#DISK} acima de 80% por 15 segundos',
        held(disk,'>{$GEST.FAST.DISK.WARN}'),2,held(disk,'<75',30,fn='max'),[offline,snmp,disk_hi])

    net_rule = upsert('discoveryrule',{'hostid':tid,'name':'GEST: portas físicas e VLANs',
        'key_':PREFIX+'interface.discovery','type':20,'delay':'1h','lifetime':'7d',
        'snmp_oid':'discovery[{#IFNAME},'+IF+'31.1.1.1.1,{#IFTYPE},'+IF+'2.2.1.3,{#IFALIAS},'+IF+'31.1.1.1.18]',
        'preprocessing':[pp(21,NET_DISCOVERY_JS)],
        'filter':{'evaltype':1,'conditions':[
            {'macro':'{#IFTYPE}','value':'^(6|135|136)$','operator':8,'formulaid':'A'},
            {'macro':'{#IFNAME}','value':'{$GEST.FAST.IF.NAME.EXCLUDE}','operator':9,'formulaid':'B'}]}})
    admin = PREFIX+'if.admin[{#SNMPINDEX}]'
    oper = PREFIX+'if.oper[{#SNMPINDEX}]'
    prototype(net_rule,admin,'GEST: interface {#IFNAME}: estado administrativo',IF+'2.2.1.7.{#SNMPINDEX}')
    prototype(net_rule,oper,'GEST: interface {#IFNAME}: estado operacional',IF+'2.2.1.8.{#SNMPINDEX}',
              tags=[{'tag':'profile','value':'GEST-fast'},{'tag':'ifType','value':'{#IFTYPE}'}])
    port_down = prototype_trigger('interface {#IFNAME} ({#IFALIAS}) sem link por 15 segundos',
        held(oper,'<>1',fn='min') + f' and last({ref(admin)})=1 and (count({ref(oper)},1h,"eq",1)>0 or {{TRIGGER.VALUE}}=1)',4,
        f'last({ref(admin)})<>1 or ('+held(oper,'=1',30)+')',[offline,snmp],
        tags=[{'tag':'profile','value':'GEST-fast'},{'tag':'ifType','value':'{#IFTYPE}'}],
        comments='Só abre depois de a porta ter sido vista operacional na última hora; evita alertas iniciais para portas já sem uso. A perda contínua mantém o problema aberto. Recupera após 30s de link estável ou desativação administrativa.')
    for direction,col,label in [('in','6','entrada'),('out','10','saída')]:
        key=PREFIX+'if.'+direction+'[{#SNMPINDEX}]'
        prototype(net_rule,key,'GEST: interface {#IFNAME}: bits de '+label,
                  IF+'31.1.1.1.'+col+'.{#SNMPINDEX}',units='bps',preprocessing=[pp(10,''),pp(1,'8')])
        p=ref(key);baseline=f'avg({p},5m:now-20s)'
        expression=(f'last({ref(admin)})=1 and last({ref(oper)})=1 and '
            f'count({p},5m:now-20s)>=55 and {baseline}>{{$GEST.FAST.TRAFFIC.BASELINE}} and '
            f'max({p},15s)<={baseline}*{{$GEST.FAST.TRAFFIC.DROP}} and '
            f'last({p},#1:now-15s)<={baseline}*{{$GEST.FAST.TRAFFIC.DROP}}')
        recovery=(f'last({ref(admin)})<>1 or (min({p},30s)>0 and '
            f'min({p},30s)>={baseline}*{{$GEST.FAST.TRAFFIC.RECOVERY}} and '
            f'last({p},#1:now-30s)>={baseline}*{{$GEST.FAST.TRAFFIC.RECOVERY}})')
        prototype_trigger('interface {#IFNAME} ({#IFALIAS}): queda de pelo menos 80% na '+label,
            expression,2,recovery,[offline,snmp,port_down],
            tags=[{'tag':'profile','value':'GEST-fast'},{'tag':'ifType','value':'{#IFTYPE}'}],
            comments='Anomalia de tráfego, não prova isolada de falha. Janela completa de 15s <=20% da média (queda >=80%) dos 5min encerrados 20s antes; base >100Mb/s e pelo menos 55 amostras. Referência móvel pode se adaptar ao novo patamar. Recupera com tráfego positivo estável por 30s >=70% da referência ou porta desativada administrativamente. Não inclui interfaces individuais PPPoE.')

    for host in hosts:
        links=[{'templateid':t['templateid']} for t in host['parentTemplates']]
        if not any(t['templateid']==tid for t in links):
            api.call('host.update',{'hostid':host['hostid'],'templates':links+[{'templateid':tid}]})
    # Não desabilita os alertas antigos antes da validação operacional do novo perfil.
    from configurar_portas_floresta_ur import configure as configure_port_policy
    port_policy=configure_port_policy(api,backup_dir)
    result={'templateid':tid,'hosts':[{'hostid':h['hostid'],'name':h['name']} for h in hosts],
            'backup':str(backup),'legacy_templates':old_templates,'port_policy':port_policy}
    result_path=backup.with_name(backup.stem.replace('before','applied')+'.json')
    with open(result_path,'x',opener=lambda p,f:os.open(p,f,0o600)) as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    export=Path(__file__).parent/'templates/gest-mikrotik-alertas-rapidos.yaml'
    export.write_text(api.call('configuration.export',{'format':'yaml','options':{'templates':[tid]}}))
    return result



def finalize(api, backup_dir):
    templates=api.call('template.get',{'filter':{'host':NAME},'output':['templateid']})
    if len(templates)!=1:raise RuntimeError('Aplique o perfil antes de finalizar.')
    tid=templates[0]['templateid']
    hosts=api.call('host.get',{'templateids':[tid],'output':['hostid','name']})
    ids=[h['hostid'] for h in hosts]
    items=api.call('item.get',{'hostids':ids,'search':{'key_':PREFIX},
         'output':['hostid','key_','state','error','lastclock','type']})
    now=time.time()
    for h in hosts:
        rows=[x for x in items if x['hostid']==h['hostid']]
        for required in [PREFIX+'cpu.max',PREFIX+'memory.pused',PREFIX+'uptime']:
            if not any(x['key_']==required and x['state']=='0' and now-int(x['lastclock'])<30 for x in rows):
                raise RuntimeError('Ainda sem coleta rápida validada: '+h['name']+' / '+required)
        if not any(x['key_'].startswith(PREFIX+'if.oper[') and x['state']=='0' and now-int(x['lastclock'])<30 for x in rows):
            raise RuntimeError('Ainda sem portas descobertas: '+h['name'])
        if not any(x['key_'].startswith(PREFIX+'disk.pused[') and x['state']=='0' and now-int(x['lastclock'])<30 for x in rows):
            raise RuntimeError('Ainda sem disco descoberto: '+h['name'])
        if any(x['state']=='1' or x['error'] for x in rows):
            raise RuntimeError('Há erro em item rápido de '+h['name'])
    rules=api.call('discoveryrule.get',{'hostids':ids,'search':{'key_':PREFIX},'output':['state','error']})
    if any(r['state']=='1' or r['error'] for r in rules):raise RuntimeError('Há erros nas descobertas rápidas.')
    fast=api.call('trigger.get',{'hostids':ids,'tags':[{'tag':'profile','value':'GEST-fast'}],
        'output':['state','error']})
    if any(t['state']=='1' or t['error'] for t in fast):raise RuntimeError('Há erros nos gatilhos rápidos.')
    icmp=api.call('item.get',{'hostids':ids,'filter':{'key_':[PING,LATENCY,LOSS]},
        'output':['hostid','key_','state','error','lastclock']})
    if len(icmp)!=3*len(hosts) or any(i['state']=='1' or now-int(i['lastclock'])>=30 for i in icmp):
        raise RuntimeError('Coletas ICMP rápidas ainda não validadas em todos os hosts.')
    old_names={'Mikrotik: High ICMP ping loss','Mikrotik: Unavailable by ICMP ping',
               'Mikrotik: High ICMP ping response time','Mikrotik: High memory utilization',
               'Mikrotik: No SNMP data collection'}
    suffixes=(': High CPU utilization',': Disk space is low',': Disk space is critically low')
    def legacy(t):return t['description'] in old_names or t['description'].endswith(suffixes)
    triggers=[t for t in api.call('trigger.get',{'hostids':ids,'output':['triggerid','description','status','value']}) if legacy(t)]
    prototypes=[t for t in api.call('triggerprototype.get',{'hostids':ids,'output':['triggerid','description','status']}) if legacy(t)]
    if any(t['value']=='1' for t in triggers):
        raise RuntimeError('Há problemas antigos abertos; revisar antes de desativar alertas equivalentes.')
    backup_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=backup_dir/f'mikrotik-legacy-status-before-{time.time_ns()}.json'
    with open(path,'x',opener=lambda p,f:os.open(p,f,0o600)) as stream:
        json.dump({'hosts':hosts,'triggers':triggers,'prototypes':prototypes},stream,ensure_ascii=False,indent=2)
    for entity,rows in [('triggerprototype',prototypes),('trigger',triggers)]:
        pending=[{'triggerid':t['triggerid'],'status':1} for t in rows if t['status']=='0']
        if pending:api.call(entity+'.update',pending)
    return {'templateid':tid,'hosts_validated':len(hosts),'legacy_trigger_count':len(triggers),
            'legacy_prototype_count':len(prototypes),'backup':str(path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--apply',action='store_true',help='Aplica no grupo Mikrotik do Zabbix configurado no aplicativo.')
    mode.add_argument('--finalize',action='store_true',help='Valida as coletas e desativa alertas antigos equivalentes somente nos hosts com perfil rápido.')
    parser.add_argument('--backup-dir',type=Path,default=Path.home()/'.local/share/alert-zabbix/backups')
    args=parser.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'extension'))
    from client import API,load_config,secret_access
    config=load_config();api=API(config)
    api.auth=api.call('user.login',{'username':config['username'],'password':secret_access(config)}) if config['auth_mode']=='password' else secret_access(config)
    try:print(json.dumps((finalize if args.finalize else configure)(api,args.backup_dir),ensure_ascii=False,indent=2))
    finally:
        if config['auth_mode']=='password':api.call('user.logout',[])

if __name__=='__main__':main()
