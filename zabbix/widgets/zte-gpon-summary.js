/* Zabbix 6.4 / Duktape: HTML seguro para o widget nativo Texto simples.
 * __SLOT__ é substituído por um slot validado pelo configurador.
 * A entrada é o walk SNMP compartilhado, nunca uma credencial.
 */
var slot = '__SLOT__';
var oidName = '1.3.6.1.2.1.31.1.1.1.1.';
var oidState = '1.3.6.1.2.1.2.2.1.8.';
var oidAuth = '1.3.6.1.4.1.3902.1082.500.10.2.2.3.1.14.';
var oidOnline = '1.3.6.1.4.1.3902.1082.500.10.2.2.3.1.15.';
var names = {}, states = {}, auth = {}, online = {};
var lines = value.split(/\r?\n/);
function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function number(s) {
    var m = s.match(/(?:^|:\s*|\()(-?\d+)\)?\s*$/);
    return m ? Number(m[1]) : null;
}
for (var i = 0; i < lines.length; i++) {
    var match = lines[i].match(/^\.?([\d.]+)\s*=\s*(.*)$/);
    if (!match) continue;
    var oid = match[1], raw = match[2];
    if (oid.indexOf(oidName) === 0) {
        names[oid.slice(oidName.length)] = raw.replace(/^STRING:\s*/, '').replace(/^"|"$/g, '');
    }
    else if (oid.indexOf(oidState) === 0) states[oid.slice(oidState.length)] = number(raw);
    else if (oid.indexOf(oidAuth) === 0) auth[oid.slice(oidAuth.length)] = number(raw);
    else if (oid.indexOf(oidOnline) === 0) online[oid.slice(oidOnline.length)] = number(raw);
}
var ports = [];
for (var index in names) {
    var port = names[index].match(/^gpon_olt-(\d+\/\d+)\/(\d+)$/);
    if (port && port[1] === slot) {
        ports.push({index: index, port: Number(port[2]), name: port[1] + '/' + port[2]});
    }
}
ports.sort(function(a, b) { return a.port - b.port; });
if (!ports.length) throw 'Nenhuma porta GPON encontrada para o slot ' + slot;
var total = 0, on = 0, complete = true, body = '';
for (var n = 0; n < ports.length; n++) {
    var p = ports[n], a = auth[p.index], o = online[p.index], s = states[p.index];
    var valid = a !== undefined && a !== null && o !== undefined && o !== null && a >= 0 && o >= 0 && o <= a;
    var off = valid ? a - o : null;
    var percent = valid && a > 0 ? o / a * 100 : 0;
    var status = s === 1 ? 'Operante' : (s === 2 ? 'Sem link' : 'Estado ' + String(s === null || s === undefined ? '—' : s));
    var badge = s === 1 ? 'gest-zte-up' : 'gest-zte-muted';
    if (valid) { total += a; on += o; } else { complete = false; }
    body += '<tr><td><strong>' + escapeHtml(p.name) + '</strong></td>'
        + '<td><span class="gest-zte-badge ' + badge + '">' + status + '</span></td>'
        + '<td>' + (valid ? a : '—') + '</td>'
        + '<td class="gest-zte-green">' + (valid ? o : '—') + '</td>'
        + '<td class="' + (off > 0 ? 'gest-zte-amber' : 'gest-zte-soft') + '">' + (valid ? off : '—') + '</td>'
        + '<td><div class="gest-zte-meter"><span style="width:' + percent.toFixed(1) + '%"></span></div>'
        + '<small>' + (valid ? (a ? percent.toFixed(1) + '% online' : 'Sem ONUs') : 'Aguardando dados') + '</small></td></tr>';
}
var stamp = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
var css = '<style>'
    + 'table:has(.gest-zte-gpon)>thead{display:none}'
    + 'table:has(.gest-zte-gpon)>tbody>tr>td:first-child{display:none}'
    + 'table:has(.gest-zte-gpon)>tbody>tr>td{padding:0}'
    + '.gest-zte-gpon{box-sizing:border-box;background:#101e2b;color:#e2e8f0;border:1px solid #284254;border-radius:10px;padding:18px;font:13px/1.45 system-ui,sans-serif;min-width:540px}'
    + '.gest-zte-gpon *{box-sizing:border-box}.gest-zte-gpon h3{font-size:18px;margin:0 0 4px;color:#f8fafc}'
    + '.gest-zte-gpon p{color:#94a3b8;margin:0 0 14px;font-size:12px}'
    + '.gest-zte-summary{display:flex;gap:10px;margin-bottom:14px}.gest-zte-summary>div{flex:1;border:1px solid #2a4255;border-radius:8px;padding:10px 12px;background:#162a3a}'
    + '.gest-zte-summary b{display:block;font-size:24px;line-height:1.2}.gest-zte-summary small{color:#94a3b8;font-size:11px}'
    + '.gest-zte-table{border-collapse:collapse;width:100%;table-layout:auto}.gest-zte-table th{color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.6px;text-align:right;border-bottom:1px solid #334155;padding:9px 6px}'
    + '.gest-zte-table td{text-align:right;border-bottom:1px solid #203549;padding:2px 6px;white-space:nowrap;font-variant-numeric:tabular-nums;color:#e2e8f0}'
    + '.gest-zte-table th:first-child,.gest-zte-table td:first-child,.gest-zte-table th:nth-child(2),.gest-zte-table td:nth-child(2){text-align:left}'
    + '.gest-zte-table tbody tr:nth-child(even){background:#132433}.gest-zte-table tr:hover{background:#1c3448}'
    + '.gest-zte-gpon .gest-zte-green{color:#4adeb5}.gest-zte-gpon .gest-zte-amber{color:#fbbf24}.gest-zte-gpon .gest-zte-soft{color:#64748b}'
    + '.gest-zte-badge{display:inline-block;padding:3px 7px;border-radius:12px;font-size:10px}.gest-zte-up{color:#6ee7b7;background:#133f39}.gest-zte-muted{color:#a9b9c9;background:#253646}'
    + '.gest-zte-meter{height:5px;min-width:80px;background:#334155;border-radius:8px;overflow:hidden}.gest-zte-meter span{display:block;height:100%;background:#34d399;border-radius:8px}'
    + '.gest-zte-table small{font-size:10px;color:#a7bdcc}.gest-zte-footer{margin-top:12px;color:#7e97aa;font-size:10px}'
    + '</style>';
return css + '<section class="gest-zte-gpon"><h3>Placa GPON ' + escapeHtml(slot) + '</h3>'
    + '<p>' + ports.length + ' portas · ONUs autorizadas, conectadas e não online</p>'
    + '<div class="gest-zte-summary"><div><b>' + (complete ? total : '—') + '</b><small>Autorizadas</small></div>'
    + '<div><b class="gest-zte-green">' + (complete ? on : '—') + '</b><small>Online</small></div>'
    + '<div><b class="gest-zte-amber">' + (complete ? total - on : '—') + '</b><small>Não online</small></div></div>'
    + '<table class="gest-zte-table"><thead><tr><th>Porta</th><th>Link</th><th>Autoriz.</th><th>Online</th><th>Não online</th><th>Conectadas</th></tr></thead><tbody>'
    + body + '</tbody></table><div class="gest-zte-footer">' + escapeHtml(stamp)
    + ' · Não online = autorizadas − online. Sem link não distingue porta ociosa de falha.</div></section>';
