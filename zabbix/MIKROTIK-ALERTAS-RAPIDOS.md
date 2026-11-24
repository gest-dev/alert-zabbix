# MikroTik · Alertas rápidos

O template **GEST - MikroTik Alertas Rapidos** complementa os templates atuais dos **12 hosts habilitados do grupo Mikrotik**, incluindo UrTelecom, FlorestaTelecom e VillaNet. Os hosts Linux/ATIV e a OLT ZTE usam seus próprios perfis.

**FlorestaTelecom e UrTelecom:** os seis MikroTik desses provedores mantêm
gráficos e coleta de tráfego. Os alertas percentuais de banda ficam ativos
somente nas portas **SFP/SFP+/SFP28/QSFP**, identificadas pelos nomes SNMP
`sfp*` e `qsfp*`, com `ifType=6`. Nas portas de cobre `ether*`, inclusive ether8,
fica somente o alerta de perda de link. VLANs não geram alertas de banda ou link.
As regras de CPU, memória, disco, comunicação e latência continuam em vigor.

| Monitoramento | Critério de problema | Recuperação |
| --- | --- | --- |
| ICMP | Falhas por uma janela completa de 15 s | Respostas positivas estáveis por 30 s |
| Latência ICMP | Acima de 90 ms / 100 ms por 15 s | Abaixo de 80 ms por 30 s |
| Perda ICMP | Acima de 20% por 15 s, sem perda total | Abaixo de 10% por 30 s |
| SNMP | Nenhuma coleta do heartbeat por pelo menos 30 s | Retorno das coletas |
| CPU | Pelo menos um núcleo acima de 90% por 15 s | Todos abaixo de 80% por 30 s |
| Memória | Acima de 90% por 15 s | Abaixo de 85% por 30 s |
| Disco fixo | Acima de 80% / 90% por 15 s | Abaixo de 75% / 85% por 30 s |
| Porta | Administrativamente ativa, sem link por 15 s, após ter sido vista operante | Link estável por 30 s ou desativação administrativa |
| Banda, por direção, nas portas habilitadas | Queda de pelo menos 80% por 15 s, referência anterior acima de 100 Mb/s | Tráfego positivo por 30 s, acima de 70% da referência móvel, ou desativação administrativa |

As coletas de ICMP, CPU, disco, estado das portas e tráfego usam **5 s**. Os contadores de memória usam **10 s**, com cálculo percentual a cada 5 s. Os gatilhos conferem também uma amostra no início da janela, evitando confirmar 15 s de falha com apenas três amostras que abrangem dez segundos.

