/* Zabbix 6.4 / Duktape. Entrada: walk SNMP; __MODE__ é validado pelo configurador. */
var mode = '__MODE__';
var roots = {
    names: '1.3.6.1.2.1.17.7.1.4.3.1.1.',
    status: '1.3.6.1.2.1.17.7.1.4.3.1.5.',
    pvid: '1.3.6.1.2.1.17.7.1.4.5.1.1.',
    bridge: '1.3.6.1.2.1.17.1.4.1.2.',
    interfaces: '1.3.6.1.2.1.31.1.1.1.1.',
    oper: '1.3.6.1.2.1.2.2.1.8.'
};
var data = {names: {}, status: {}, pvid: {}, bridge: {}, interfaces: {}, oper: {}};
function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function integer(s) {
    var m = s.match(/(?:^|:\s*|\()(-?\d+)\)?\s*$/);
    return m ? Number(m[1]) : null;
}
var lines = value.split(/\r?\n/);
for (var n = 0; n < lines.length; n++) {
    var match = lines[n].match(/^\.?([\d.]+)\s*=\s*(.*)$/);
    if (!match) continue;
    for (var group in roots) {
        if (match[1].indexOf(roots[group]) !== 0) continue;
        var index = match[1].slice(roots[group].length);
        if (!/^\d+$/.test(index)) continue;
        var raw = match[2];
        if (/No Such|No more|End of MIB/i.test(raw)) continue;
        data[group][index] = group === 'names' || group === 'interfaces'
            ? raw.replace(/^STRING:\s*/, '').replace(/^"|"$/g, '') : integer(raw);
        break;
    }
}
var ids = Object.keys(data.names).filter(function(id) {
    return Number(id) >= 1 && Number(id) <= 4094;
}).sort(function(a, b) { return Number(a) - Number(b); });
if (!ids.length) throw 'A tabela de VLANs não retornou registros válidos.';
var active = 0;
for (var i = 0; i < ids.length; i++) if (data.status[ids[i]] === 1) active++;
var ports = [];
for (var bridge in data.pvid) {
    var ifindex = data.bridge[bridge];
    if (ifindex === null || ifindex === undefined) ifindex = bridge;
    var name = data.interfaces[String(ifindex)];
    var pvid = data.pvid[bridge];
    if (!name || !/^xgei-\d+\/\d+\/\d+$/.test(name) || pvid === null || pvid < 1 || pvid > 4094) continue;
    ports.push({name: name, pvid: pvid, state: data.oper[String(ifindex)]});
}
ports.sort(function(a, b) {
    var aa = a.name.match(/\d+/g), bb = b.name.match(/\d+/g);
    for (var k = 0; k < aa.length; k++) if (Number(aa[k]) !== Number(bb[k])) return Number(aa[k]) - Number(bb[k]);
    return 0;
});
if (mode === 'total') return ids.length;
if (mode === 'active') {
    for (var j = 0; j < ids.length; j++) {
        if (data.status[ids[j]] === null || data.status[ids[j]] === undefined) throw 'Estado de configuração de VLAN ausente.';
    }
    return active;
}
if (mode === 'ports') {
    if (!ports.length) throw 'Nenhum uplink Ethernet identificado com PVID válido.';
    return ports.length;
}

