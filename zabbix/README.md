# Templates de disponibilidade para Zabbix 6.4

O arquivo [gest-monitoramento-web-icmp.yaml](templates/gest-monitoramento-web-icmp.yaml)
contém dois templates do grupo **GEST**:

| Template | Verificações |
| --- | --- |
| GEST - Site HTTPS e Ping | URL do site/front e ICMP da interface principal do host |
| GEST - API HTTPS | Uma URL adicional para a API, com alerta independente |

O template principal serve para aplicações com um site. Vincule também o complemento
quando a aplicação tiver uma API separada. Os templates não contêm IPs de servidores,
URLs de clientes ou credenciais.

A integração de notificações **WhatsappAtivDurvs** está documentada em
[media/README.md](media/README.md), com script reutilizável e token em macro
secreta, fora do código.

## Usar em um novo host

1. Em **Coleta de dados → Templates → Importar**, importe o YAML. Os templates
   também podem ser exportados diretamente pela interface do Zabbix.
2. Crie um host habilitado no grupo apropriado. Para ICMP, informe o IP/DNS na
   interface principal do tipo Agente; não é necessário instalar um agente para
   esses testes, pois as verificações são feitas pelo servidor/proxy Zabbix.
3. Vincule **GEST - Site HTTPS e Ping**. Se houver API separada, vincule também
   **GEST - API HTTPS**.
4. Na aba **Macros** do host, configure:

| Macro | Uso | Padrão |
| --- | --- | --- |
| `{$SERVICE.NAME}` | Nome do serviço nos alertas e nas tags | `Aplicação` |
| `{$WEB.URL}` | URL completa do site/front, incluindo `https://` | Vazio; preencher ao usar o template principal |
| `{$WEB.LABEL}` | Nome do componente no alerta: `site` ou `front` | `site` |
| `{$API.URL}` | URL completa da API, incluindo `https://` | Vazio; preencher ao usar o complemento de API |
| `{$MONITOR.INTERVAL}` | Intervalo de coleta HTTP e ICMP | `1m` |
| `{$MONITOR.TIMEOUT}` | Timeout de cada etapa HTTP | `15s` |

As macros pertencem ao host. Para mudar um endereço, edite a macro desse host;
para alterar o padrão compartilhado, edite o template no Zabbix e exporte o YAML
novamente. O ping usa a interface do host e permanece independente das URLs, mesmo
quando o domínio resolve para IPs diferentes.

## Critérios dos alertas

- HTTP: exige status **200** após seguir redirecionamentos e valida o certificado TLS.
- ICMP: retorna `1` quando há resposta e `0` quando não há resposta.
- Cada verificação abre um problema de severidade **Alta** após **três falhas
  consecutivas** e recupera na primeira coleta bem-sucedida.
- Não há dependência entre os alertas de site, API e ping: uma falha de ICMP não
  oculta uma falha HTTP, e vice-versa.
- A verificação HTTP confirma a resposta da URL. Não executa JavaScript, login
  ou operações internas da aplicação.

O aplicativo Alertas Zabbix continua consultando somente os problemas atuais de
hosts habilitados. Importar estes templates não altera as credenciais do aplicativo.

## Incorporar verificações já existentes

O Zabbix pode incorporar entidades existentes ao vincular templates. Para preservar
os IDs e o histórico, os cenários e etapas precisam corresponder aos do template,
os itens precisam ter as mesmas chaves e as triggers precisam ter os mesmos nomes
e expressões. Exporte a configuração antes de uma migração e confira os IDs depois.
Não exclua itens ou cenários para resolver conflitos de vínculo.

Nesta implantação, a migração foi primeiro validada em um host temporário
desabilitado, removido ao concluir o teste. Nos dois hosts existentes foram
preservados **20 itens, 3 cenários, 3 etapas e 5 triggers**, com suas identidades
originais. As configurações específicas e os registros de migração ficam fora do
projeto, em `~/.local/share/alert-zabbix/backups/`.

