# Fail2Ban · duas VMs AtivBenefícios

O template **GEST - Fail2Ban Linux**, no grupo de templates **GEST**, monitora
o estado do serviço usando a chave personalizada `fail2ban.status`. Ele pode ser
usado com o agente clássico e com o Agent 2.

| Configuração | Valor |
| --- | --- |
| Nome do item | Fail2Ban · estado do serviço |
| Tipo | Zabbix agent, passivo |
| Chave | `fail2ban.status` |
| Tipo de informação | Numérico inteiro sem sinal |
| Intervalo | 30 segundos |
| Histórico / tendências | 7 dias / 90 dias |
| Mapeamento | `1` = Ativo; `0` = Inativo |
| Problema | Fail2Ban está inativo em `{HOST.NAME}` |
| Severidade | Alta |
| Confirmação | Dois minutos de leituras zero |
| Recuperação | Primeira leitura `1` |

O template está vinculado a **AtivBeneficios VM SistemaProd** (ID `10635`, agente
clássico) e **AtivBeneficios VM DBProd** (ID `10641`, Agent 2). Ele complementa os
templates GEST já existentes, preservando os itens, históricos e alertas de
comunicação dessas máquinas.

Em **25/11/2026**, as duas coletas foram conferidas no histórico do Zabbix:
valor **1 (Ativo)**, sem erro de item ou de trigger. Os IDs dos itens novos são
`113995` (sistema) e `113996` (banco); o template tem ID `10651`. Não foi preciso
interromper o Fail2Ban para validar a leitura.

## Agentes: diretório correto

O `UserParameter` é:

```ini
UserParameter=fail2ban.status,systemctl is-active --quiet fail2ban && echo 1 || echo 0
```

O arquivo deve ficar em um diretório carregado pela diretiva `Include=` do
agente. Na VM **ativ-site-beneficios**, o caminho foi conferido:

```ini
Include=/etc/zabbix/zabbix_agentd.conf.d/*.conf
```

Por isso, o arquivo do agente clássico fica em
`/etc/zabbix/zabbix_agentd.conf.d/fail2ban.conf`. Um arquivo somente em
`/etc/zabbix/zabbix_agentd.d/` não é carregado por essa configuração.

Após modificar o arquivo no servidor web:

```bash
sudo systemctl restart zabbix-agent
sudo -u zabbix zabbix_agentd -t fail2ban.status
```

Na VM **mysql**, o parâmetro foi instalado para o Agent 2 em
`/etc/zabbix/zabbix_agent2.d/fail2ban.conf`. Para conferir a configuração e testar:

```bash
grep -E '^[[:space:]]*Include=' /etc/zabbix/zabbix_agent2.conf
sudo -u zabbix zabbix_agent2 -t fail2ban.status
```

Ao atualizar o parâmetro do Agent 2, reinicie **zabbix-agent2**. Os comandos
`zabbix_agentd` e o serviço `zabbix-agent` pertencem ao agente clássico, não à
instalação Agent 2 do banco. Nenhum desses passos exige reiniciar o Fail2Ban ou
a VM, nem conceder sudo ao usuário `zabbix`.

O método usa os [UserParameters oficiais do Zabbix](https://www.zabbix.com/documentation/6.4/en/manual/config/items/userparameters).
Ele verifica apenas o estado do serviço, sem consultar jails, regras de firewall
ou a quantidade de IPs banidos.

## Regra de confirmação

```text
max(/GEST - Fail2Ban Linux/fail2ban.status,2m)=0
and count(/GEST - Fail2Ban Linux/fail2ban.status,2m)>=4
and last(/GEST - Fail2Ban Linux/fail2ban.status,#1:now-2m)=0
```

Além de verificar que todas as amostras na janela são zero, a regra exige pelo
menos quatro leituras e confere o início dos dois minutos. Isso evita disparar
no primeiro zero recebido logo após cadastrar o item. A recuperação usa
`last(/GEST - Fail2Ban Linux/fail2ban.status)=1`.

As funções estão descritas no [manual de funções de histórico](https://www.zabbix.com/documentation/6.4/en/manual/appendix/functions/history).
O intervalo de coleta e o processamento/envio da mídia podem acrescentar atraso
à confirmação. Sem leitura do agente, não se conclui que o Fail2Ban está parado;
os alertas existentes de comunicação continuam responsáveis por essa situação.

## Notificações e acompanhamento

As duas VMs pertencem ao grupo de hosts **ATIVBEneficios**. A ação existente
**Alerta Whatsapp ATIVBeneficios** está habilitada e seleciona esse grupo,
usando a mídia **WhatsappAtivDurvs**. Os novos problemas entram nesse filtro;
não foram alterados destinatários, tokens, mensagens ou ações.

Os incidentes também aparecem nos widgets de problemas do dashboard GEST,
incluindo as páginas individuais e a aba Servidores. Para ver o estado sem
esperar um problema, acesse **Monitoramento → Dados recentes**, filtre pelo
host e procure **Fail2Ban**.

## Exportar e reaplicar

O [YAML do template](templates/gest-fail2ban-linux.yaml) pode ser importado no
Zabbix 6.4. Não depende de uma base Linux específica e não contém credenciais.
O configurador usa a conexão administrativa já configurada no aplicativo:

```bash
python3 zabbix/configurar_fail2ban.py --apply
```

Por padrão, vincula às duas VMs AtivBenefícios. Para selecionar outros hosts:

```bash
python3 zabbix/configurar_fail2ban.py --apply --hostid ID_DO_HOST
```

É possível repetir `--hostid`. A chave deve ser validada em cada agente antes
da ativação. O script preserva os templates e IDs dos itens existentes, evita
duplicar o item/trigger e salva backup privado em
`~/.local/share/alert-zabbix/backups/fail2ban-before-*.json`.
