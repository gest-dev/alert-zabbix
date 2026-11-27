// Agrupa somente a entrega. Não consulta ou modifica eventos do Zabbix.
var p;
try { p = JSON.parse(value); }
catch (error) { throw 'Agrupador: parâmetros JSON inválidos.'; }
if (!p || typeof p !== 'object' || Array.isArray(p)) {
    throw 'Agrupador: informe um objeto de parâmetros.';
}
function field(name) {
    return p[name] === undefined || p[name] === null ? '' : String(p[name]);
}
function required(name) {
    var v = field(name).trim();
    if (!v || /\{(?:\$|ALERT\.)/.test(v) || /^\*+$/.test(v)) {
        throw 'Agrupador: configure ' + name + '.';
    }
    return v;
}
var provider = required('QueueProvider');
var recipient, message, format = 'plain';
if (provider === 'telegram') {
    recipient = required('To');
    message = field('Subject') + '\n' + required('Message');
    format = (field('ParseMode') || 'plain').toLowerCase();
} else if (provider === 'ativ') {
    recipient = field('To').trim();
    if (!recipient || recipient === '{ALERT.SENDTO}') { recipient = required('Id'); }
    if (!/^[0-9-]+@g\.us$/.test(recipient)
            && !/^[0-9]+@(?:c\.us|s\.whatsapp\.net)$/.test(recipient)) {
        throw 'Agrupador: destinatário WhatsApp inválido.';
    }
    message = '*Nome do Processo:* ' + (field('Process') || 'Zabbix') + '\n'
        + '*Tipo do Erro:* ' + (field('Subject') || 'Aviso de monitoramento') + '\n'
        + '*Descrição do Erro:* ' + required('Message') + '\n';
} else if (provider === 'astro') {
    // As mídias Astro existentes usam Id, independentemente de To.
    recipient = required('Id');
    message = required('Message');
} else {
    throw 'Agrupador: provedor inválido.';
}
var url = required('QueueUrl');
if (url !== 'http://127.0.0.1:8791/enqueue') {
    throw 'Agrupador: QueueUrl deve apontar para a fila local.';
}
var queueToken = required('QueueToken');
var token = required('Token');
if (/[\r\n]/.test(queueToken + token)) { throw 'Agrupador: token inválido.'; }
var kind = field('UpdateStatus') === '1' ? 'update'
    : field('EventValue') === '0' ? 'recovery' : 'problem';
var payload = {
    route: required('QueueRoute'), provider: provider, recipient: recipient,
    token: token, text: message, format: format, kind: kind,
    group: field('Group'), proxy: field('HTTPProxy')
};
var request = new HttpRequest();
var raw, status;
try {
    // A fila é local: não utilizar o proxy do serviço de mensagens aqui.
    request.setProxy('');
    request.addHeader('Content-Type: application/json');
    request.addHeader('Authorization: Bearer ' + queueToken);
    raw = request.post(url, JSON.stringify(payload));
    status = request.getStatus();
} catch (error) {
    throw 'Agrupador: fila indisponível; a notificação deve ser tentada novamente.';
}
var result;
try { result = JSON.parse(raw); } catch (error) { result = null; }
if (status !== 202 || !result || result.accepted !== true) {
    throw 'Agrupador: notificação não confirmada pela fila (HTTP ' + status + ').';
}
// OK confirma gravação persistente na fila; a entrega é feita pelo serviço.
return 'OK';
