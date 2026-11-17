// Webhook Zabbix 6.4. Configuração e credenciais são recebidas por parâmetros.
var params;
try {
    params = JSON.parse(value);
} catch (error) {
    throw 'WhatsappAtivDurvs: parâmetros JSON inválidos.';
}
if (!params || typeof params !== 'object' || Array.isArray(params)) {
    throw 'WhatsappAtivDurvs: informe um objeto de parâmetros.';
}

function text(name) {
    var result = params[name];
    return result === undefined || result === null ? '' : String(result).trim();
}

function unresolved(input) {
    return /\{(?:\$|ALERT\.)/.test(input);
}

var url = text('Url');
var token = text('Token');
var recipient = text('To');
if (!recipient || recipient === '{ALERT.SENDTO}') {
    recipient = text('Id');
}
var subject = text('Subject');
var message = text('Message');
var process = text('Process') || 'Zabbix';

if (!/^https?:\/\/[^\s/?#@]+(?:\/[^\s?#]*)?$/.test(url) || unresolved(url)) {
    throw 'WhatsappAtivDurvs: configure Url com o endereço completo da API.';
}
if (!token || unresolved(token) || /^\*+$/.test(token) || /[\r\n]/.test(token)) {
    throw 'WhatsappAtivDurvs: configure Token com uma macro secreta válida.';
}
if (!/^[0-9-]+@g\.us$/.test(recipient)
        && !/^[0-9]+@(?:c\.us|s\.whatsapp\.net)$/.test(recipient)) {
    throw 'WhatsappAtivDurvs: To ou Id deve conter um ID WhatsApp válido, como o ID de grupo terminado em @g.us.';
}
if (!message || unresolved(message) || unresolved(subject) || unresolved(process)) {
    throw 'WhatsappAtivDurvs: preencha Message e resolva as macros da mensagem.';
}

var body = {
    text: '*Nome do Processo:* ' + process + '\n'
        + '*Tipo do Erro:* ' + (subject || 'Aviso de monitoramento') + '\n'
        + '*Descrição do Erro:* ' + message + '\n',
    id: recipient
};
var request = new HttpRequest();
var response;
var status;
try {
    if (text('HTTPProxy')) {
        request.setProxy(text('HTTPProxy'));
    }
    request.addHeader('Content-Type: application/json');
    request.addHeader('Authorization: Bearer ' + token);
    response = request.post(url, JSON.stringify(body));
    status = request.getStatus();
} catch (error) {
    // Erros de transporte podem incluir a URL; não registrar parâmetros ou segredos.
    throw 'WhatsappAtivDurvs: falha de comunicação com o serviço WhatsApp.';
}
if (status < 200 || status >= 300) {
    throw 'WhatsappAtivDurvs: serviço WhatsApp retornou HTTP ' + status + '.';
}

var result;
try {
    result = JSON.parse(response);
} catch (error) {
    result = null;
}
if (result && (result.success === false || result.ok === false || result.status === false
        || (result.error !== undefined && result.error !== null
            && result.error !== false && result.error !== ''))) {
    throw 'WhatsappAtivDurvs: serviço WhatsApp informou falha no envio.';
}

// Não retornar resposta, destinatário ou credenciais para o log de ações.
return 'OK';
