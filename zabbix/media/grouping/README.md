# Agrupamento somente na entrega de mensagens

O serviço reúne notificações por **30 segundos**, em janelas contadas a partir
da primeira mensagem. Agrupa separadamente por mídia e destinatário, com lotes
próprios para problemas, recuperações e atualizações. Cada mensagem recebe um
cabeçalho com a quantidade de alertas e a numeração das partes.

**As telas do aplicativo e os dashboards permanecem iguais.** O serviço não
acessa a API do Zabbix, não fecha eventos e não altera triggers, correlações,
hosts ou filtros. O configurador administrativo altera somente os scripts e os
parâmetros dos quatro tipos de mídia existentes e cria uma macro secreta para
autenticar a fila local. Mantém seus IDs, ações, usuários e destinatários.

## Formatos e limites

| Mídia existente | Entrega ao serviço original |
| --- | --- |
| `WhatsappAtivDurvs` | POST com `text` e `id`, token Bearer, campos Nome do Processo/Tipo do Erro/Descrição do Erro |
| `WhatsappAstro` | POST com `id`, `message` e `group`, token Bearer; mantém o `Id` configurado na mídia |
| `WhatsApp Ur Telecom` | Mesmo contrato Astro, mantendo o seu próprio `Id` |
| `TelegramHome` | `sendMessage` com o mesmo bot e `chat_id`; conserva o texto visível de HTML e os endereços dos links |

O Telegram é entregue como texto simples para evitar tags HTML incompletas ao
dividir mensagens. O conteúdo visível é mantido, mas negrito e outras marcações
HTML deixam de ser aplicados. Os WhatsApps mantêm seus textos originais dentro
do resumo. Um único alerta também aguarda a janela e recebe cabeçalho.

Cada parte tem, por padrão, até **3.500 unidades UTF-16**, incluindo o cabeçalho.
A divisão preserva caracteres inteiros, incluindo emojis, e prefere quebras de
linha. Alertas individuais maiores também são divididos, sem truncar o texto.
O limite pode ser reduzido por rota em `service-config.json` antes de instalar,
se o provedor WhatsApp exigir um valor menor. O máximo aceito é 4.096.

O consumidor mantém pelo menos 3,1 segundos entre partes para um destino do
Telegram e 1,1 segundo nos serviços WhatsApp. Respeita `retry_after` do Telegram
quando o HTTP retorna 429 e adia novas tentativas após falhas. Grandes volumes
e indisponibilidade do provedor podem acrescentar espera além dos 30 segundos.

## Persistência e significado do sucesso

O webhook faz POST somente para `http://127.0.0.1:8791/enqueue`, autenticado pela
macro secreta `{$NOTIFY.GROUP.TOKEN}`. O HTTP 202 só é devolvido após a gravação
no SQLite. Não há envio direto alternativo se a fila não confirmar a gravação;
o erro é devolvido ao Zabbix, que usa as tentativas configuradas na mídia.

**Um envio marcado como bem-sucedido pelo Zabbix passa a significar aceitação
pela fila**, e não entrega ao WhatsApp/Telegram. O consumidor registra as
entregas e as falhas no journal, sem texto, destinatários ou credenciais. Falhas
de entrega ficam persistidas para novas tentativas, sem prazo de descarte.
As partes já confirmadas são removidas individualmente e não são reenviadas
quando uma parte posterior falha. Se o provedor aceitar uma mensagem e a
conexão cair antes da confirmação, uma nova tentativa pode repetir essa parte.

A configuração e o SQLite contêm segredos e conteúdo de alertas. Ficam fora
da pasta pública e do repositório: configuração em `/etc/zabbix/message-group.json`
com modo 0640 e banco em `/var/lib/zabbix-message-group/` com diretório 0700.
O serviço só aceita conexões em loopback e só entrega aos endpoints fixados na
configuração. Não segue redirecionamentos HTTP.

## Instalação e ativação

Use a conexão administrativa do aplicativo neste computador. O configurador
foi preparado para Zabbix 6.4 e exige as quatro mídias acima habilitadas.

