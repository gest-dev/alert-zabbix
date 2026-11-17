#!/usr/bin/env bash
set -euo pipefail
pasta="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$pasta/tests/test_client.py"
python3 - "$pasta" <<'PY'
import ast
from pathlib import Path
import sys
for path in Path(sys.argv[1]).rglob('*.py'):
    ast.parse(path.read_text(), filename=str(path))
print('Sintaxe Python validada.')
PY
mkdir -p "$pasta/dist"
gnome-extensions pack --force --extra-source=client.py --extra-source=configurar.py --extra-source=icons \
    --out-dir="$pasta/dist" "$pasta/extension"
echo "Pacote pronto: $pasta/dist/alert-zabbix@gezer.local.shell-extension.zip"
