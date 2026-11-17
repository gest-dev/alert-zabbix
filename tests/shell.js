import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Scripting from 'resource:///org/gnome/shell/ui/scripting.js';

export const METRICS = {};
let count = 0;
function check(condition, message) {
    count++;
    if (!condition)
        throw new Error(message);
}

export async function run() {
    Main.overview.hide();
    await Scripting.sleep(2500);
    const uuid = 'alert-zabbix@gezer.local';
    const ext = Main.extensionManager.lookup(uuid);
    check(Boolean(ext?.stateObj?._button), `Enable failed: ${ext?.error}`);
    const monitor = ext.stateObj;
    check(monitor._icon.gicon.get_file().query_exists(null) && monitor._icon.is_symbolic,
        'Bundled panel icon exists and renders symbolically');
    const settingsFile = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_config_dir(), 'alert-zabbix', 'settings.json']));
    const originalButton = monitor._button;
    for (const [position, parent] of [['left', Main.panel._leftBox], ['right', Main.panel._rightBox]]) {
        const sizes = position === 'left' ? {font_size: 9, icon_size: 10, spacing: 2} : {font_size: 20, icon_size: 32, spacing: 20};
        settingsFile.replace_contents(JSON.stringify({panel_position: position, ...sizes}), null, false, Gio.FileCreateFlags.NONE, null);
        await Scripting.sleep(1000);
        check(monitor._button.container.get_parent() === parent, `Saved preference moves indicator to ${position} without a server`);
        check(monitor._button === originalButton, 'Moving preserves the indicator and menu');
        check(monitor._label.get_style().includes(`font-size: ${sizes.font_size}px`), 'Font size changes from saved preference');
        check(monitor._icon.icon_size === sizes.icon_size && monitor._icon.width === sizes.icon_size,
            `Icon size changes in the rendered panel: requested ${sizes.icon_size}, property ${monitor._icon.icon_size}, rendered ${monitor._icon.width}`);
        check(monitor._indicatorBox.get_style().includes(`spacing: ${sizes.spacing}px`), 'Indicator spacing changes');
    }
    settingsFile.replace_contents(JSON.stringify({panel_position: 'right', font_size: 11, icon_size: 16, spacing: 5}), null, false, Gio.FileCreateFlags.NONE, null);
    await Scripting.sleep(700);
    const config = {url: 'https://zabbix.example.test/zabbix', interval: 30, min_severity: 0, notifications: true};
    const fixture = {ok: true, version: '6.4.21', checked_at: Date.now() / 1000, config,
        problems: [{id: 'test-1', severity: 4, name: 'Problema de teste · disco cheio', host: 'Servidor de teste',
            clock: Date.now() / 1000 - 1800, acknowledged: false, url: 'https://zabbix.example.test/zabbix/'}]};
    const notices = [];
    const notify = monitor._notify;
    monitor._notify = (...args) => notices.push(args);
    monitor._receive(fixture);
    check(monitor._label.text === 'Zabbix 1 · 1 alto', 'Problem count and severity shown without opening menu');
    check(notices.length === 1 && notices[0][0].includes('atual(is)'), 'Startup summarizes current problems once');
    check(monitor._label.get_style().includes('#f87171'), 'Highest severity color');
    check(monitor._label.get_style().includes('font-size: 11px'), 'Receiving new problems preserves the chosen font size');
    check(monitor._status.label.text === '1 problema(s) atual(is)', 'Header shows current problems only');
    const next = {...fixture, problems: [...fixture.problems, {...fixture.problems[0], id: 'test-2'}]};
    monitor._receive(next);
    monitor._receive(next);
    check(notices.length === 2, 'New problems notify once, unchanged snapshots stay silent');
    const raised = {...next, problems: next.problems.map(row => ({...row, severity: 5}))};
    monitor._receive(raised);
    monitor._receive(raised);
    check(notices.length === 3 && notices[2][1].includes('Desastre'), 'Severity escalation notifies once');
    monitor._receive({...raised, config: {...config, notifications: false}, problems: [...raised.problems, {...raised.problems[0], id: 'test-3'}]});
    check(notices.length === 3, 'Screen notifications can be disabled');
    monitor._receive(next);
    check(monitor._problems._getMenuItems().length === 2, 'Current problems replace the list without duplication');
    monitor._receive({...fixture, problems: []});
    check(monitor._label.text === 'Zabbix OK', 'Resolved events disappear and panel shows OK');
    check(notices.length === 3, 'Recovery does not generate a problem alert');
    check(monitor._problems._getMenuItems()[0].label.text.includes('Nenhum problema atual'), 'Empty current list is explicit');
    monitor._receive(next);
    monitor._receive({ok: false, kind: 'connection', error: 'Rede indisponível · teste'});
    check(monitor._label.text === 'Zabbix !', 'Connection failure does not present old count as current');
    check(monitor._label.get_style().includes('font-size: 11px') && monitor._icon.icon_size === 16, 'Connection failure preserves the chosen sizes');
    check(monitor._problems._getMenuItems().length === 0, 'Old problems are hidden when current state is unavailable');
    check(monitor._summary.label.text.startsWith('Última consulta válida'), 'Last valid timestamp shown');
    monitor._receive({ok: false, kind: 'auth', error: 'Login recusado · teste'});
    check(monitor._paused, 'Auth failure pauses automatic retries');
    monitor._receive(fixture);
    check(!monitor._paused, 'Successful refresh clears pause');
    check(monitor._problems._getMenuItems()[0].label.text.includes('Servidor de teste'), 'Host appears in problem list');
    monitor._button.menu.open();
    await Scripting.sleep(400);
    check(monitor._problems._getMenuItems()[0].mapped, 'Current problem is immediately visible when opening the menu');
    const stream = Gio.File.new_for_path('/tmp/alert-zabbix-preview.png').replace(null, false, Gio.FileCreateFlags.NONE, null);
    await new Promise((resolve, reject) => {
        new Shell.Screenshot().screenshot(false, stream, (object, result) => {
            try { object.screenshot_finish(result); resolve(); } catch (error) { reject(error); }
        });
    });
    stream.close(null);
    monitor._button.menu.close();
    monitor._notify = notify;
    const notification = monitor._notify('Ícone do Zabbix · teste', 'Aviso exclusivo da sessão de teste.');
    check(notification.gicon.get_file().query_exists(null) && monitor._notificationSource.icon.equal(notification.gicon),
        'Native notifications use the bundled app logo');
    const source = monitor._notificationSource;
    monitor._configure();
    const windows = () => global.get_window_actors().map(actor => actor.meta_window)
        .filter(window => window.get_gtk_application_id() === 'org.gezer.AlertZabbix');
    for (let i = 0; i < 25 && !windows().length; i++)
        await Scripting.sleep(200);
    check(windows().length === 1, 'Configuration window opens');
    monitor._configure();
    await Scripting.sleep(400);
    check(windows().length === 1, 'Repeated activation reuses window');
    Main.activateWindow(windows()[0]);
    await Scripting.sleep(1500);
    const configStream = Gio.File.new_for_path('/tmp/alert-zabbix-config-preview.png').replace(null, false, Gio.FileCreateFlags.NONE, null);
    await new Promise((resolve, reject) => {
        new Shell.Screenshot().screenshot(false, configStream, (object, result) => {
            try { object.screenshot_finish(result); resolve(); } catch (error) { reject(error); }
        });
    });
    configStream.close(null);
    monitor._configure(true);
    for (let attempt = 0; attempt < 20 && !windows()[0]?.get_title().includes('Barra e avisos'); attempt++)
        await Scripting.sleep(250);
    check(windows().length === 1, 'Appearance shortcut reuses the configuration window');
    check(windows()[0].get_title().includes('Barra e avisos'), 'Appearance shortcut opens the requested page');
    Main.activateWindow(windows()[0]);
    await Scripting.sleep(300);
    const appearanceStream = Gio.File.new_for_path('/tmp/alert-zabbix-appearance-preview.png').replace(null, false, Gio.FileCreateFlags.NONE, null);
    await new Promise((resolve, reject) => {
        new Shell.Screenshot().screenshot(false, appearanceStream, (object, result) => {
            try { object.screenshot_finish(result); resolve(); } catch (error) { reject(error); }
        });
    });
    appearanceStream.close(null);
    windows()[0].delete(global.get_current_time());
    await Scripting.sleep(300);
    const testPath = Gio.File.new_for_uri(import.meta.url).get_parent().get_child('ui.py').get_path();
    const test = Gio.Subprocess.new(['python3', testPath], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
    const [output, errors] = await new Promise((resolve, reject) => {
        test.communicate_utf8_async(null, null, (child, result) => {
            try {
                const [, stdout, stderr] = child.communicate_utf8_finish(result);
                resolve([stdout, stderr]);
            } catch (error) { reject(error); }
        });
    });
    check(test.get_successful() && output.includes('ALERT_ZABBIX_UI_OK'), `Connection UI tests failed: ${output}\n${errors}`);
    print(output.trim());
    settingsFile.replace_contents(JSON.stringify({panel_position: 'left', font_size: 9, icon_size: 10, spacing: 2}), null, false, Gio.FileCreateFlags.NONE, null);
    await Scripting.sleep(700);
    Main.extensionManager.disableExtension(uuid);
    check(monitor._button === null, 'Disable cleans up panel');
    check(monitor._notificationSource === null && source.notifications.length === 0, 'Disable releases the branded notification source');
    Main.extensionManager.enableExtension(uuid);
    await Scripting.sleep(1000);
    check(Boolean(monitor._button), 'Re-enable succeeds with existing config directory');
    check(monitor._button.container.get_parent() === Main.panel._leftBox, 'Saved position survives re-enabling');
    check(monitor._label.get_style().includes('font-size: 9px') && monitor._icon.icon_size === 10, 'Saved sizes survive re-enabling');
    print(`ALERT_ZABBIX_SHELL_OK: ${count} verificações.`);
}
