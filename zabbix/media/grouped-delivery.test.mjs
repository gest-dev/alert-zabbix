import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const script = new vm.Script('(function(value) {\n' +
  fs.readFileSync(new URL('./grouped-delivery.js', import.meta.url), 'utf8') + '\n})');
const defaults = {
  QueueProvider: 'ativ', QueueRoute: '44', QueueUrl: 'http://127.0.0.1:8791/enqueue',
  QueueToken: 'FAKE_LOCAL_QUEUE_KEY', Token: 'FAKE_PROVIDER_KEY',
  To: '120000000000000000@g.us', Id: '120000000000000001@g.us',
  Subject: 'Falha no serviço', Message: 'Host: teste\nServiço indisponível.',
  Process: 'Servidor de teste', EventValue: '1', UpdateStatus: '0'
};

function execute(params = {}, response = {}) {
  const calls = [], headers = [];
  let proxy;
  class HttpRequest {
    setProxy(value) { proxy = value; }
    addHeader(value) { headers.push(value); }
    post(url, payload) {
      calls.push({url, body: JSON.parse(payload)});
      if (response.fail) throw Error('internal ' + defaults.Token);
      return response.body ?? '{"accepted":true}';
    }
    getStatus() { return response.status ?? 202; }
  }
  const run = script.runInNewContext({HttpRequest});
  try { return {result: run(JSON.stringify({...defaults, ...params})), calls, headers, proxy}; }
  catch (error) { return {error: String(error), calls, headers, proxy}; }
}

test('ATIV mantém destinatário e campos da mensagem, envia apenas à fila local', () => {
  const r = execute({HTTPProxy: 'http://proxy.invalid:8080'});
  assert.equal(r.result, 'OK');
  assert.equal(r.calls.length, 1);
  assert.equal(r.calls[0].url, defaults.QueueUrl);
  assert.equal(r.calls[0].body.recipient, defaults.To);
  assert.equal(r.calls[0].body.proxy, 'http://proxy.invalid:8080');
  assert.equal(r.proxy, '');
  assert.equal(r.calls[0].body.text, '*Nome do Processo:* Servidor de teste\n' +
    '*Tipo do Erro:* Falha no serviço\n*Descrição do Erro:* ' + defaults.Message + '\n');
  assert.ok(r.headers.includes('Authorization: Bearer ' + defaults.QueueToken));
  assert.ok(!r.headers.includes('Authorization: Bearer ' + defaults.Token));
});

test('Astro preserva Id fixo e Group, sem substituir pelo To', () => {
  const r = execute({QueueProvider: 'astro', QueueRoute: '43', Group: 'true'});
  assert.equal(r.calls[0].body.recipient, defaults.Id);
  assert.equal(r.calls[0].body.text, defaults.Message);
  assert.equal(r.calls[0].body.group, 'true');
});

test('Telegram mantém assunto e corpo e informa formato HTML', () => {
  const r = execute({QueueProvider: 'telegram', QueueRoute: '42', To: '-1001234', ParseMode: 'HTML'});
  assert.equal(r.calls[0].body.recipient, '-1001234');
  assert.equal(r.calls[0].body.text, defaults.Subject + '\n' + defaults.Message);
  assert.equal(r.calls[0].body.format, 'html');
});

test('recuperações e atualizações têm grupos próprios', () => {
  assert.equal(execute({EventValue: '0'}).calls[0].body.kind, 'recovery');
  assert.equal(execute({EventValue: '0', UpdateStatus: '1'}).calls[0].body.kind, 'update');
});

test('teste ATIV aceita Id alternativo', () => {
  assert.equal(execute({To: '{ALERT.SENDTO}'}).calls[0].body.recipient, defaults.Id);
});

for (const params of [
  {QueueUrl: 'http://outro-servidor/enqueue'}, {Token: '{$UNRESOLVED}'},
  {QueueToken: ''}, {QueueToken: 'key\r\nHeader: bad'}, {Message: ''},
  {QueueProvider: 'outro'}, {To: 'invalido'}
]) {
  test('configuração inválida impede envio: ' + Object.keys(params)[0], () => {
    const r = execute(params);
    assert.ok(r.error);
    assert.equal(r.calls.length, 0);
  });
}

for (const response of [{fail: true}, {status: 503}, {body: 'invalid'}, {body: '{"accepted":false}'}]) {
  test('fila sem confirmação não informa sucesso nem envia diretamente ao provedor', () => {
    const r = execute({}, response);
    assert.ok(r.error);
    assert.equal(r.calls.length, 1);
    assert.ok(!r.error.includes(defaults.Token));
    assert.ok(!r.error.includes(defaults.QueueToken));
  });
}
