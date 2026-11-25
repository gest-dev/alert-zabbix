# VM uiluolt · padrão GEST

O host **uiluolt** (`172.16.0.100`, ID `10649`) usa o template
**GEST-cpu-hd-uiluolt**, do grupo **GEST**. Ele herda **Linux by Zabbix agent**
e acrescenta as regras GEST de disco, comunicação e disponibilidade dos serviços
encontrados nessa VM Debian 12. O agente instalado é o **Agent 2 6.4.21**.
O host pertence aos grupos **GEST**, **Linux servers** e **Virtual machines**.
O grupo de hosts GEST é independente do grupo GEST usado para organizar templates.

## O que é monitorado

| Componente | Verificação |
| --- | --- |
| Sistema operacional | CPU, memória, swap, sistemas de arquivos, inodes, disco, interfaces e uptime pela base Linux |
| Disco `/` | Capacidade, uso percentual, espaço usado e espaço livre disponível |
| Comunicação do agente | Porta TCP 10050 consultada pelo servidor Zabbix a cada 5 segundos |
| Aplicação uiluolt | Processo específico `build/bin/server.js` e porta TCP da aplicação, atualmente 3333 |
| PM2 | Estado da unidade `pm2-root.service` |
| MongoDB | Estado de `mongod.service` e disponibilidade TCP local da porta 27017, sem usuário de banco |
| GenieACS | Estado individual dos serviços CWMP, FS, NBI e UI |
| OpenVPN | Estado das duas unidades existentes: servidor principal e RouterOS 6 |

As verificações systemd usam `systemd.unit.info[...,ActiveState]`, disponível no
[Agent 2 para Linux](https://www.zabbix.com/documentation/6.4/en/manual/config/items/itemtypes/zabbix_agent/zabbix_agent2).
Estados `active` e `reloading` são considerados disponíveis. A contagem da
aplicação usa o caminho específico do processo para evitar que outro Node.js
mascare sua parada. Não há verificações de Nginx ou PHP nessa VM.

## Alertas

| Situação | Confirmação | Recuperação |
| --- | --- | --- |
| Disco com pelo menos 90% de uso | Três coletas consecutivas; severidade Atenção | Abaixo de 88% |
| Disco com pelo menos 95% de uso | Três coletas consecutivas; severidade Alta | Abaixo de 93% |
| Porta do agente indisponível | 1 minuto de falha; coleta a cada 5 segundos | 30 segundos estáveis |
| Processo, porta da aplicação, MongoDB ou serviço parado | 1 minuto de falha; coleta a cada 15 segundos | 30 segundos estáveis |

O aviso de disco depende do alerta crítico para reduzir duplicidade. As regras
GEST usam **somente o percentual**, sem exigir espaço absoluto ou previsão de
esgotamento. Os dois alertas nativos de disco e o alerta nativo de disponibilidade
do agente foram desativados apenas na ramificação GEST deste host, para evitar
alertas duplicados. CPU, memória e as demais regras Linux mantêm seus critérios
da base, como no template do servidor AtivBenefícios.

As janelas de comunicação e serviços conferem também a amostra no início do
período, evitando confirmar estabilidade com uma única leitura. A confirmação
de 1 minuto é a avaliação da trigger; coleta, processamento e entrega da mídia
podem acrescentar atraso. A configuração de destinatários e ações permanece a
do Zabbix.

Estado de processo, porta e unidade systemd não confirma operações internas do
sistema, consultas ao MongoDB, provisionamento de OLTs ou sessões conectadas nas
VPNs. A resposta HTTP da aplicação foi conferida durante a implantação, mas
este template não executa um cenário HTTP periódico.

## Configurar e reaplicar

No Zabbix, acesse **Dados coletados → Templates → GEST-cpu-hd-uiluolt**.
Os padrões ficam na aba **Macros**; para personalizar uma máquina, defina a
macro na aba **Macros** do próprio host.

| Macro | Padrão | Uso |
| --- | --- | --- |
| `{$GEST.FS.PUSED.WARN}` / `{$GEST.FS.PUSED.CRIT}` | `90` / `95` | Limites de ocupação |
| `{$GEST.FS.PUSED.WARN.RECOVERY}` / `{$GEST.FS.PUSED.CRIT.RECOVERY}` | `88` / `93` | Margens de recuperação |
| `{$GEST.AGENT.PORT}` | `10050` | Porta do agente |
| `{$GEST.AGENT.CHECK.INTERVAL}` | `5s` | Coleta de conectividade TCP do agente |
| `{$UILUOLT.INTERVAL}` | `15s` | Coleta dos serviços |
| `{$UILUOLT.APP.PORT}` | `3333` | Porta da aplicação |
| `{$UILUOLT.MONGODB.PORT}` | `27017` | Porta local do MongoDB |
| `{$UILUOLT.PROCESS.MATCHES}` | Caminho do processo Node.js | Expressão regular da aplicação |
| `{$UILUOLT.SERVICE.*}` | Unidades verificadas na VM | Nome de cada serviço systemd |

O [YAML exportado](templates/gest-cpu-hd-uiluolt.yaml) depende da base oficial
**Linux by Zabbix agent** já instalada. Após importar, reaplique os ajustes de
status herdados com a conexão administrativa configurada no aplicativo:

```bash
python3 zabbix/configurar_template_uiluolt.py --apply
```

O configurador reutiliza os scripts de disco e conexão GEST e salva backups
privados em `~/.local/share/alert-zabbix/backups/`. A migração desvincula a base
direta **sem limpar** antes de vincular a ramificação GEST, preservando os IDs e
históricos dos itens. Não muda o template oficial nem os outros hosts.
O script e o YAML não contêm senha de SSH, API ou banco.

## Dashboard e validação

A aba **uiluolt** continua no dashboard
**[GEST · Operação e servidores](http://172.16.0.4/zabbix/zabbix.php?action=dashboard.view&dashboardid=1)**,
com os mesmos 12 widgets. Sua configuração está em [DASHBOARD.md](DASHBOARD.md#vm-uiluolt).
Os novos eventos de serviços aparecem no widget de problemas dessa VM.
O host também está nos comparativos da **Visão geral** e de **Servidores**
(disco usado/livre, CPU e memória), nos dois gráficos comparativos e no filtro
de problemas dos servidores. Para reaplicar esses vínculos e o grupo GEST:

```bash
python3 zabbix/configurar_servidores_uiluolt.py --apply
```

A implantação preservou os 86 IDs de itens existentes e o dashboard completo.
As 12 verificações novas de serviços e conexão retornaram disponíveis, sem itens
ativos não suportados. Os alertas de disco foram encontrados com limites
efetivos de 90%/95%, e os alertas nativos de disco e agente da base Linux
continuaram habilitados para suas outras ramificações. Nenhum serviço foi
interrompido para simular falha.
