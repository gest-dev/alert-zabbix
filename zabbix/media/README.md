# WhatsApp ATIV / Durvs

O script [whatsapp-ativ-durvs.js](whatsapp-ativ-durvs.js) implementa a chamada
WhatsApp de `Commons::sendMessageWhatsAppById`: POST JSON com `text` e `id`,
autenticado pelo cabeçalho `Authorization: Bearer …`. O texto mantém os campos
Nome do Processo, Tipo do Erro e Descrição do Erro. Não replica o envio Discord.

No Zabbix, configure o tipo de mídia **WhatsappAtivDurvs** como **Webhook**,
cole o script e defina os parâmetros:

| Parâmetro | Valor |
| --- | --- |
| `Url` | `{$WHATSAPP.ATIV.URL}` |
| `Token` | `{$WHATSAPP.ATIV.TOKEN}` |
| `To` | `{ALERT.SENDTO}` |
| `Id` | ID do grupo usado como alternativa quando `To` está vazio ou não resolvido no teste |
| `Subject` | `{ALERT.SUBJECT}` |
| `Message` | `{ALERT.MESSAGE}` |
| `Process` | `{HOST.NAME}` |
| `HTTPProxy` | Vazio, salvo se houver proxy HTTP configurado |

Crie as macros em **Administração → Macros**, no escopo global:

- `{$WHATSAPP.ATIV.URL}`: endpoint completo usado pelo projeto, incluindo o
  caminho `/api/message-by-id`.
- `{$WHATSAPP.ATIV.TOKEN}`: valor de `TOKEN_WHATSAPP_ATIV` do `.env` do projeto,
  com tipo **Texto secreto**, sem o prefixo `Bearer`.

O `.env` não é lido pelo JavaScript do webhook. O token deve ser transferido
para a macro secreta administrativamente, sem gravá-lo no script, nos exemplos,
em comandos de terminal ou nos arquivos versionados. Se o token mudar no
serviço, atualize também a macro.

Na mídia do usuário destinatário da ação, selecione **WhatsappAtivDurvs** e
preencha **Enviar para** com o ID WhatsApp do destino. Para um grupo, o ID
termina em `@g.us`. O parâmetro `To` tem prioridade sobre `Id`, permitindo usar
o mesmo tipo de mídia para vários destinos, conforme os usuários das ações.
IDs são usados como strings; não os converta para números JavaScript.

A ação deve filtrar o grupo de hosts desejado e selecionar esta mídia nas
operações. Mantenha os modelos de mensagem de problema e recuperação. O grupo
de hosts do Zabbix e o grupo WhatsApp são configurações distintas.

O webhook aceita respostas HTTP 2xx, rejeita falhas explícitas em JSON e
informa falha para outros códigos HTTP ou erros de transporte. Não registra
token, cabeçalhos, destinatário, texto ou corpo da resposta. O retorno `OK`
indica aceitação da requisição pela API; não comprova leitura no WhatsApp.

Os testes automatizados devem substituir `HttpRequest` por uma implementação
simulada. O botão **Testar** do Zabbix faz um envio real para o destino
informado; use-o somente quando quiser enviar uma mensagem.

Para executar os testes locais, sem rede e sem credenciais:

```bash
node zabbix/media/whatsapp-ativ-durvs.test.mjs
```

Referências: [webhooks Zabbix 6.4](https://www.zabbix.com/documentation/6.4/en/manual/config/notifications/media/webhook),
[macros secretas](https://www.zabbix.com/documentation/6.4/en/manual/config/macros/secret_macros)
e [HttpRequest](https://www.zabbix.com/documentation/6.4/en/manual/config/items/preprocessing/javascript/javascript_objects#httprequest).

## WhatsApp Astro

A mídia **WhatsappAstro** mantém o script e o contrato próprios do serviço
existente (`id`, `message` e `group`). Seus parâmetros usam macros globais
independentes das macros ATIV:

| Parâmetro | Macro | Tipo da macro |
| --- | --- | --- |
| `Token` | `{$WHATSAPP.ASTRO.TOKEN}` | Texto secreto |
| `Url` | `{$WHATSAPP.ASTRO.URL}` | Texto |

Os valores foram transferidos da configuração existente da mídia, sem alterar
destino, método HTTP, mensagens, ações ou usuários. Para atualizar a credencial,
acesse **Administração → Macros**, defina um novo valor para a macro de token e
salve. Não substitua esse script pelo ATIV: os dois serviços recebem formatos
de requisição diferentes. A alteração de macros não envia mensagens de teste.

## Telegram Home

O parâmetro `Token` da mídia **TelegramHome** referencia a macro global
`{$TELEGRAM.HOME.TOKEN}`, do tipo **Texto secreto**. O valor foi migrado do
parâmetro original sem alterar o script, o destinatário, as mensagens ou as
ações. Para trocar o token do bot, atualize essa macro em
**Administração → Macros**. A migração não envia mensagens de teste.