var body = '', heading, intro, columns, note;
if (mode === 'vlans_html') {
    heading = 'Inventário de VLANs';
    intro = ids.length + ' VLANs cadastradas na OLT';
    columns = '<th>ID</th><th>Nome</th><th>Configuração</th>';
    var statuses = {1: 'Ativa', 2: 'Não ativa', 3: 'Não pronta', 4: 'Em criação', 5: 'Em espera', 6: 'Em remoção'};
    for (var v = 0; v < ids.length; v++) {
        var id = ids[v], state = data.status[id];
        body += '<tr><td><b class="zte-vlan-id">' + id + '</b></td><td>' + esc(data.names[id] || 'Sem nome')
            + '</td><td><span class="zte-vlan-badge ' + (state === 1 ? 'zte-vlan-up' : 'zte-vlan-muted') + '">'
            + esc(statuses[state] || 'Não informado') + '</span></td></tr>';
    }
    note = 'Ativa é o estado da configuração; não confirma tráfego ou disponibilidade do serviço.';
} else if (mode === 'ports_html') {
    heading = 'Uplinks · VLAN padrão de entrada';
    intro = ports.length + ' portas Ethernet com PVID informado';
    columns = '<th>Porta</th><th>PVID</th><th>Link</th>';
    for (var p = 0; p < ports.length; p++) {
        var port = ports[p];
        var label = port.state === 1 ? 'Operante' : (port.state === 2 ? 'Sem link' : 'Não informado');
        body += '<tr><td><b>' + esc(port.name) + '</b></td><td><span class="zte-vlan-id">' + port.pvid
            + '</span></td><td><span class="zte-vlan-badge ' + (port.state === 1 ? 'zte-vlan-up' : 'zte-vlan-muted') + '">'
            + label + '</span></td></tr>';
    }
    if (!ports.length) body = '<tr><td colspan="3">PVID das portas Ethernet não disponível nesta coleta.</td></tr>';
    note = 'PVID: VLAN atribuída à entrada sem tag. Não é a lista de VLANs permitidas na porta. Sem link também pode indicar porta ociosa.';
} else {
    throw 'Modo de apresentação inválido.';
}
var stamp = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
return '<style>'
    + 'table:has(.gest-zte-vlans){width:100%;table-layout:fixed}'
    + 'table:has(.gest-zte-vlans)>thead{display:none}'
    + 'table:has(.gest-zte-vlans)>tbody>tr>td:first-child{display:none}'
    + 'table:has(.gest-zte-vlans)>tbody>tr>td{padding:0}'
    + '.gest-zte-vlans{box-sizing:border-box;width:100%;min-width:0;white-space:normal;padding:16px;background:#101e2b;border:1px solid #284254;border-radius:10px;color:#e2e8f0;font:13px/1.4 system-ui,sans-serif}'
    + '.gest-zte-vlans *{box-sizing:border-box}'
    + '.gest-zte-vlans h3{margin:0 0 4px;font-size:18px;color:#f8fafc;text-transform:none;letter-spacing:normal;font-family:inherit}'
    + '.gest-zte-vlans p{margin:0 0 12px;color:#94a3b8;font-size:12px}'
    + '.gest-zte-vlans table{border-collapse:collapse;width:100%;table-layout:auto}'
    + '.gest-zte-vlans th{text-align:left;padding:7px 8px;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #334155}'
    + '.gest-zte-vlans td{text-align:left;height:auto;line-height:18px;padding:5px 8px;border-bottom:1px solid #203549;color:#e2e8f0}'
    + '.gest-zte-vlans tbody tr:nth-child(even){background:#132433}'
    + '.gest-zte-vlans tbody tr:hover{background:#1c3448}'
    + '.gest-zte-vlans .zte-vlan-id{color:#7dd3fc;font-variant-numeric:tabular-nums}'
    + '.gest-zte-vlans .zte-vlan-badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;white-space:nowrap}'
    + '.gest-zte-vlans .zte-vlan-up{color:#6ee7b7;background:#133f39}'
    + '.gest-zte-vlans .zte-vlan-muted{color:#b7c7d5;background:#253646}'
    + '.gest-zte-vlans footer{display:block;position:static;width:auto;min-width:0;padding:0;text-align:left;line-height:1.4;margin-top:10px;color:#94a3b8;font-size:11px;white-space:normal}'
    + '.gest-zte-vlans footer small{display:block;margin-top:6px;font-size:10px;color:#7e97aa}'
    + '</style><section class="gest-zte-vlans"><h3>' + heading + '</h3><p>' + intro
    + '</p><table><thead><tr>' + columns + '</tr></thead><tbody>' + body
    + '</tbody></table><footer>' + note + '<small>Coleta: ' + esc(stamp) + '</small></footer></section>';