1. Prepare um pacote em uma **pasta privada nova**, fora da raiz web:

   ```bash
   python3 zabbix/configurar_agrupamento.py --prepare /tmp/zabbix-message-group-package
   ```

   Esta etapa apenas consulta a configuração. O pacote contém a chave nova,
   os arquivos do serviço, o plano e o backup das mídias originais; não o
   versione nem o coloque em uma pasta servida pelo nginx/Apache.

2. Transfira o pacote preservando suas permissões para o servidor do Zabbix.
   No servidor, execute como root:

   ```bash
   python3 /tmp/zabbix-message-group-package/install.py \
     --config /tmp/zabbix-message-group-package/service-config.json
   ```

   A instalação exige Python 3.9 ou superior, systemd e o usuário `zabbix`.
   Inicia o serviço `zabbix-message-group` e confere sua saúde. Ainda não altera
   mídias nem envia mensagens. Uma cópia privada dos arquivos de recuperação
   é criada em `/var/backups/zabbix-message-group/`.

3. Neste computador, ative o plano após a instalação:

   ```bash
   python3 zabbix/configurar_agrupamento.py \
     --apply /tmp/zabbix-message-group-package --ssh root@SERVIDOR
   ```

   O SSH usa chave ou conexão autenticada existente; aceite também
   `--ssh-port PORTA` e `--ssh-control-path SOCKET`. A verificação de saúde envia
   a chave no stdin, sem colocá-la em argumentos do processo. O configurador
   confere a configuração da fila e detecta mudanças manuais nas mídias antes
   de alterá-las. Em uma falha parcial da API, tenta restaurar as mídias que
   acabou de modificar. Não executa o botão Testar nem gera eventos falsos.

4. Acompanhe o serviço e os alertas naturais:

   ```bash
   systemctl status zabbix-message-group
   journalctl -u zabbix-message-group --since '10 minutes ago'
   ```

   `/health` exige o mesmo Bearer da fila e retorna o estado do consumidor,
   a impressão digital da configuração e as contagens `incoming` e `outbox`.
   Uma fila pendente significa que há mensagens aguardando janela, entrega
   ou nova tentativa. Reiniciar o serviço preserva essas mensagens.

Para voltar ao envio direto, mantenha o serviço ativo, espere a fila esvaziar e
execute `--restore PACOTE --ssh root@SERVIDOR`. O configurador só restaura mídias
que ainda correspondam ao plano, e recusa a restauração com mensagens pendentes.
Depois da restauração, o serviço pode ser desabilitado. Preserve o pacote privado
original para futuras verificações ou restaurações.

## Validação sem mensagens reais

```bash
node --test zabbix/media/grouped-delivery.test.mjs zabbix/media/whatsapp-ativ-durvs.test.mjs
python3 -m unittest discover -s zabbix/media/grouping -p 'test_*.py' -v
```

Os testes substituem os provedores por simuladores. Conferem janela fixa,
isolamento de destinatários e estados, reinício com mensagens pendentes,
repetição de partes que falharam, limites com emojis, formatos de cada serviço,
autenticação HTTP e escopo das alterações administrativas.

## Implantação de 25/11/2026

Agrupamento ativado nas quatro mídias existentes, com janela de 30 segundos e
limite de 3.500 unidades por parte. O serviço foi instalado e habilitado no
servidor do Zabbix. Foram aprovados 19 testes Python e 31 testes JavaScript;
os 13 testes do consumidor também passaram com o Python 3.9 do servidor.

Os quatro webhooks foram executados pelo próprio Zabbix usando uma rota
inexistente e credenciais fictícias do provedor. A fila rejeitou todas essas
requisições com HTTP 400, validando a execução e a comunicação local sem
enfileirar ou entregar mensagens. Ao concluir, a fila estava saudável e vazia.
As configurações de dashboards e ações foram comparadas antes e depois e
permaneceram idênticas. A entrega aos provedores será observada nos alertas
naturais seguintes; não foram enviadas mensagens artificiais aos destinatários.