São janelas de confirmação. Timeout, execução de pollers e entrega por WhatsApp/Telegram acrescentam tempo. Em particular, `nodata()` tem período mínimo de 30 s e avaliação periódica no Zabbix 6.4: [documentação oficial](https://www.zabbix.com/documentation/6.4/en/manual/appendix/functions/history#nodata).

## Regra de banda

Na Floresta e UrTelecom, esta regra se aplica somente às portas SFP/QSFP.
Nos demais hosts, continua com o escopo original abaixo.

- Descobre Ethernet física (`ifType=6`), VLANs (`135/136`).
- Exclui interfaces individuais PPPoE e túneis. Não muda os intervalos dos milhares de contadores PPPoE existentes.
- Compara entrada e saída **separadamente**, evitando que tráfego na direção oposta esconda a queda.
- Usa a média dos cinco minutos encerrados **20 segundos antes** da avaliação. Isso separa a referência da janela da queda.
- Exige referência acima de **100.000.000 bps**, pelo menos 55 amostras nessa janela e queda de **80% ou mais por 15 segundos completos**.
- A macro `{$GEST.FAST.TRAFFIC.DROP}` vale **0.20**: é a fração restante do tráfego, não a porcentagem perdida. Exemplo: média de 1 Gb/s → alerta em 200 Mb/s ou menos, sustentados por 15 segundos.
- Aguarda a formação do histórico inicial; não alerta imediatamente após criar o item.
- O critério detecta anomalia. Variação de demanda também pode reduzir tráfego sem falha física.
- A referência é móvel e pode se adaptar ao novo patamar. Tráfego continuamente zerado não satisfaz a recuperação.

Os alertas de banda dependem do estado da porta e dos alertas de comunicação. Portas que já estavam sem uso no momento da descoberta não abrem um problema inicial: a regra exige que tenham sido vistas operantes na última hora. Depois de aberto, o problema permanece até a recuperação, mesmo após uma hora sem link.

## Floresta e UrTelecom: banda nas SFP; ether somente link

A política cobre Borda, Concentrador e a visão PPPoE de cada provedor, resolvidos
pelo nome e pelo vínculo ao perfil MikroTik rápido. A OLT ZTE continua usando
seu template próprio e não tinha alertas percentuais de banda para desativar.

Ficam ativos **96 gatilhos de variação de tráfego em SFP/QSFP**, correspondentes
a entrada e saída de 48 interfaces nas visões existentes. Permanecem desativados
**348 gatilhos percentuais de ether/VLANs** e **140 gatilhos de link de VLANs**,
mantendo **82 gatilhos de link Ethernet** e os **888 itens de interface**.
As contagens incluem as visões duplicadas de equipamentos existentes e não
representam necessariamente portas físicas únicas. Os históricos e gráficos
permanecem disponíveis, com a coleta de cinco segundos.

O link Ethernet continua exigindo 15 segundos sem operação, com a porta
administrativamente ativa e previamente vista operante na última hora.
Recupera após 30 segundos de link estável ou desativação administrativa.
As portas SFP/QSFP mantêm tanto o alerta de perda de link quanto o de banda.
O último segue a regra de 80% por 15 segundos, base acima de 100 Mb/s,
comparação com os cinco minutos anteriores e recuperação por 30 segundos.

As exceções de descoberta ficam no template compartilhado, com macros por host:

| Macro | Padrão do template | Floresta/UrTelecom |
| --- | --- | --- |
| `{$GEST.FAST.TRAFFIC.IFTYPE.MATCHES}` | `^(6\|135\|136)$` | `^6$` (banda somente em Ethernet física) |
| `{$GEST.FAST.TRAFFIC.IFNAME.MATCHES}` | `.*` | `^(sfp\|qsfp)` (banda somente nos nomes ópticos validados) |
| `{$GEST.FAST.LINK.IFTYPE.MATCHES}` | `^(6\|135\|136)$` | `^6$` (somente Ethernet gera alerta de link) |

As três exceções usam **Criar desabilitado** apenas para gatilhos. A porta
precisa satisfazer tanto o tipo quanto o nome permitidos para alertar por banda.
Se uma SFP for renomeada sem esse prefixo, ajuste também o filtro por nome.
Não excluem itens
ou interfaces da descoberta. O padrão conserva o comportamento dos outros
provedores. A configuração foi verificada também depois de solicitar uma nova
descoberta; detalhes da API estão na
[documentação de overrides](https://www.zabbix.com/documentation/6.4/en/manual/api/reference/discoveryrule/object#lld-rule-override-operation-status).

Para reaplicar a política sem alterar as coletas:

```bash
python3 zabbix/configurar_portas_floresta_ur.py --apply
```

O [configurador](configurar_portas_floresta_ur.py) usa a conexão do aplicativo,
salva backup privado `floresta-ur-port-policy-before-*.json`, preserva macros
alheias e confere os estados dos alertas dos demais hosts. A aplicação geral
do perfil rápido chama essa política ao final para conservar as exceções.

## Configuração e aplicação

As macros `{$GEST.FAST.*}` ficam no novo template. Os nomes e as margens de recuperação documentados correspondem à configuração aplicada; ajuste também as descrições e margens se alterar limites.

O template utiliza a interface SNMP já cadastrada em cada host, incluindo portas alternativas. Não contém IPs nem comunidades. As coletas de CPU são compartilhadas entre os núcleos; a descoberta de interfaces ocorre a cada hora e trata linhas incompletas de sessões removidas durante a consulta.

Em alguns casos, o host principal e a visão PPPoE usam o mesmo equipamento/IP/porta. O perfil foi vinculado aos 12 hosts solicitados, mantendo essas visões existentes; eventos de saúde podem ocorrer em ambos os nomes. Quando vários equipamentos usam NAT no mesmo IP público, ICMP testa o IP da borda, enquanto SNMP testa a porta específica de cada host.

Arquivos:

- [Template exportado para Zabbix 6.4](templates/gest-mikrotik-alertas-rapidos.yaml).
- [Script de aplicação e validação](configurar_mikrotik_rapido.py), que usa a conexão configurada no aplicativo, sem credenciais no código.

```bash
# Aplica o perfil adicional e preserva os vínculos atuais.
python3 zabbix/configurar_mikrotik_rapido.py --apply

# Após formar histórico e descobrir portas, valida as coletas.
# Só então desativa os alertas antigos equivalentes nos hosts atendidos.
python3 zabbix/configurar_mikrotik_rapido.py --finalize
```

A aplicação cria backups privados em `~/.local/share/alert-zabbix/backups/`. O passo de finalização não desativa alertas se houver erro de coleta/descoberta/gatilho, falta de portas/discos ou problemas antigos ainda abertos. Ele preserva alertas de temperatura, reinício, firmware e demais funções dos templates originais.

## Validação e reversão

A aplicação foi conferida pela API com dados reais dos 12 hosts: CPU, memória, discos, interfaces, estado SNMP e expressões dos gatilhos. As janelas e o tratamento da descoberta também foram verificados com dados sintéticos locais. Não houve bloqueio de IP, interrupção de rede ou envio manual de notificações para testar este perfil.

Para reverter, restaure os campos `status` dos gatilhos e protótipos a partir do backup `mikrotik-legacy-status-before-*.json`, **antes** de desvincular o perfil rápido. Para remover seus itens e gatilhos, use a opção de desvincular e limpar apenas o novo template; isso também remove o histórico desses itens adicionais. Os templates e históricos anteriores foram preservados.
