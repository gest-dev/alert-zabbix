#!/usr/bin/env python3
"""Cria o dashboard nativo da OLT ZTE, com totais calculados e visão GPON."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

BASE = Path(__file__).resolve().parent
HOST = 'UrTelecom OLT ZTE Titan'
DASHBOARD = 'UrTelecom · OLT ZTE Titan'
TEMPLATE = 'GEST - ZTE TITAN C6xx SNMP'
PREFIX = 'zte.dashboard.'
COLORS = {'blue':'162E43','green':'163E36','amber':'49371D','purple':'2E2549',
          'slate':'1B2B3A','red':'732C3A','text':'F1F5F9','muted':'ABC0D2'}


def f(name, value, type_=0):
    return {'type':type_, 'name':name, 'value':str(value)}


def widget(type_, name, x, y, width, height, fields):
    return {'type':type_, 'name':name,'x':x,'y':y,'width':width,'height':height,
            'view_mode':0,'fields':fields}


def natural(text):
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)',text)]


def card(item, title, x, y, width=6, height=3, color='blue', desc='', decimals=0,
         value_size=42, thresholds=()):
    fields=[f('itemid',item['itemid'],4),f('rf_rate',10),f('adv_conf',1),
            *[f('show',n) for n in (1,2,3)],f('description',desc or item['name'],1),
            f('decimal_places',decimals),f('desc_size',11),f('value_size',value_size),
            f('decimal_size',27),f('units_size',24),f('time_size',9),
            f('desc_color',COLORS['muted'],1),f('value_color',COLORS['text'],1),
            f('units_color',COLORS['text'],1),f('time_color',COLORS['muted'],1),
            f('bg_color',COLORS[color],1)]
    for i,(threshold,tone) in enumerate(thresholds):
        fields.extend([f(f'thresholds.threshold.{i}',threshold,1),
                       f(f'thresholds.color.{i}',COLORS[tone],1)])
    return widget('item',title,x,y,width,height,fields)


def graph(title, series, host, x,y,width=12,height=5,percent=False):
    fields=[f('rf_rate',30),f('righty',0),f('lefty_min','0',1),f('legend',1),
            f('legend_lines',min(8,len(series))),f('legend_columns',1),f('show_problems',1),
            f('graph_item_problems',0),f('problemhosts.0',host,1)]
    if percent:fields.append(f('lefty_max','100',1))
    for i,(item,color) in enumerate(series):
        fields.extend([f(f'ds.hosts.{i}.0',host,1),f(f'ds.items.{i}.0',item['name'],1),
                       f(f'ds.color.{i}',color,1),f(f'ds.width.{i}',2),
                       f(f'ds.fill.{i}',2),f(f'ds.transparency.{i}',2),
                       f(f'ds.missingdatafunc.{i}',0)])
    return widget('svggraph',title,x,y,width,height,fields)


def configure(api, host_name=HOST):
    hosts=api.call('host.get',{'filter':{'host':host_name},'output':['hostid','host','name'],
        'selectParentTemplates':['templateid','host'],'selectInterfaces':['ip','port','type']})
    if len(hosts)!=1:raise RuntimeError('Host ZTE não encontrado ou nome ambíguo.')
    host=hosts[0];hid=host['hostid']
    parents=[t for t in host['parentTemplates'] if t['host']==TEMPLATE]
    if len(parents)!=1:raise RuntimeError('Template ZTE esperado não está vinculado ao host.')
    tid=parents[0]['templateid']
    old=api.call('dashboard.get',{'filter':{'name':DASHBOARD},'output':'extend',
        'selectPages':'extend','selectUsers':'extend','selectUserGroups':'extend'})
    if len(old)>1:raise RuntimeError('Dashboard duplicado; conferir antes de alterar.')
    backup_dir=Path.home()/'.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    backup=backup_dir/f'zte-dashboard-before-{time.time_ns()}.json'
    snapshot={'dashboards':old,'template':api.call('configuration.export',
        {'format':'yaml','options':{'templates':[tid]}}),'host':host}
    with open(backup,'x',opener=lambda p,flags:os.open(p,flags,0o600)) as out:
        json.dump(snapshot,out,ensure_ascii=False,indent=2)

    template_items=api.call('item.get',{'hostids':[tid],'output':['itemid','key_','name']})
    own={i['key_']:i['itemid'] for i in template_items}
    def item(key,name,type_,value_type=3,**extra):
        data={'hostid':tid,'key_':key,'name':name,'type':type_,'value_type':value_type,
              'delay':'30s','history':'7d','trends':'90d',
              'tags':[{'tag':'component','value':'dashboard'},{'tag':'vendor','value':'ZTE'}]}
        data.update(extra)
        if key in own:
            data.pop('hostid')
            api.call('item.update',dict(data,itemid=own[key]));return own[key]
        ident=api.call('item.create',data)['itemids'][0];own[key]=ident;return ident

    sums={
        'authorized':'sum(last_foreach(//chave.gpon.zte.autorizadas.b.[*]))',
        'online':'sum(last_foreach(//chave.gpon.zte.onlines.b.[*]))',
        'state7':'sum(last_foreach(//zte.onu.state7[*]))'}
    for key,label in [('authorized','autorizadas'),('online','online'),('state7','OffLine (estado 7)')]:
        item(PREFIX+'onu.'+key,'GPON: total de ONUs '+label,15,params=sums[key])
    item(PREFIX+'onu.notonline','GPON: total de ONUs não online',15,
         params=sums['authorized']+'-'+sums['online'])
    item(PREFIX+'onu.online.percent','GPON: percentual de ONUs online',15,value_type=0,units='%',
         params='100*'+sums['online']+'/('+sums['authorized']+'+('+sums['authorized']+'=0))')
    for direction,label in [('in','entrada'),('out','saída')]:
        item(PREFIX+'ethernet.'+direction,'Ethernet: soma do tráfego de '+label,15,
             params='sum(last_foreach(//net.if.'+direction+'[*]))',units='bps')

    master=item(PREFIX+'gpon.walk','GPON: dados para o painel por porta',20,value_type=4,
        history='0',trends='0',snmp_oid='walk[1.3.6.1.2.1.31.1.1.1.1,1.3.6.1.2.1.2.2.1.8,1.3.6.1.4.1.3902.1082.500.10.2.2.3.1.14,1.3.6.1.4.1.3902.1082.500.10.2.2.3.1.15]')
    raw_items=api.call('item.get',{'hostids':[hid],'output':['itemid','key_','name']})
    slots=sorted({re.search(r'gpon_olt-(\d+/\d+)/\d+',i['key_']).group(1)
        for i in raw_items if i['key_'].startswith('chave.gpon.zte.autorizadas.b.')})
    if not slots:raise RuntimeError('Nenhuma porta GPON descoberta.')
    html_source=(BASE/'widgets/zte-gpon-summary.js').read_text()
    for slot in slots:
        if not re.fullmatch(r'\d+/\d+',slot):raise RuntimeError('Slot inválido.')
        item(PREFIX+'gpon.html['+slot+']','GPON: resumo visual da placa '+slot,18,value_type=4,
            delay='0',master_itemid=master,history='1h',trends='0',
            preprocessing=[{'type':21,'params':html_source.replace('__SLOT__',slot),
                            'error_handler':0,'error_handler_params':''}])

    def valuemap(name,mappings):
        found=api.call('valuemap.get',{'hostids':[tid],'filter':{'name':name},'output':['valuemapid']})
        if found:return found[0]['valuemapid']
        return api.call('valuemap.create',{'hostid':tid,'name':name,'mappings':[
            {'type':0,'value':str(k),'newvalue':v} for k,v in mappings]})['valuemapids'][0]
    vm=valuemap('GEST - Disponibilidade SNMP',[(0,'Sem resposta'),(1,'Disponível'),(2,'Aguardando')])
    api.call('item.update',{'itemid':own['zabbix[host,snmp,available]'],'valuemapid':vm})
    status_proto=api.call('itemprototype.get',{'hostids':[tid],
        'search':{'key_':'Interace.Status.zte['},'output':['itemid']})
    if len(status_proto)!=1:raise RuntimeError('Protótipo de estado das interfaces não encontrado.')
    vm=valuemap('GEST - Estado da interface',[(1,'Operante'),(2,'Sem link'),(3,'Em teste'),
        (4,'Desconhecido'),(5,'Dormente'),(6,'Ausente'),(7,'Camada inferior indisponível')])
    api.call('itemprototype.update',{'itemid':status_proto[0]['itemid'],'valuemapid':vm})

    gp=api.call('itemprototype.get',{'hostids':[tid],'output':['itemid','key_']})
    keys={i['key_']:i['itemid'] for i in gp}
    graph_name='GPON {#OLTGPON}: ONUs autorizadas, online e não online'
    graph_data={'name':graph_name,'width':800,'height':250,'yaxismin':0,'ymin_type':1,
        'show_work_period':0,'show_triggers':0,'show_legend':1,'gitems':[
            {'itemid':keys['chave.gpon.zte.autorizadas.b.[{#OLTGPON}]'],'color':'94A3B8','drawtype':0,'sortorder':0},
            {'itemid':keys['chave.gpon.zte.onlines.b.[{#OLTGPON}]'],'color':'34D399','drawtype':1,'sortorder':1},
            {'itemid':keys['zte.onu.notonline[{#SNMPINDEX}]'],'color':'FBBF24','drawtype':2,'sortorder':2}]}
    graphs=api.call('graphprototype.get',{'hostids':[tid],'filter':{'name':graph_name},'output':['graphid']})
    if graphs:api.call('graphprototype.update',dict(graph_data,graphid=graphs[0]['graphid']))
    else:api.call('graphprototype.create',graph_data)
    host_graph=api.call('graphprototype.get',{'hostids':[hid],'filter':{'name':graph_name},'output':['graphid']})[0]['graphid']

    items=api.call('item.get',{'hostids':[hid],'output':['itemid','name','key_','units','value_type']})
    bykey={i['key_']:i for i in items}
    for key in list(own):
        if key.startswith(PREFIX) and key not in bykey:raise RuntimeError('Item novo ainda não herdado: '+key)
    cpu=bykey['1.3.6.1.4.1.3902.3.6002.2.1.1.8.1.1.1.0']
    memory=bykey['1.3.6.1.4.1.3902.3.6002.2.1.1.6.1.1.1.0']
    pages=[];overview=[]
    overview.append(card(bykey['zabbix[host,snmp,available]'],'Conexão · SNMP',0,0,color='red',
        desc='UrTelecom · ZXA10 C620',value_size=28,thresholds=[(1,'green'),(2,'amber')]))
    overview.append(card(cpu,'Processamento · CPU',6,0,desc='Utilização geral',decimals=1,
        thresholds=[(70,'amber'),(90,'red')]))
    overview.append(card(memory,'Recursos · memória',12,0,color='purple',desc='Memória utilizada',
        decimals=1,thresholds=[(80,'amber'),(90,'red')]))
    overview.append(card(bykey['1.3.6.1.2.1.1.3.0'],'Operação · uptime',18,0,color='slate',
        desc='Tempo desde a inicialização',value_size=28))
    for col,(key,title,tone,desc) in enumerate([
        ('authorized','ONUs · autorizadas','blue','Total cadastrado nas portas GPON'),
        ('online','ONUs · online','green','Conectadas neste momento'),
        ('notonline','ONUs · não online','amber','Todos os estados diferentes de online'),
        ('online.percent','ONUs · conectadas / autorizadas','purple','Percentual de ONUs online')]):
        overview.append(card(bykey[PREFIX+'onu.'+key],title,col*6,3,color=tone,desc=desc,
                             decimals=1 if key.endswith('percent') else 0))
    overview.append(graph('GPON · evolução das ONUs',[
        (bykey[PREFIX+'onu.authorized'],'94A3B8'),(bykey[PREFIX+'onu.online'],'34D399'),
        (bykey[PREFIX+'onu.notonline'],'FBBF24')],host['host'],0,6))
    overview.append(graph('Recursos · CPU e memória',[(cpu,'60A5FA'),(memory,'C4B5FD')],host['host'],12,6,percent=True))
    overview.append(card(bykey[PREFIX+'ethernet.in'],'Ethernet · soma de entrada',0,11,width=6,color='green',desc='Soma das interfaces Ethernet',decimals=2,value_size=34))
    overview.append(card(bykey[PREFIX+'ethernet.out'],'Ethernet · soma de saída',6,11,width=6,desc='Soma das interfaces Ethernet',decimals=2,value_size=34))
    overview.append(widget('problems','Problemas atuais · somente esta OLT',12,11,12,3,
        [f('hostids',hid,3),f('show',3),f('show_lines',5),f('show_tags',0),f('rf_rate',10)]))
    overview.append(card(bykey['zte.system.description'],'Equipamento · modelo e software',0,14,width=16,height=2,
        color='slate',desc=host['name'],value_size=20))
    clock=[f('clock_type',1),f('adv_conf',1),*[f('show',v) for v in (1,2,3)],
        f('time_size',45),f('date_size',16),f('tzone_size',12),f('time_sec',0),
        f('tzone_timezone','America/Sao_Paulo',1),f('bg_color',COLORS['slate'],1),
        f('time_color',COLORS['text'],1),f('date_color',COLORS['muted'],1),f('tzone_color',COLORS['muted'],1)]
    overview.append(widget('clock','Horário · Brasília',16,14,8,2,clock))
    pages.append({'name':'Visão geral','widgets':overview})

    gpon=[]
    for n,slot in enumerate(slots):
        gpon.append(widget('plaintext','GPON · placa '+slot,(n%2)*12,(n//2)*11,12,11,
            [f('itemids',bykey[PREFIX+'gpon.html['+slot+']']['itemid'],4),
             f('show_lines',1),f('style',1),f('show_as_html',1),f('rf_rate',30)]))
    gpon.append(widget('graphprototype','Histórico por porta · use a paginação para navegar',0,((len(slots)+1)//2)*11,24,12,
        [f('source_type',2),f('graphid',host_graph,7),f('columns',2),f('rows',3),f('show_legend',1),f('rf_rate',60)]))
    pages.append({'name':'GPON · portas e ONUs','widgets':gpon})

    rx=sorted([i for i in items if i['key_'].startswith('net.if.in[')],key=lambda i:natural(i['name']))
    uplinks=[]
    statuses=[i for i in items if i['key_'].startswith('Interace.Status.zte[') and 'xgei-' in i['name']]
    for n,i in enumerate(sorted(statuses,key=lambda i:natural(i['name']))):
        uplinks.append(card(i,i['name'].replace('Interface ','')+' · link',(n%4)*6,(n//4)*2,
            height=2,color='amber',desc='Estado operacional',value_size=26,
            thresholds=[(1,'green'),(2,'slate'),(3,'amber')]))
    graph_y=((len(statuses)+3)//4)*2
    for n,i in enumerate(rx):
        index=re.search(r'\.(\d+)\]$',i['key_']).group(1)
        out=bykey['net.if.out[ifHCOutOctets.'+index+']']
        uplinks.append(graph(i['name'].replace(': Bits received','')+' · entrada e saída',
            [(i,'34D399'),(out,'60A5FA')],host['host'],(n%2)*12,graph_y+(n//2)*5))
    pages.append({'name':'Uplinks · tráfego','widgets':uplinks})

    hardware=[]
    cores=sorted([i for i in items if i['key_'].startswith('CPU.Card[')],key=lambda i:natural(i['name']))
    for n,i in enumerate(cores):
        idx=re.search(r'\[(\d+)\]',i['key_']).group(1)
        hardware.append(card(i,'CPU · slot '+idx,(n%6)*4,(n//6)*3,width=4,color='purple',
            desc='CPU da placa '+idx,decimals=1,value_size=36,thresholds=[(70,'amber'),(90,'red')]))
    models=sorted([i for i in items if i['key_'].startswith('Card[')],key=lambda i:natural(i['name']))
    for n,i in enumerate(models):
        hardware.append(card(i,'Inventário · '+i['name'],(n%6)*4,3+(n//6)*2,width=4,height=2,
            color='slate',desc='Modelo informado pela OLT',value_size=26))
    hardware.append(graph('Placas · histórico de CPU',[(i,c) for i,c in zip(cores,
        ['34D399','60A5FA','C4B5FD','FBBF24','F472B6','22D3EE'])],host['host'],0,5,width=24,height=5,percent=True))
    optical=[i for i in items if i['key_'].startswith('Sinal[')]
    for n,slot in enumerate(slots):
        group=[i for i in optical if 'gpon_olt-'+slot+'/' in i['name']]
        hardware.append(graph('Óptica · placa '+slot+' · escala original do template',
            [(i,c) for i,c in zip(sorted(group,key=lambda i:natural(i['name'])),
                ['34D399','60A5FA','C4B5FD','FBBF24','F472B6','22D3EE','FB923C','A3E635']*4)],
            host['host'],(n%2)*12,10+(n//2)*7,height=7))
    pages.append({'name':'Hardware · óptica','widgets':hardware})

    events=[widget('problems','Problemas atuais · UrTelecom OLT ZTE Titan',0,0,24,5,
        [f('hostids',hid,3),f('show',3),f('show_lines',20),f('show_tags',1),f('rf_rate',10)]),
        widget('actionlog','Notificações desta OLT · envios, pendências e falhas',0,5,24,6,
        [f('message',host['name'],1),f('show_lines',20),f('rf_rate',30)]),
        graph('GPON · estado 7 e total não online são contagens diferentes',
        [(bykey[PREFIX+'onu.notonline'],'FBBF24'),(bykey[PREFIX+'onu.state7'],'FB923C')],host['host'],0,11,width=24,height=5)]
    pages.append({'name':'Eventos · notificações','widgets':events})
    # O grid nativo usa 24 colunas; detecta colisões antes de publicar.
    for page in pages:
        rects=[]
        for w in page['widgets']:
            assert 0<=w['x'] and w['x']+w['width']<=24
            for p in rects:
                if w['x']<p['x']+p['width'] and p['x']<w['x']+w['width'] and w['y']<p['y']+p['height'] and p['y']<w['y']+w['height']:
                    raise RuntimeError('Widgets sobrepostos em '+page['name'])
            rects.append(w)
    data={'name':DASHBOARD,'display_period':30,'auto_start':0,'pages':pages}
    if old:
        previous_pages={p['name']:p for p in old[0]['pages']}
        for page in pages:
            previous=previous_pages.get(page['name'])
            if not previous:continue
            page['dashboard_pageid']=previous['dashboard_pageid']
            widgets={(w['type'],w['name']):w['widgetid'] for w in previous['widgets']}
            for w in page['widgets']:
                if (w['type'],w['name']) in widgets:w['widgetid']=widgets[(w['type'],w['name'])]
        # Complementos como a aba VLANs têm configurador próprio.
        # Preserve sua posição relativa ao atualizar as cinco páginas base.
        generated={p['name']:p for p in pages}
        pages[:]=[generated.pop(p['name']) if p['name'] in generated else
                  {k:p[k] for k in ['dashboard_pageid','name','display_period','widgets']}
                  for p in old[0]['pages']]
        pages.extend(generated.values())
        did=old[0]['dashboardid'];api.call('dashboard.update',dict(data,dashboardid=did))
    else:
        # Mesmo proprietário/compartilhamento público do painel operacional existente.
        base=api.call('dashboard.get',{'filter':{'name':'GEST · Operação e servidores'},
            'output':['userid','private'],'selectUsers':'extend','selectUserGroups':'extend'})
        if len(base)!=1:raise RuntimeError('Dashboard operacional não encontrado para copiar compartilhamento.')
        data.update({k:base[0][k] for k in ['userid','private','users','userGroups']})
        did=api.call('dashboard.create',data)['dashboardids'][0]
    result=api.call('dashboard.get',{'dashboardids':[did],'output':'extend','selectPages':'extend',
        'selectUsers':'extend','selectUserGroups':'extend'})[0]
    export=BASE/'dashboards';export.mkdir(exist_ok=True)
    (export/'urtelecom-zte-titan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (BASE/'templates/gest-zte-titan-c6xx.yaml').write_text(api.call('configuration.export',
        {'format':'yaml','options':{'templates':[tid]}}))
    rules=api.call('discoveryrule.get',{'hostids':[hid],'filter':{'key_':
        ['descobertas.interfaces.gpon.b','descobertas.interfaces.geral.zte.b']},'output':['itemid']})
    if rules:api.call('task.create',[{'type':6,'request':{'itemid':r['itemid']}} for r in rules])
    return {'dashboardid':did,'url':'/zabbix/zabbix.php?action=dashboard.view&dashboardid='+did,
        'pages':[{'name':p['name'],'widgets':len(p['widgets'])} for p in pages],
        'backup':str(backup)}


def integrate_overview(api):
    """Adiciona uma única página compacta ao slideshow operacional existente."""
    dashboards=api.call('dashboard.get',{'filter':{'name':[
        'GEST · Operação e servidores',DASHBOARD]},'output':'extend',
        'selectPages':'extend','selectUsers':'extend','selectUserGroups':'extend'})
    main=next((d for d in dashboards if d['name']=='GEST · Operação e servidores'),None)
    detail=next((d for d in dashboards if d['name']==DASHBOARD),None)
    if main is None or detail is None:raise RuntimeError('Os dashboards operacional e detalhado precisam existir.')
    if sum(p['name']==DASHBOARD for p in main['pages'])>1:
        raise RuntimeError('Há páginas OLT duplicadas; conferir antes de alterar.')
    source=next(p for p in detail['pages'] if p['name']=='Visão geral')
    summary={'name':DASHBOARD,'display_period':0,'widgets':[]}
    layout={0:(0,2),3:(2,2),6:(4,4),11:(8,2)}
    for w in source['widgets']:
        if int(w['y']) not in layout:continue
        widget_copy={k:json.loads(json.dumps(w[k])) for k in
                     ['type','name','x','y','width','height','view_mode','fields']}
        widget_copy['y'],widget_copy['height']=layout[int(w['y'])]
        if w['type']=='item':
            for field in widget_copy['fields']:
                if field['name']=='value_size':
                    old_size=int(field['value'])
                    field['value']=str(56 if old_size>=40 else (42 if old_size>=34 else 34))
        if w['type']=='problems':
            for field in widget_copy['fields']:
                if field['name']=='show_lines':field['value']='3'
        summary['widgets'].append(widget_copy)
    if len(summary['widgets'])!=13:raise RuntimeError('A visão geral de origem mudou; conferir o resumo.')
    for i,w in enumerate(summary['widgets']):
        for p in summary['widgets'][:i]:
            if int(w['x'])<int(p['x'])+int(p['width']) and int(p['x'])<int(w['x'])+int(w['width']) and int(w['y'])<int(p['y'])+int(p['height']) and int(p['y'])<int(w['y'])+int(w['height']):
                raise RuntimeError('Widgets sobrepostos no resumo.')
    backup_dir=Path.home()/'.local/share/alert-zabbix/backups'
    backup_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    backup=backup_dir/f'gest-before-zte-summary-{time.time_ns()}.json'
    with open(backup,'x',opener=lambda path,flags:os.open(path,flags,0o600)) as stream:
        json.dump(main,stream,ensure_ascii=False,indent=2)
    pages=[]
    for p in main['pages']:
        if p['name']==DASHBOARD:
            summary['dashboard_pageid']=p['dashboard_pageid']
            identities={(w['type'],w['name']):w['widgetid'] for w in p['widgets']}
            for w in summary['widgets']:
                if (w['type'],w['name']) in identities:w['widgetid']=identities[(w['type'],w['name'])]
            pages.append(summary)
        else:
            pages.append({k:p[k] for k in ['dashboard_pageid','name','display_period','widgets']})
    if not any(p['name']==DASHBOARD for p in pages):pages.append(summary)
    api.call('dashboard.update',{'dashboardid':main['dashboardid'],'pages':pages})
    after=api.call('dashboard.get',{'dashboardids':[main['dashboardid']],
        'output':'extend','selectPages':'extend','selectUsers':'extend','selectUserGroups':'extend'})[0]
    for p in main['pages']:
        if p['name']!=DASHBOARD:
            assert next(x for x in after['pages'] if x['dashboard_pageid']==p['dashboard_pageid'])==p,'Página anterior alterada'
    for key in ['userid','private','display_period','auto_start','users','userGroups']:
        assert after[key]==main[key], 'Configuração operacional alterada: '+key
    assert sum(p['name']==DASHBOARD for p in after['pages'])==1
    page=next(p for p in after['pages'] if p['name']==DASHBOARD)
    export=BASE/'dashboards';export.mkdir(exist_ok=True)
    (export/'gest-urtelecom-zte-resumo.json').write_text(json.dumps(
        {'dashboardid':main['dashboardid'],'page':page},ensure_ascii=False,indent=2)+'\n')
    return {'dashboardid':main['dashboardid'],'pageid':page['dashboard_pageid'],
        'name':page['name'],'widgets':len(page['widgets']),'page_count':len(after['pages']),
        'slideshow_period':after['display_period'],'backup':str(backup)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--apply',action='store_true',help='Cria ou atualiza o dashboard detalhado da OLT.')
    mode.add_argument('--main-page',action='store_true',help='Adiciona uma única página compacta ao dashboard GEST para o slideshow.')
    args=parser.parse_args()
    sys.path.insert(0,str(BASE.parent/'extension'))
    from client import API,load_config,secret_access
    cfg=load_config();api=API(cfg)
    api.auth=api.call('user.login',{'username':cfg['username'],'password':secret_access(cfg)}) if cfg['auth_mode']=='password' else secret_access(cfg)
    try:print(json.dumps((integrate_overview if args.main_page else configure)(api),ensure_ascii=False,indent=2))
    finally:
        if cfg['auth_mode']=='password':api.call('user.logout',[])

if __name__=='__main__':main()
