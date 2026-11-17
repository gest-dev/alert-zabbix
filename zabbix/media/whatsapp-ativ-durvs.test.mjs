import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('./whatsapp-ativ-durvs.js', import.meta.url), 'utf8');
const compiled = new vm.Script('(function(value) {\n' + source + '\n})');
const defaults = {
  Url: 'https://whatsapp.example.invalid/api/message-by-id',
  Token: 'FAKE_TOKEN_FOR_OFFLINE_TESTS',
  To: '120000000000000000@g.us',
  Subject: 'Problema: Nginx parado',
  Message: 'Host: servidor de teste\nDescrição com "aspas" e acentuação.',
  Process: 'Zabbix · teste'
};

function execute(params = {}, response = {}) {
  const captured = {headers: [], calls: []};
  class HttpRequest {
    addHeader(header) { captured.headers.push(header); }
    setProxy(proxy) { captured.proxy = proxy; }
    post(url, payload) {
      captured.calls.push({url, body: JSON.parse(payload)});
      if (response.transportError) throw new Error(defaults.Token + ' private response');
      return response.body ?? '{"success":true}';
    }
    getStatus() { return response.status ?? 200; }
  }
  const run = compiled.runInNewContext({HttpRequest});
  let result, error;
  try { result = run(JSON.stringify({...defaults, ...params})); }
  catch (caught) { error = String(caught); }
  return {result, error, ...captured};
}

test('envia exatamente text e id com Bearer e preserva texto multilinha', () => {
  const r = execute();
  assert.equal(r.result, 'OK');
  assert.deepEqual(r.calls, [{url: defaults.Url, body: {
    text: '*Nome do Processo:* ' + defaults.Process + '\n'
      + '*Tipo do Erro:* ' + defaults.Subject + '\n'
      + '*Descrição do Erro:* ' + defaults.Message + '\n',
    id: defaults.To
  }}]);
  assert.ok(r.headers.includes('Authorization: Bearer ' + defaults.Token));
});

test('destino da mídia do usuário tem prioridade sobre o ID alternativo', () => {
  assert.equal(execute({Id: '120000000000000001@g.us'}).calls[0].body.id, defaults.To);
});

test('ID alternativo atende ao teste com ALERT.SENDTO ainda não resolvido', () => {
  const r = execute({To: '{ALERT.SENDTO}', Id: defaults.To});
  assert.equal(r.result, 'OK');
  assert.equal(r.calls[0].body.id, defaults.To);
});

for (const [name, params] of Object.entries({
  'destino inválido': {To: 'invalid destination'},
  'token ausente': {Token: ''},
  'macro secreta não resolvida': {Token: '{$WHATSAPP.ATIV.TOKEN}'},
  'token mascarado': {Token: '******'},
  'injeção de cabeçalho': {Token: 'token\r\nAnother: header'},
  'credencial embutida na URL': {Url: 'https://user:password@example.invalid/api'},
  'mensagem ausente': {Message: ''},
  'mensagem não resolvida': {Message: '{ALERT.MESSAGE}'}
})) {
  test('rejeita ' + name + ' antes de chamar o serviço', () => {
    const r = execute(params);
    assert.ok(r.error);
    assert.equal(r.calls.length, 0);
    assert.ok(!r.error.includes(defaults.Token));
  });
}

test('falha HTTP não expõe corpo da resposta ou credencial', () => {
  const r = execute({}, {status: 401, body: defaults.Token});
  assert.match(r.error, /HTTP 401/);
  assert.ok(!r.error.includes(defaults.Token));
});

test('falha explícita em JSON 200 é tratada como falha de envio', () => {
  assert.match(execute({}, {body: '{"success":false}'}).error, /falha no envio/);
});

test('erro de transporte é sanitizado', () => {
  const r = execute({}, {transportError: true});
  assert.match(r.error, /falha de comunicação/);
  assert.ok(!r.error.includes(defaults.Token));
});

test('suporta proxy opcional e resposta HTTP 204 sem corpo', () => {
  const r = execute({HTTPProxy: 'http://proxy.example.invalid:8080'}, {status: 204, body: ''});
  assert.equal(r.result, 'OK');
  assert.equal(r.proxy, 'http://proxy.example.invalid:8080');
});
