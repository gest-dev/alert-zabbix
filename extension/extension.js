import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';

const NAMES = ['Não classificado', 'Informação', 'Advertência', 'Médio', 'Alto', 'Desastre'];
const COLORS = ['#a1a1aa', '#60a5fa', '#facc15', '#fb923c', '#f87171', '#ef4444'];

export default class AlertZabbix extends Extension {
    enable() {
        this._alive = true;
        this._generation = (this._generation ?? 0) + 1;
        this._state = null;
        this._seen = null;
        this._identity = null;
        this._paused = false;
        this._timer = 0;
        this._reloadTimer = 0;
        this._process = null;
        this._panelPosition = 'right';
        this._appearance = {font_size: 11, icon_size: 16, spacing: 5};
        this._panelColor = '#a5b1a8';
        this._settingsCancel = new Gio.Cancellable();
        this._notificationSource = null;
        this._brandIcon = new Gio.FileIcon({file: this.dir.get_child('icons').get_child('org.gezer.AlertZabbix.png')});
        this._button = new PanelMenu.Button(0.0, 'Alertas Zabbix');
        this._button.add_style_class_name('zabbix-panel-button');
        const box = new St.BoxLayout({style_class: 'zabbix-indicator'});
        this._indicatorBox = box;
        this._icon = new St.Icon({gicon: new Gio.FileIcon({file: this.dir.get_child('icons').get_child('alert-zabbix-symbolic.svg')}),
            style_class: 'zabbix-panel-icon', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        this._label = new St.Label({text: 'Zabbix …', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._label);
        this._button.add_child(box);
        this._applyPanelStyle();
        this._status = new PopupMenu.PopupMenuItem('Consultando Zabbix…', {reactive: false});
        this._status.label.add_style_class_name('zabbix-heading');
        this._button.menu.addMenuItem(this._status);
        this._summary = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._summary.label.add_style_class_name('zabbix-summary');
        this._button.menu.addMenuItem(this._summary);
        this._problems = new PopupMenu.PopupMenuSection();
        this._button.menu.addMenuItem(this._problems);
        this._button.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._button.menu.addAction('Atualizar agora', () => this._pull(true));
        this._button.menu.addAction('Abrir Zabbix', () => this._state?.config.url ? this._open(this._state.config.url) : this._configure());
        this._button.menu.addAction('Configurar conexão', () => this._configure());
        this._button.menu.addAction('Aparência e posição', () => this._configure(true));
        Main.panel.addToStatusArea(this.uuid, this._button, 1, 'right');
        // Watch the parent because saving replaces the file atomically.
        const directory = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_config_dir(), 'alert-zabbix']));
        if (!directory.query_exists(null))
            directory.make_directory_with_parents(null);
        this._watchConfig(directory);
        this._loadPreferences();
        this._pull();
    }

