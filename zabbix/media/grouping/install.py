#!/usr/bin/env python3
"""Instala a fila local no servidor Zabbix; não altera mídias nem envia testes."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Execute no servidor como root ou com sudo.')
    pwd.getpwnam('zabbix')
    gid = grp.getgrnam('zabbix').gr_gid
    config = json.loads(args.config.read_text())
    # Validar antes de alterar arquivos de instalação.
    from service import Queue
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        Queue(Path(temp) / 'check.sqlite3', config)
    source = Path(__file__).resolve().parent
    directory = Path('/opt/zabbix-message-group')
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    target_config = Path('/etc/zabbix/message-group.json')
    if target_config.exists() and json.loads(target_config.read_text()) != config:
        # Não trocar rotas/tokens silenciosamente com uma fila em andamento.
        raise SystemExit('Configuração diferente já instalada; preserve a fila e revise a migração.')
    backup = Path('/var/backups/zabbix-message-group') / str(time.time_ns())
    backup.mkdir(mode=0o700, parents=True)
    os.chmod(backup.parent, 0o700)
    for name in ('service-config.json', 'plan.json', 'media-before.json'):
        original = args.config if name == 'service-config.json' else args.config.parent / name
        if original.exists():
            shutil.copyfile(original, backup / name)
            os.chmod(backup / name, 0o600)
    shutil.copyfile(source / 'service.py', directory / 'service.py')
    os.chmod(directory / 'service.py', 0o644)
    fd = os.open(target_config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, 'w') as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.chown(target_config, 0, gid)
    os.chmod(target_config, 0o640)
    unit = Path('/etc/systemd/system/zabbix-message-group.service')
    shutil.copyfile(source / unit.name, unit)
    os.chmod(unit, 0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', unit.name], check=True)
    subprocess.run(['systemctl', 'restart', unit.name], check=True)
    request = urllib.request.Request('http://127.0.0.1:8791/health',
                                     headers={'Authorization': 'Bearer ' + config['token']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(20):
        try:
            with opener.open(request, timeout=2) as response:
                if json.load(response).get('ok') is True:
                    print('Fila instalada e saudável. Backup privado em ' + str(backup))
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise SystemExit('Fila sem resposta saudável; mantenha as mídias originais até corrigir.')


if __name__ == '__main__':
    main()
