"""Exercise connection setup on the disposable GNOME test display."""
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extension'))
import configurar as module
from client import MonitorError, config_path, load_config
from gi.repository import GLib

folder = tempfile.TemporaryDirectory(prefix='zabbix-ui-config-')
os.environ['XDG_CONFIG_HOME'] = folder.name
vault = {}
calls = []
stage = 0
count = 0
failed = False
started = time.monotonic()
saved_bytes = None


def fake_secret(config, value=None):
    key = (config['url'], config['username'], config['auth_mode'])
    if value is None:
        return vault.get(key)
    vault[key] = value


class FakeAPI:
    def __init__(self, config):
        self.config = config

    def snapshot(self, secret):
        calls.append((self.config.copy(), secret))
        if secret == 'invalid-test-value':
            raise MonitorError('Credencial de teste recusada.', 'auth')
        return dict(problems=[{}, {}])


class TestApplication(module.Application):
    def __init__(self):
        super().__init__()
        self.set_application_id('org.gezer.AlertZabbix.Test')


app = TestApplication()


def check(value, message):
    global count
    count += 1
    if not value:
        raise AssertionError(message)


def exercise():
    global stage, failed, saved_bytes
    try:
        if time.monotonic() - started > 25:
            raise AssertionError('Connection UI test timed out')
        window = app.window
        if window is None or window.busy:
            return GLib.SOURCE_CONTINUE
        if stage == 0:
            check(window.get_icon_name() == 'org.gezer.AlertZabbix' and module.Gtk.IconTheme.get_for_display(window.get_display()).has_icon('org.gezer.AlertZabbix'),
                  'The application exposes its bundled desktop icon')
            check(window.url.get_text() == window.username.get_text() == '', 'First launch has no server or username')
            check(window.secret.get_text() == '', 'Credentials are never prefilled')
            window.start_operation(True)
            check(not window.busy and not calls and not vault, 'Missing address is rejected before network or keyring access')
            window.runtime_checked(6, 4)
            check(window.runtime_banner.get_revealed(), 'An older loaded extension shows the pending-update banner')
            check('versão anterior' in window.appearance_description.get_text(), 'Pending update does not promise immediate movement')
            window.pages.set_visible_child_name('appearance')
            check(not window.test_button.get_visible() and window.auto_save_note.get_visible(), 'Appearance page is independent of connection controls')
            window.position.set_selected(0)
            check(load_config()['panel_position'] == 'left' and not calls and not vault, 'Position saves without contacting API or keyring')
            check(window.preview_indicator.get_parent() is window.preview_left, 'Preview follows left position')
            check('próxima sessão' in window.preference_status.get_text(), 'Saving with old extension explains when position will apply')
            window.runtime_checked(6, 6)
            check(not window.runtime_banner.get_revealed(), 'Matching loaded version clears the pending-update banner')
            window.font_size.set_value(9)
            window.icon_size.set_value(10)
            window.spacing.set_value(2)
            window.window_font.set_value(12)
            saved = load_config()
            check((saved['font_size'], saved['icon_size'], saved['spacing'], saved['window_font_size']) == (9, 10, 2, 12), 'Size controls save without a connection')
            check(window.preview_icon.get_pixel_size() == 10 and window.preview_indicator.get_spacing() == 2, 'Preview reflects icon size and spacing')
            check(window._style_values['font_size'] == 9 and not calls and not vault, 'Font sizing does not contact API or keyring')
            window.theme.set_selected(1)
            check(load_config()['theme'] == 'light', 'Theme is saved immediately')
            window.theme.set_selected(0)
            window.pages.set_visible_child_name('connection')
            window.url.set_text('https://zabbix.example.test/zabbix')
            window.mode.set_selected(1)
            check(not window.username.get_visible() and window.secret.get_title() == 'Token de API', 'Token mode adapts the form')
            window.mode.set_selected(0)
            check(window.username.get_visible(), 'Password mode shows username')
            check('criptografada' in window.transport_note.get_text() and 'HTTP ·' not in window.transport_note.get_text(), 'Transport description follows the URL')
            window.username.set_text('test-user')
            window.secret.set_text('test-only-value')
            window.start_operation(False)
            stage = 1
        elif stage == 1:
            check(window.status.get_title() == 'Conexão confirmada', 'Test connection reports success')
            check(load_config()['url'] == '' and not vault, 'Testing does not persist connection or credentials')
            check(window.secret.get_text() == 'test-only-value', 'Testing preserves entry for a later save')
            window.start_operation(True)
            stage = 2
        elif stage == 2:
            check(window.status.get_title() == 'Conexão salva', 'Saving reports success')
            check(len(vault) == 1, 'Saving writes to keyring adapter')
            check(window.secret.get_text() == '', 'Successful save clears the credential field')
            saved_bytes = config_path().read_bytes()
            check(b'test-only-value' not in saved_bytes, 'Configuration file excludes credential')
            check(load_config()['username'] == 'test-user', 'Connection is saved outside code')
            check(load_config()['panel_position'] == 'left', 'Saving the connection preserves chosen position')
            check(load_config()['font_size'] == 9 and load_config()['icon_size'] == 10, 'Saving connection preserves chosen sizes')
            window.username.set_text('different-user')
            window.secret.set_text('invalid-test-value')
            window.start_operation(True)
            stage = 3
        elif stage == 3:
            check(window.status.get_title() == 'Não foi possível conectar', 'Invalid credential shows failure')
            check(config_path().read_bytes() == saved_bytes and len(vault) == 1, 'Failed save preserves the existing connection')
            check(window.secret.get_text() == 'invalid-test-value', 'Failed attempt leaves the input editable')
            window.close()
            app.activate()
            check(app.window.url.get_text() == 'https://zabbix.example.test/zabbix', 'Reopened window reads saved connection')
            check(app.window.username.get_text() == 'test-user' and app.window.secret.get_text() == '', 'Reopen preserves account and keeps credential hidden')
            check(app.window.position.get_selected() == 0 and load_config()['theme'] == 'dark', 'Position and theme survive reopening')
            check(app.window.font_size.get_value() == 9 and app.window.icon_size.get_value() == 10 and app.window.window_font.get_value() == 12, 'Sizes survive reopening')
            print(f'ALERT_ZABBIX_UI_OK: {count} verificações.', flush=True)
            app.quit()
            return GLib.SOURCE_REMOVE
    except Exception:
        failed = True
        traceback.print_exc()
        app.quit()
        return GLib.SOURCE_REMOVE
    return GLib.SOURCE_CONTINUE


GLib.timeout_add(100, exercise)
with patch.object(module, 'API', FakeAPI), patch.object(module, 'secret_access', fake_secret), \
        patch.object(module.ConfigurationWindow, 'check_runtime', lambda self: None):
    app.run(None)
folder.cleanup()
raise SystemExit(1 if failed else 0)