Referências: [vínculo de templates](https://www.zabbix.com/documentation/6.4/en/manual/config/templates/linking)
e [monitoramento web](https://www.zabbix.com/documentation/6.4/en/manual/web_monitoring).

## Servidor Linux do banco de dados

O arquivo [gest-banco-linux-ping.yaml](templates/gest-banco-linux-ping.yaml) contém
o template **GEST - Banco Linux e Ping**. Ele herda **Linux by Zabbix agent**,
que precisa existir no Zabbix, e acrescenta ICMP a cada minuto, com alerta após
três falhas consecutivas e recuperação na primeira resposta válida.

Configure a interface principal do host com o IP do servidor e a porta TCP 10050.
O agente precisa permitir as consultas do servidor/proxy Zabbix e a conexão deve
estar liberada na rede. Instalar o Agent 2 não conclui essa configuração.
O template acompanha o sistema operacional e o ping; métricas internas do MySQL
exigem configurar uma conta própria de monitoramento e o template MySQL adequado.

## CPU, discos e disponibilidade do MySQL

O arquivo [gest-cpu-hd-mysql.yaml](templates/gest-cpu-hd-mysql.yaml) exporta o
template **GEST-cpu-hd-mysql** e sua base **GEST - Banco Linux e Ping**, no grupo
**GEST**. O template oficial **Linux by Zabbix agent** precisa existir antes de
importar em outro Zabbix 6.4.

O template herda CPU, carga, memória, swap, espaço livre e inodes dos sistemas de
arquivos, desempenho de discos, rede, disponibilidade do agente e ICMP. As
descobertas Linux acrescentam os itens de cada disco, sistema de arquivos e
interface. O limite herdado de CPU é 90%. Para espaço em disco, o template GEST
usa as regras próprias descritas abaixo: aviso a partir de 90% e alerta alto
a partir de 95%, sem depender de um segundo critério de espaço livre absoluto
ou previsão de esgotamento.

Para saber se o MySQL está rodando, acrescenta três itens nativos do agente:

| Item | Verificação |
| --- | --- |
| `proc.num[mysqld]` | Quantidade de processos do MySQL |
| `proc.num[mariadbd]` | Quantidade de processos do MariaDB, como alternativa |
| `net.tcp.service[tcp,{$MYSQL.HOST},{$MYSQL.PORT}]` | Conexão TCP local com o serviço: 1 disponível, 0 indisponível |

Não exige usuário, senha ou permissões SQL. O agente verifica os processos e a
porta no próprio servidor do banco; a porta 3306 não precisa ficar exposta à
internet. O teste TCP confirma que a porta aceita conexão, sem autenticar ou
executar consultas SQL.

| Macro | Padrão | Uso |
| --- | --- | --- |
| `{$MYSQL.HOST}` | `127.0.0.1` | Endereço do MySQL acessível localmente pelo agente |
| `{$MYSQL.PORT}` | `3306` | Porta local do MySQL/MariaDB |
| `{$MYSQL.INTERVAL}` | `1m` | Intervalo de coleta dos três itens |

As macros podem ser sobrescritas no host. O template gera alerta **Alto** após
três verificações consecutivas sem nenhum processo `mysqld` ou `mariadbd`, ou
sem conexão na porta configurada. Recupera na primeira coleta válida. O alerta
de porta depende do alerta de processo para evitar duas notificações para a
mesma parada. Os alertas Linux e ICMP continuam herdados.

O item adicional `vfs.fs.size[/,free]` coleta o espaço livre disponível no disco
raiz, em bytes, para os cartões do dashboard. O estado da porta MySQL usa o
mapeamento **GEST - Disponibilidade MySQL**, com os textos **Disponível** e
**Indisponível**; os valores numéricos e as expressões de alerta são preservados.

### Notificações de ocupação do disco

Os alertas usam os itens de ocupação dos sistemas de arquivos já descobertos,
sem duplicar sua coleta ou alterar o template oficial Linux. As regras antigas
de pouco espaço são desativadas somente no template GEST e nos seus hosts, para
evitar alertas duplicados com critérios diferentes. As outras verificações de
disco, como inodes, latência e sistema de arquivos somente para leitura, continuam
herdadas.

| Macro | Padrão | Comportamento |
| --- | --- | --- |
| `{$GEST.FS.PUSED.WARN}` | `90` | Abre aviso de severidade Atenção após três coletas consecutivas com ocupação maior ou igual ao limite |
| `{$GEST.FS.PUSED.CRIT}` | `95` | Abre problema de severidade Alta após três coletas consecutivas com ocupação maior ou igual ao limite |
| `{$GEST.FS.PUSED.WARN.RECOVERY}` | `88` | Recupera o aviso quando o uso cai abaixo deste percentual |
| `{$GEST.FS.PUSED.CRIT.RECOVERY}` | `93` | Recupera o alerta alto quando o uso cai abaixo deste percentual |

Com a coleta padrão de um minuto, três amostras correspondem a aproximadamente
dois a três minutos de uso elevado. As margens de recuperação evitam alternância
de notificações perto do limite. O aviso depende do alerta alto para evitar
abrir um aviso novo quando o problema já estiver no nível alto.

No servidor configurado, as ações existentes de Telegram e WhatsApp estão
habilitadas e aceitam essas severidades. O aplicativo também inclui ambos os
níveis com o filtro atual. A configuração foi conferida sem gerar eventos falsos
ou enviar mensagens de teste aos destinatários.

O exportador do Zabbix 6.4 omite protótipos locais adicionados a uma regra de
descoberta herdada e ajustes de status herdados. Por isso, **após importar o YAML
em outro servidor**, aplique também o configurador administrativo:

```bash
python3 zabbix/configurar_alertas_disco.py
```

Execute a partir da pasta do projeto, com a conexão do aplicativo configurada
para o Zabbix de destino e uma conta com permissão para alterar templates e
hosts. O script encontra as entidades pelo nome e pelas chaves, mantém os IDs
existentes ao ser executado novamente e cria uma cópia privada antes das mudanças.
Ele aplica os padrões acima; sobrescritas específicas nas macros dos hosts são
preservadas. Não altera ações, destinatários ou templates Linux compartilhados.

Para usar em um servidor já vinculado à base, substitua o vínculo direto por
**GEST-cpu-hd-mysql**, desvinculando sem limpar os itens. A base permanece
herdada pelo novo template. Não use **Desvincular e limpar**, pois isso elimina
os itens e o histórico. A mudança de herança foi validada em um host temporário
desabilitado, removido ao concluir o teste, e os IDs dos itens existentes foram
conferidos na aplicação ao host de produção.

Referência: [itens nativos do agente no Zabbix 6.4](https://www.zabbix.com/documentation/6.4/en/manual/config/items/itemtypes/zabbix_agent).

## Dashboard operacional

O painel **GEST · Operação e servidores** usa widgets nativos do Zabbix 6.4,
com comparação de capacidade e páginas separadas por host. A organização
e os cuidados de manutenção estão em [DASHBOARD.md](DASHBOARD.md).

## Servidor web: CPU, disco, Nginx e PHP

O arquivo [gest-cpu-hd-nginx-php.yaml](templates/gest-cpu-hd-nginx-php.yaml)
contém o template **GEST-cpu-hd-nginx-php**, no grupo **GEST**. Ele herda o
template oficial **Linux by Zabbix agent** para CPU, memória, discos, rede e
disponibilidade do agente, e acrescenta:

| Item | Verificação |
| --- | --- |
| `vfs.fs.size[/,free]` | Espaço livre disponível no sistema de arquivos raiz |
| `proc.num[nginx]` | Quantidade de processos Nginx |
| `proc.num[,,,"{$PHP.FPM.PROCESS.MATCHES}"]` | Quantidade de processos PHP-FPM, com filtro configurável |

Os processos são apresentados como **Parado** quando a contagem é zero e
**Rodando** quando há pelo menos um processo. Nginx e PHP-FPM geram problemas
de severidade **Alta** após três coletas consecutivas sem processo e recuperam
na primeira coleta em que o processo volta. O intervalo padrão é um minuto,
configurável por `{$WEB.SERVICE.INTERVAL}`.

`{$PHP.FPM.PROCESS.MATCHES}` contém por padrão
`(^|/)php-fpm([0-9.]+)?(:|[[:space:]]|$)`, abrangendo PHP-FPM com e sem número de
versão no nome. Confirme o runtime real antes de vincular o template: PHP via
CLI, Apache, FrankenPHP ou outro modelo precisa de uma verificação apropriada.
O monitoramento por processo confirma que o serviço está rodando; o cenário
HTTPS existente complementa essa verificação com a resposta da aplicação.

Não exige banco de dados, conta SQL, endpoint público de status ou parâmetros
remotos de execução de comandos. Não inclui MySQL nem acrescenta ICMP; mantenha
o vínculo existente **GEST - Site HTTPS e Ping** para preservar site e ping.
A combinação dos dois templates foi validada em um host temporário desabilitado,
com preservação dos sete itens web/ICMP existentes e sem chaves MySQL.

### Ativar no host de produção

1. Instale e configure o Zabbix agent ou Agent 2 conforme a distribuição do
   servidor. Se já houver um agente compatível, valide os itens antes de
   substituí-lo. Confirme que está ativo e escutando na porta TCP 10050.
2. Inclua em `Server=` a origem fixa do servidor/proxy Zabbix pela VPN, mantendo
   outras origens necessárias na mesma diretiva. Libere TCP 10050 para essa
   origem nos firewalls do sistema e da hospedagem.
3. Valide consultas reais de `agent.ping`, `system.cpu.util`, `proc.num[nginx]`
   e da chave PHP-FPM a partir do servidor Zabbix.
4. Acrescente **GEST-cpu-hd-nginx-php** aos templates do host, preservando os
   vínculos web existentes, sem desvincular e limpar itens.
5. Aplique também os alertas de disco à descoberta herdada:

   ```bash
   python3 zabbix/configurar_alertas_disco.py --template GEST-cpu-hd-nginx-php
   ```

O configurador administrativo mantém o template de banco como destino padrão;
`--template` permite aplicar a mesma política ao template web. Os limites são
90% para aviso e 95% para alerta alto, por três coletas consecutivas, com
recuperação abaixo de 88% e 93%, respectivamente. Como no template de banco,
o exportador nativo 6.4 omite esses ajustes locais em descoberta herdada;
execute o configurador após uma importação.

O template pode ficar preparado no Zabbix enquanto o acesso ao agente é
resolvido. Só considere o monitoramento interno ativo após confirmar valores
recentes nos itens do host. HTTP e ping continuam independentes dessa preparação.

A ativação no host AtivBenefícios foi conferida com o agente clássico 5.0.47
já instalado, sem substituí-lo: CPU, espaço livre e percentual de uso do disco,
Nginx e PHP-FPM receberam amostras recentes no Zabbix. A página
**AtivBenefícios · Web** e os comparativos de servidores usam esses itens.

## VPN do servidor e acesso aos agentes

O [registro da VPN L2TP/IPsec](VPN.md) documenta a separação da porta UDP de origem
do Zabbix para clientes atrás do mesmo NAT, o procedimento de recuperação e os
testes de acesso aos agentes. A configuração é administrativa e fica na VM;
não é aplicada pelo instalador do aplicativo nem pelos templates.

## Confirmação de falha e recuperação da conexão com o agente

Os templates **GEST-cpu-hd-mysql** e **GEST-cpu-hd-nginx-php** acrescentam a
verificação simples `net.tcp.service[tcp,,{$GEST.AGENT.PORT}]`, executada pelo
servidor/proxy a cada **5 segundos**.

Em **19/11/2026**, o alerta foi ajustado para reduzir notificações durante
oscilações da VPN:

| Condição | Confirmação exigida |
| --- | --- |
| Abrir o problema de conexão | **1 minuto** de falhas observadas, sem resposta positiva na janela |
| Encerrar o problema | **30 segundos** de respostas positivas estáveis, sem falha na janela |

As expressões usam `max(...,1m)=0` para falha e `min(...,30s)=1` para recuperação,
com conferência adicional do último valor anterior ao início de cada janela
(`last(...,#1:now-1m)` e `last(...,#1:now-30s)`). Isso evita confirmar uma janela
completa a partir de uma única amostra após um intervalo sem coleta. A primeira
resposta positiva já deixa a condição de problema falsa, mas o evento continua
aberto até a confirmação da recuperação. Uma nova falha reinicia a espera por
estabilidade.

O tempo é contado pelos horários das amostras recebidas, não pela quantidade de
checagens. A próxima coleta, os timeouts, o processamento e a fila do mensageiro
podem acrescentar atraso; esses tempos não são garantia de entrega da mensagem.
Sem novas amostras, esta regra não substitui uma verificação própria de ausência
de dados.

Antes desse ajuste, o alerta abria após cinco falhas e encerrava na primeira
resposta positiva. O teste de 17/11/2026 confirmou a regra anterior em 24 segundos
no servidor web e 27 segundos no banco; esses resultados não validam os tempos
atuais. A evidência histórica permanece no backup privado
`vpn-fast-notification-test-*.json`, fora do projeto.

Essa checagem confirma que a porta TCP aceita conexão. Não comprova a execução
das métricas ou o funcionamento de Nginx, PHP e MySQL, que têm verificações
próprias. A disponibilidade padrão do agente continua sendo coletada para o
estado da interface; seu alerta de três minutos é desativado somente nos dois
templates GEST e nos respectivos hosts para evitar notificações duplicadas.
O template Linux oficial e os demais hosts não são alterados.

| Macro | Padrão | Uso |
| --- | --- | --- |
| `{$GEST.AGENT.PORT}` | `10050` | Porta TCP do agente |
| `{$GEST.AGENT.CHECK.INTERVAL}` | `5s` | Frequência das checagens; não define sozinha o tempo de confirmação |

Após importar os templates, aplique também o estado do alerta herdado, omitido
pelo exportador nativo 6.4:

```bash
python3 zabbix/configurar_alerta_agente_rapido.py
```

O nome do arquivo foi preservado para manter os comandos existentes. Use
`--template NOME` para restringir a aplicação a um template. O configurador é
administrativo e usa a conexão salva do aplicativo; faz backup com permissão
600 fora do projeto antes de alterar a configuração. Os backups incluem as
expressões de problema e recuperação. Somente as macros desta verificação são
atualizadas; as demais, inclusive secretas, são preservadas. Os alertas de CPU,
disco, serviços, HTTPS e ICMP mantêm suas regras próprias.

Referências: [verificações simples](https://www.zabbix.com/documentation/6.4/en/manual/config/items/itemtypes/simple_checks),
[funções de histórico](https://www.zabbix.com/documentation/6.4/en/manual/appendix/functions/history)
e [condição adicional de recuperação](https://www.zabbix.com/documentation/6.4/en/manual/config/triggers/expression).