    _loadPreferences() {
        const generation = this._generation;
        const file = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_config_dir(), 'alert-zabbix', 'settings.json']));
        file.load_contents_async(this._settingsCancel, (source, result) => {
            if (!this._alive || generation !== this._generation)
                return;
            try {
                const [, contents] = source.load_contents_finish(result);
                const config = JSON.parse(new TextDecoder().decode(contents));
                this._panelPosition = config.panel_position === 'left' ? 'left' : 'right';
                for (const [key, low, high, fallback] of [['font_size', 9, 20, 11], ['icon_size', 10, 32, 16], ['spacing', 2, 20, 5]])
                    this._appearance[key] = Number.isFinite(config[key]) ? Math.max(low, Math.min(high, Math.round(config[key]))) : fallback;
                this._applyPanelStyle();
                this._syncPosition(this._panelPosition);
            } catch (error) {
                // The API client reports unreadable configuration in the menu.
            }
        });
    }

    _applyPanelStyle() {
        this._label.set_style(`font-size: ${this._appearance.font_size}px; color: ${this._panelColor};`);
        this._icon.icon_size = this._appearance.icon_size;
        this._icon.set_style(`icon-size: ${this._appearance.icon_size}px; color: ${this._panelColor};`);
        this._indicatorBox.set_style(`spacing: ${this._appearance.spacing}px;`);
    }

    _syncPosition(position) {
        const target = position === 'left' ? Main.panel._leftBox : Main.panel._rightBox;
        const actor = this._button.container;
        const parent = actor.get_parent();
        if (!parent || parent === target)
            return;
        this._button.menu.close();
        parent.remove_child(actor);
        target.insert_child_at_index(actor, position === 'left' ? -1 : 1);
    }

    _watchConfig(directory) {
        this._monitor = directory.monitor_directory(Gio.FileMonitorFlags.NONE, null);
        this._monitor.connect('changed', () => {
            if (this._reloadTimer)
                GLib.source_remove(this._reloadTimer);
            this._reloadTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
                this._reloadTimer = 0;
                this._loadPreferences();
                this._paused = false;
                if (this._process)
                    this._reloadPending = true;
                else
                    this._pull();
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _schedule() {
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
        if (!this._alive || this._paused)
            return;
        const interval = this._state?.config.interval ?? 30;
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, interval, () => {
            this._timer = 0;
            this._pull();
            return GLib.SOURCE_REMOVE;
        });
    }

    _pull(manual = false) {
        if (!this._alive || this._process || (this._paused && !manual))
            return;
        this._paused = false;
        const generation = this._generation;
        try {
            this._process = Gio.Subprocess.new(['python3', this.dir.get_child('client.py').get_path()],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            this._process.communicate_utf8_async(null, null, (process, result) => {
                if (!this._alive || generation !== this._generation)
                    return;
                this._process = null;
                try {
                    const [, stdout] = process.communicate_utf8_finish(result);
                    if (!process.get_successful())
                        throw new Error('Falha ao iniciar o cliente Python.');
                    this._receive(JSON.parse(stdout));
                } catch (error) {
                    this._receive({ok: false, kind: 'connection', error: 'Não foi possível consultar o cliente local.'});
                }
                if (this._reloadPending) {
                    this._reloadPending = false;
                    this._pull();
                } else {
                    this._schedule();
                }
            });
        } catch (error) {
            this._process = null;
            this._receive({ok: false, kind: 'connection', error: 'Não foi possível iniciar o cliente Python.'});
            this._schedule();
        }
    }

    _receive(state) {
        if (!state.ok) {
            this._paused = ['auth', 'config', 'api'].includes(state.kind);
            this._label.text = 'Zabbix !';
            this._problems.removeAll();
            this._panelColor = '#a1a1aa';
            this._applyPanelStyle();
            this._status.label.text = state.error;
            this._status.label.clutter_text.line_wrap = true;
            this._status.label.set_style('max-width: 620px;');
            this._summary.label.text = this._state ? `Última consulta válida · ${new Date(this._state.checked_at * 1000).toLocaleTimeString('pt-BR')}` :
                this._paused ? 'Abra Configurar conexão ou tente Atualizar agora.' : 'Tentando novamente em 30 segundos.';
            return;
        }
        this._state = state;
        this._paused = false;
        const rows = state.problems;
        const identity = JSON.stringify([state.config.url, state.config.username, state.config.auth_mode, state.config.min_severity]);
        if (identity !== this._identity) {
            this._seen = null;
            this._identity = identity;
        }
        const changed = this._seen === null ? rows : rows.filter(row =>
            !this._seen.has(row.id) || row.severity > this._seen.get(row.id));
        if (state.config.notifications && changed.length) {
            const first = changed.reduce((highest, row) => row.severity > highest.severity ? row : highest);
            this._notify(this._seen === null ? `Zabbix: ${rows.length} problema(s) atual(is)` :
                `Zabbix: ${changed.length} alerta(s) novo(s) ou agravado(s)`,
            `${NAMES[first.severity]} · ${first.host}\n${first.name}${changed.length > 1 ? `\nE mais ${changed.length - 1} problema(s).` : ''}`);
        }
        this._seen = new Map(rows.map(row => [row.id, row.severity]));
        const severity = rows.length ? Math.max(...rows.map(row => row.severity)) : -1;
        const highestCount = rows.filter(row => row.severity === severity).length;
        this._label.text = rows.length ? `Zabbix ${rows.length} · ${highestCount} ${NAMES[severity].toLowerCase()}` : 'Zabbix OK';
        this._button.accessible_name = rows.length ? `${rows.length} problemas atuais. ${highestCount} com gravidade ${NAMES[severity]}.` : 'Zabbix: nenhum problema atual';
        this._panelColor = severity >= 0 ? COLORS[severity] : '#4ade80';
        this._applyPanelStyle();
        this._status.label.text = `${rows.length} problema(s) atual(is)`;
        this._summary.label.text = `Atualizado às ${new Date(state.checked_at * 1000).toLocaleTimeString('pt-BR')} · a cada ${state.config.interval}s`;
        this._problems.removeAll();
        if (!rows.length)
            this._problems.addMenuItem(new PopupMenu.PopupMenuItem('Nenhum problema atual neste filtro.', {reactive: false}));
        for (const row of rows.slice(0, 40)) {
            const age = Math.max(0, Math.floor((Date.now() / 1000 - row.clock) / 60));
            const duration = age < 60 ? `${age} min` : `${Math.floor(age / 60)}h ${age % 60}min`;
            const item = new PopupMenu.PopupBaseMenuItem({style_class: 'zabbix-problem-card'});
            item.set_style(`border-left: 3px solid ${COLORS[row.severity]};`);
            const content = new St.BoxLayout({vertical: true, x_expand: true, style_class: 'zabbix-problem-content'});
            const heading = new St.BoxLayout({style_class: 'zabbix-problem-heading'});
            item.label = new St.Label({text: row.host, x_expand: true, style_class: 'zabbix-problem-host'});
            heading.add_child(item.label);
            const badge = new St.Label({text: NAMES[row.severity], style_class: 'zabbix-severity'});
            badge.set_style(`color: ${COLORS[row.severity]};`);
            heading.add_child(badge);
            content.add_child(heading);
            const description = new St.Label({text: row.name, style_class: 'zabbix-problem-name'});
            description.clutter_text.line_wrap = true;
            content.add_child(description);
            content.add_child(new St.Label({text: `${duration}${row.acknowledged ? ' · Reconhecido' : ''}`, style_class: 'zabbix-summary'}));
            item.add_child(content);
            item.accessible_name = `${row.host}. ${NAMES[row.severity]}. ${row.name}. ${duration}.`;
            item.connect('activate', () => this._open(row.url));
            this._problems.addMenuItem(item);
        }
        if (rows.length > 40)
            this._problems.addAction(`Ver todos os ${rows.length} no Zabbix`, () => this._open(state.config.url + '/zabbix.php?action=problem.view'));
    }

    _notify(title, body) {
        if (!this._notificationSource) {
            const source = new MessageTray.Source({title: 'Alertas Zabbix', icon: this._brandIcon});
            source.connect('destroy', () => {
                if (this._notificationSource === source)
                    this._notificationSource = null;
            });
            this._notificationSource = source;
            Main.messageTray.add(source);
        }
        const notification = new MessageTray.Notification({source: this._notificationSource, title, body,
            gicon: this._brandIcon, isTransient: true});
        this._notificationSource.addNotification(notification);
        return notification;
    }

    _open(url) {
        try {
            Gio.AppInfo.launch_default_for_uri(url, global.create_app_launch_context(0, -1));
        } catch (error) {
            Main.notifyError('Alertas Zabbix', 'Não foi possível abrir o navegador.');
        }
    }

    _configure(appearance = false) {
        try {
            const args = ['python3', this.dir.get_child('configurar.py').get_path()];
            if (appearance)
                args.push('--appearance');
            const process = Gio.Subprocess.new(args, Gio.SubprocessFlags.NONE);
            process.wait_check_async(null, (child, result) => {
                try {
                    child.wait_check_finish(result);
                } catch (error) {
                    if (this._alive)
                        Main.notifyError('Alertas Zabbix', 'Não foi possível abrir a configuração. Confira as dependências.');
                }
            });
        } catch (error) {
            Main.notifyError('Alertas Zabbix', 'Não foi possível abrir a configuração.');
        }
    }

    disable() {
        this._alive = false;
        this._generation++;
        if (this._timer)
            GLib.source_remove(this._timer);
        if (this._reloadTimer)
            GLib.source_remove(this._reloadTimer);
        this._timer = this._reloadTimer = 0;
        this._monitor?.cancel();
        this._settingsCancel?.cancel();
        this._settingsCancel = null;
        this._monitor = null;
        this._notificationSource?.destroy();
        this._notificationSource = null;
        this._brandIcon = null;
        // Let an in-flight request finish its logout; it cannot update this generation.
        this._process = null;
        this._reloadPending = false;
        this._button?.destroy();
        this._button = null;
        this._state = null;
        this._seen = this._identity = null;
    }
}
