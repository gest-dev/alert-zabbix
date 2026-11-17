#!/usr/bin/env python3
"""Native connection preferences; credentials stay in the Ubuntu keyring."""
import threading
import sys
import json
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk
from client import API, DEFAULTS, MonitorError, SEVERITIES, load_config, normalize, save_config, save_preferences, secret_access

ICONS = Path(__file__).resolve().parent / 'icons'


class ConfigurationWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='Alertas Zabbix', default_width=700, default_height=780)
        icon_theme = Gtk.IconTheme.get_for_display(self.get_display())
        if str(ICONS) not in icon_theme.get_search_path():
            icon_theme.add_search_path(str(ICONS))
        self.set_icon_name('org.gezer.AlertZabbix')
        self.closed = False
        self.busy = False
        self._preferences_ready = False
        self._runtime_outdated = False
        self.connect('close-request', self.on_close)
        initial_error = ''
        try:
            config = load_config()
        except MonitorError as error:
            config = DEFAULTS.copy()
            initial_error = str(error)
        self._style_values = config.copy()

        self.add_css_class('zabbix-settings')
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(self.get_display(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._style_manager = Adw.StyleManager.get_default()
        self._theme_signal = self._style_manager.connect('notify::dark', lambda *_args: self.refresh_css())
        self.apply_theme(config['theme'])

        toolbar = Adw.ToolbarView()
        self.set_content(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='Alertas Zabbix', subtitle='Configuração'))
        toolbar.add_top_bar(header)
        self.runtime_banner = Adw.Banner(title='Atualização pendente: saia e entre na sessão para aplicar os ajustes da barra.', revealed=False)
        toolbar.add_top_bar(self.runtime_banner)
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        switcher = Gtk.StackSwitcher(stack=self.pages, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=10)
        toolbar.add_top_bar(switcher)
        toolbar.set_content(self.pages)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.pages.add_titled(scroll, 'connection', 'Conexão')
        clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480)
        scroll.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24)
        clamp.set_child(body)

        hero = Gtk.Box(spacing=18)
        icon = Gtk.Image.new_from_file(str(ICONS / 'org.gezer.AlertZabbix.png'))
        icon.set_pixel_size(56)
        icon.set_valign(Gtk.Align.CENTER)
        hero.append(icon)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        brand = Gtk.Label(label='ALERTAS ZABBIX', xalign=0)
        brand.add_css_class('zabbix-brand')
        titles.append(brand)
        title = Gtk.Label(label='Seu Zabbix, sempre à vista', xalign=0, wrap=True)
        title.add_css_class('title-1')
        titles.append(title)
        subtitle = Gtk.Label(label='Problemas de hosts ativos, com avisos enquanto você trabalha.', xalign=0, wrap=True)
        subtitle.add_css_class('dim-label')
        titles.append(subtitle)
        hero.append(titles)
        body.append(hero)

        state_group = Adw.PreferencesGroup()
        self.status = Adw.ActionRow(title='Conexão configurada' if config['url'] else 'Vamos conectar seu Zabbix',
                                    subtitle='Teste a conexão para conferir o acesso.' if config['url'] else 'Informe o endereço e escolha como entrar.')
        self.status.set_subtitle_lines(0)
        self.status_icon = Gtk.Image(icon_name='network-workgroup-symbolic')
        self.status.add_prefix(self.status_icon)
        self.spinner = Gtk.Spinner(visible=False)
        self.status.add_suffix(self.spinner)
        state_group.add(self.status)
        body.append(state_group)

        self.connection_group = Adw.PreferencesGroup(title='Seu servidor', description='Use o mesmo endereço que você abre no navegador.')
        body.append(self.connection_group)
        self.url = Adw.EntryRow(title='Endereço do Zabbix', text=config['url'], input_purpose=Gtk.InputPurpose.URL)
        self.mode = Adw.ComboRow(title='Entrar com', model=Gtk.StringList.new(['Usuário e senha', 'Token de API']),
                                 selected=int(config['auth_mode'] == 'token'))
        self.username = Adw.EntryRow(title='Usuário do Zabbix', text=config['username'])
        self.secret = Adw.PasswordEntryRow(title='Senha')
        for row in (self.url, self.mode, self.username, self.secret):
            self.connection_group.add(row)
        self.credential_note = Gtk.Label(label='Senha e token ficam no chaveiro do Ubuntu. Ao editar a mesma conexão, deixe o campo vazio para manter a credencial salva.',
                                         xalign=0, wrap=True)
        self.credential_note.add_css_class('dim-label')
        body.append(self.credential_note)
        self.transport_note = Gtk.Label(xalign=0, wrap=True)
        self.transport_note.add_css_class('dim-label')
        body.append(self.transport_note)
        self.mode.connect('notify::selected', self.update_fields)
        self.url.connect('changed', self.connection_edited)
        self.username.connect('changed', self.connection_edited)
        self.secret.connect('changed', self.connection_edited)
        self.update_fields()

        about = Gtk.Label(label='Compatível com Zabbix 6.4 · Consulta somente os problemas atuais', xalign=0, wrap=True)
        about.add_css_class('dim-label')
        body.append(about)
        self.build_appearance_page(config)

        action_bar = Gtk.ActionBar()
        buttons = Gtk.Box(spacing=12)
        self.test_button = Gtk.Button(label='Testar conexão')
        self.test_button.connect('clicked', lambda *_args: self.start_operation(False))
        self.save_button = Gtk.Button(label='Salvar conexão')
        self.save_button.add_css_class('suggested-action')
        self.save_button.connect('clicked', lambda *_args: self.start_operation(True))
        buttons.append(self.test_button)
        buttons.append(self.save_button)
        self.close_button = Gtk.Button(label='Fechar', visible=False)
        self.close_button.connect('clicked', lambda *_args: self.close())
        buttons.append(self.close_button)
        self.auto_save_note = Gtk.Label(label='Alterações salvas automaticamente', visible=False)
        self.auto_save_note.add_css_class('dim-label')
        action_bar.pack_start(self.auto_save_note)
        action_bar.pack_end(buttons)
        toolbar.add_bottom_bar(action_bar)
        self.pages.connect('notify::visible-child-name', self.page_changed)
        self._preferences_ready = True
        if initial_error:
            self.set_status('Confira a configuração', initial_error, 'error')
        self.check_runtime()

    def check_runtime(self):
        def worker():
            try:
                installed = json.loads(Path(__file__).with_name('metadata.json').read_text())['version']
                proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                    None, 'org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions', 'org.gnome.Shell.Extensions', None)
                result = proxy.call_sync('GetExtensionInfo', GLib.Variant('(s)', ('alert-zabbix@gezer.local',)),
                                         Gio.DBusCallFlags.NONE, 3000, None)
                info = result.unpack()[0]
                loaded = info.get('version')
                if loaded is not None:
                    GLib.idle_add(self.runtime_checked, installed, loaded)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def runtime_checked(self, installed, loaded):
        if self.closed:
            return GLib.SOURCE_REMOVE
        self._runtime_outdated = installed != loaded
        self.runtime_banner.set_revealed(self._runtime_outdated)
        self.appearance_description.set_text(
            'Sua escolha fica salva. A barra ainda usa a versão anterior; saia e entre na sessão para aplicar posição e tamanhos.'
            if self._runtime_outdated else 'Escolha onde o indicador aparece e como receber os avisos.\nOs ajustes são aplicados na hora.')
        if self._runtime_outdated:
            self.preference_status.set_text('Preferências salvas para a próxima sessão. A prévia mostra a escolha, não o estado atual da barra.')
        return GLib.SOURCE_REMOVE

    def apply_theme(self, theme):
        self._style_manager.set_color_scheme({'dark': Adw.ColorScheme.FORCE_DARK, 'light': Adw.ColorScheme.FORCE_LIGHT,
                                              'system': Adw.ColorScheme.DEFAULT}[theme])
        self.refresh_css()

    def refresh_css(self):
        dark = self._style_manager.get_dark()
        background, surface, edge, muted = ('#101411', '#171e19', '#2b382f', '#a5b1a8') if dark else ('#f4f8f5', '#ffffff', '#d5dfd8', '#526258')
        accent = '#4ade80' if dark else '#16713a'
        self._css.load_from_string(f'''
            window.zabbix-settings {{ background: {background}; font-size: {self._style_values['window_font_size']}px; --accent-bg-color: #22c55e; --accent-color: {accent}; --accent-fg-color: #101411; }}
            .zabbix-settings headerbar, .zabbix-settings actionbar {{ background: {background}; }}
            .zabbix-settings .accent, .zabbix-settings .zabbix-brand {{ color: {accent}; }}
            .zabbix-settings .zabbix-brand {{ font-size: 11px; font-weight: 800; letter-spacing: 2px; }}
            .zabbix-settings button.suggested-action {{ background: #22c55e; color: #101411; }}
            .zabbix-settings list.boxed-list {{ background: {surface}; border: 1px solid {edge}; border-radius: 14px; }}
            .zabbix-settings .dim-label {{ color: {muted}; opacity: 1; }}
            .zabbix-settings .zabbix-bar-preview {{ background: {surface}; border: 1px solid {edge}; border-radius: 14px; padding: 18px 14px; }}
            .zabbix-settings .zabbix-preview-indicator {{ background: alpha({accent}, 0.15); color: {accent}; border-radius: 8px; padding: 7px 10px; font-weight: bold; }}
            .zabbix-settings .zabbix-preview-value {{ font-size: {self._style_values['font_size']}px; }}
        ''')

    def build_appearance_page(self, config):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.pages.add_titled(scroll, 'appearance', 'Barra e avisos')
        clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480)
        scroll.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24)
        clamp.set_child(body)
        title = Gtk.Label(label='Do seu jeito', xalign=0)
        title.add_css_class('title-1')
        body.append(title)
        self.appearance_description = Gtk.Label(label='Escolha onde o indicador aparece e como receber os avisos.\nOs ajustes são aplicados na hora.', xalign=0, wrap=True)
        self.appearance_description.add_css_class('dim-label')
        body.append(self.appearance_description)
        preview_group = Adw.PreferencesGroup(title='Prévia da posição')
        self.preview = Gtk.Box(spacing=14)
        self.preview.add_css_class('zabbix-bar-preview')
        self.preview_left = Gtk.Box(spacing=10, hexpand=True)
        self.preview_left.append(Gtk.Label(label='Atividades'))
        self.preview_right = Gtk.Box(spacing=10, hexpand=True, halign=Gtk.Align.END)
        self.preview_right.append(Gtk.Image(icon_name='network-wired-symbolic'))
        self.preview_indicator = Gtk.Box(spacing=config['spacing'])
        self.preview_icon = Gtk.Image.new_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(str(ICONS / 'alert-zabbix-symbolic.svg'))))
        self.preview_icon.set_pixel_size(config['icon_size'])
        self.preview_value = Gtk.Label(label='Zabbix')
        self.preview_value.add_css_class('zabbix-preview-value')
        self.preview_indicator.append(self.preview_icon)
        self.preview_indicator.append(self.preview_value)
        self.preview_indicator.add_css_class('zabbix-preview-indicator')
        self.preview.append(self.preview_left)
        self.preview.append(Gtk.Label(label='Relógio'))
        self.preview.append(self.preview_right)
        preview_group.add(self.preview)
        body.append(preview_group)
        self.appearance_group = Adw.PreferencesGroup(title='Barra do Ubuntu', description='Diminua a letra e o ícone para ocupar menos espaço.')
        body.append(self.appearance_group)
        self.position = Adw.ComboRow(title='Posição na barra do Ubuntu', model=Gtk.StringList.new(['Esquerda', 'Direita']),
                                     selected=['left', 'right'].index(config['panel_position']))
        self.theme = Adw.ComboRow(title='Tema da janela', model=Gtk.StringList.new(['Escuro', 'Claro', 'Seguir sistema']),
                                  selected=['dark', 'light', 'system'].index(config['theme']))
        self.appearance_group.add(self.position)
        self.window_font = Adw.SpinRow(title='Letra da janela (px)', adjustment=Gtk.Adjustment(value=config['window_font_size'], lower=11, upper=18, step_increment=1))
        self.font_size = Adw.SpinRow(title='Letra na barra (px)', adjustment=Gtk.Adjustment(value=config['font_size'], lower=9, upper=20, step_increment=1))
        self.icon_size = Adw.SpinRow(title='Ícone na barra (px)', adjustment=Gtk.Adjustment(value=config['icon_size'], lower=10, upper=32, step_increment=2))
        self.spacing = Adw.SpinRow(title='Espaço entre ícone e texto (px)', adjustment=Gtk.Adjustment(value=config['spacing'], lower=2, upper=20, step_increment=1))
        for row in (self.font_size, self.icon_size, self.spacing):
            self.appearance_group.add(row)
        self.window_group = Adw.PreferencesGroup(title='Janela do aplicativo')
        self.window_group.add(self.theme)
        self.window_group.add(self.window_font)
        body.append(self.window_group)
        self.monitor_group = Adw.PreferencesGroup(title='Monitoramento', description='Somente problemas atuais de hosts com monitoramento habilitado.')
        body.append(self.monitor_group)
        self.interval = Adw.SpinRow(title='Atualização em segundos', adjustment=Gtk.Adjustment(value=config['interval'], lower=30, upper=900, step_increment=15))
        self.severity = Adw.ComboRow(title='Mostrar a partir de', model=Gtk.StringList.new(SEVERITIES), selected=config['min_severity'])
        self.notifications = Adw.SwitchRow(title='Avisos na tela', subtitle='Problemas novos e aumento de gravidade', active=config['notifications'])
        for row in (self.interval, self.severity, self.notifications):
            self.monitor_group.add(row)
        self.preference_status = Gtk.Label(label='Sua conexão é preservada ao mudar a aparência.', xalign=0, wrap=True)
        self.preference_status.add_css_class('dim-label')
        body.append(self.preference_status)
        for row, prop in ((self.position, 'selected'), (self.theme, 'selected'), (self.interval, 'value'),
                          (self.severity, 'selected'), (self.notifications, 'active'), (self.font_size, 'value'),
                          (self.icon_size, 'value'), (self.spacing, 'value'), (self.window_font, 'value')):
            row.connect('notify::' + prop, self.preferences_changed)
        self.update_preview()

    def preference_values(self):
        return dict(panel_position=['left', 'right'][self.position.get_selected()],
                    theme=['dark', 'light', 'system'][self.theme.get_selected()],
                    interval=self.interval.get_value(), min_severity=self.severity.get_selected(),
                    notifications=self.notifications.get_active(), font_size=self.font_size.get_value(),
                    icon_size=self.icon_size.get_value(), spacing=self.spacing.get_value(), window_font_size=self.window_font.get_value())

    def update_preview(self):
        parent = self.preview_indicator.get_parent()
        if parent:
            parent.remove(self.preview_indicator)
        (self.preview_left if self.position.get_selected() == 0 else self.preview_right).append(self.preview_indicator)
        self.preview_icon.set_pixel_size(int(self.icon_size.get_value()))
        self.preview_indicator.set_spacing(int(self.spacing.get_value()))

    def preferences_changed(self, *_args):
        if not self._preferences_ready or self.busy:
            return
        try:
            config = save_preferences(self.preference_values())
            self._style_values = config
            self.apply_theme(config['theme'])
            self.update_preview()
            self.preference_status.set_text('Preferências salvas para a próxima sessão. Saia e entre no Ubuntu para carregar a atualização.'
                                           if self._runtime_outdated else 'Preferências salvas. A posição e os tamanhos mudam assim que a extensão recebe o ajuste.')
        except (MonitorError, OSError) as error:
            self.preference_status.set_text(str(error))

    def page_changed(self, *_args):
        appearance = self.pages.get_visible_child_name() == 'appearance'
        self.set_title('Alertas Zabbix · Barra e avisos' if appearance else 'Alertas Zabbix')
        self.test_button.set_visible(not appearance)
        self.save_button.set_visible(not appearance)
        self.close_button.set_visible(appearance)
        self.auto_save_note.set_visible(appearance)

    def update_fields(self, *_args):
        token = bool(self.mode.get_selected())
        self.username.set_visible(not token)
        self.secret.set_title('Token de API' if token else 'Senha do Zabbix')
        self.connection_edited()

    def connection_edited(self, *_args):
        url = self.url.get_text().strip().lower()
        self.transport_note.set_visible(bool(url))
        self.transport_note.set_text('HTTPS · conexão criptografada com o servidor.' if url.startswith('https://') else
                                     'HTTP · a conexão não é criptografada.' if url.startswith('http://') else
                                     'Inclua https:// ou http:// no endereço.')
        if hasattr(self, 'test_button') and not self.busy:
            self.set_status('Conexão editada', 'Teste ou salve para conferir o acesso.')

    def set_status(self, title, subtitle, kind=None):
        self.status.set_title(title)
        self.status.set_subtitle(subtitle)
        for name in ('success', 'error'):
            self.status_icon.remove_css_class(name)
        self.status_icon.set_from_icon_name({'success': 'emblem-ok-symbolic', 'error': 'dialog-error-symbolic'}.get(kind, 'network-workgroup-symbolic'))
        if kind:
            self.status_icon.add_css_class(kind)

    def start_operation(self, save):
        if self.busy:
            return
        try:
            config = normalize(dict(url=self.url.get_text(), username=self.username.get_text(),
                                    auth_mode='token' if self.mode.get_selected() else 'password',
                                    **self.preference_values()), require_connection=True)
        except MonitorError as error:
            self.set_status('Confira os campos', str(error), 'error')
            return
        credential_input = self.secret.get_text()
        self.busy = True
        self.connection_group.set_sensitive(False)
        self.monitor_group.set_sensitive(False)
        self.appearance_group.set_sensitive(False)
        self.window_group.set_sensitive(False)
        self.test_button.set_sensitive(False)
        self.save_button.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.set_status('Verificando conexão…', 'Consultando o Zabbix com os dados informados.')
        application = self.get_application()
        application.hold()

        def worker():
            success = False
            try:
                credential = credential_input or secret_access(config)
                state = API(config).snapshot(credential)
                if save:
                    if credential_input:
                        secret_access(config, credential_input)
                    save_config(config)
                message = f"{len(state['problems'])} problema(s) atual(is) no filtro. " + ('O indicador já pode usar esta conexão.' if save else 'Os dados ainda não foram salvos.')
                success = True
            except (MonitorError, OSError) as error:
                message = str(error)
            except Exception:
                message = 'Não foi possível concluir a operação. Confira os dados e tente novamente.'
            GLib.idle_add(self.finished, application, success, save, message)
        threading.Thread(target=worker, daemon=True).start()

    def finished(self, application, success, saved, message):
        self.busy = False
        if not self.closed:
            self.connection_group.set_sensitive(True)
            self.monitor_group.set_sensitive(True)
            self.appearance_group.set_sensitive(True)
            self.window_group.set_sensitive(True)
            self.test_button.set_sensitive(True)
            self.save_button.set_sensitive(True)
            self.spinner.stop()
            self.spinner.set_visible(False)
            if success and saved:
                self.secret.set_text('')
            self.set_status('Conexão salva' if success and saved else 'Conexão confirmada' if success else 'Não foi possível conectar',
                            message, 'success' if success else 'error')
        application.release()
        return GLib.SOURCE_REMOVE

    def on_close(self, *_args):
        self.closed = True
        self._style_manager.disconnect(self._theme_signal)
        Gtk.StyleContext.remove_provider_for_display(self.get_display(), self._css)
        application = self.get_application()
        if application.window is self:
            application.window = None
        return False


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id='org.gezer.AlertZabbix', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option('appearance', 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, 'Abrir aparência e posição da barra', None)
        self.window = None

    def do_command_line(self, command_line):
        self.activate()
        self.window.pages.set_visible_child_name('appearance' if command_line.get_options_dict().contains('appearance') else 'connection')
        return 0

    def do_activate(self):
        if self.window is None:
            self.window = ConfigurationWindow(self)
        self.window.present()


if __name__ == '__main__':
    Application().run(sys.argv)
