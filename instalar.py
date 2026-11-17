#!/usr/bin/env python3
"""Install this extension in the current user's GNOME session."""
from datetime import datetime
import os
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys

UUID = 'alert-zabbix@gezer.local'


def main():
    project = Path(__file__).resolve().parent
    for command in ('gnome-shell', 'gnome-extensions', 'gjs', 'python3'):
        if not shutil.which(command):
            raise RuntimeError('Comando necessário: ' + command)
    import gi
    for name, version in [('Gtk', '4.0'), ('Adw', '1'), ('Secret', '1')]:
        gi.require_version(name, version)
        __import__('gi.repository', fromlist=[name])
    if not subprocess.check_output(['gnome-shell', '--version'], text=True).startswith('GNOME Shell 50.'):
        raise RuntimeError('Esta extensão requer GNOME 50.')
    archive = project / 'dist' / (UUID + '.shell-extension.zip')
    if not archive.is_file():
        raise RuntimeError('Execute antes: bash empacotar.sh')
    data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    destination = data / 'gnome-shell/extensions' / UUID
    update = destination.exists()
    backup_root = data / 'alert-zabbix/backups'
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    legacy_backups = project / 'backups'
    if legacy_backups.is_dir():
        migrated = backup_root / ('legacy-project-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.move(str(legacy_backups), str(migrated))
        print('Backups anteriores preservados fora do projeto:', migrated)
    if update:
        backup = backup_root / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        shutil.copytree(destination, backup)
        print('Backup:', backup)
    subprocess.run(['gnome-extensions', 'install', *(['--force'] if update else []), str(archive)], check=True)
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    applications = data / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    (applications / 'org.gezer.AlertZabbix.desktop').write_text(
        '[Desktop Entry]\nType=Application\nName=Alertas Zabbix\n'
        'Comment=Configurar os alertas do Zabbix na barra do Ubuntu\n'
        f'Exec={quote(sys.executable)} {quote(destination / "configurar.py")}\n'
        f'Icon={destination / "icons/org.gezer.AlertZabbix.png"}\nTerminal=false\nCategories=Utility;Monitor;\n')
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(applications)], capture_output=True, check=False)
    subprocess.run(['gjs', '-c', """
const Gio = imports.gi.Gio;
const settings = new Gio.Settings({schema_id: 'org.gnome.shell'});
const uuid = 'alert-zabbix@gezer.local';
const enabled = settings.get_strv('enabled-extensions');
if (!enabled.includes(uuid) && !settings.set_strv('enabled-extensions', [...enabled, uuid]))
    throw new Error('Não foi possível salvar a ativação');
if (!settings.set_strv('disabled-extensions', settings.get_strv('disabled-extensions').filter(item => item !== uuid)))
    throw new Error('Não foi possível atualizar a ativação');
Gio.Settings.sync();
"""], check=True)
    subprocess.run(['gnome-extensions', 'enable', UUID], capture_output=True, check=False)
    print('Alertas Zabbix instalado. Abra pelo menu de aplicativos para configurar.')
    info = subprocess.run(['gnome-extensions', 'info', UUID], env={**os.environ, 'LC_ALL': 'C'},
                          capture_output=True, text=True, check=False)
    loaded = re.search(r'^\s*Version:\s*(\d+)\s*$', info.stdout, re.MULTILINE)
    installed = json.loads((destination / 'metadata.json').read_text())['version']
    if loaded and int(loaded[1]) != installed:
        print(f'A barra ainda executa a versão {loaded[1]}; a versão {installed} está instalada.')
        print('A atualização da barra requer sair e entrar na sessão. Seus ajustes de posição e tamanho estão preservados.')
    else:
        print('Se o indicador ainda não aparecer, salve seu trabalho, saia da sessão e entre novamente.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ImportError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Instalação interrompida:', error, file=sys.stderr)
        sys.exit(1)
