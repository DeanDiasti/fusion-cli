#!/bin/sh
set -eu
CADBOT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$CADBOT_ROOT/.venv/bin/python" ]; then
  echo "Missing .venv. Create it and install requirements.txt before installing CadBot." >&2
  exit 1
fi
"$CADBOT_ROOT/.venv/bin/python" -c 'import openai_codex'
exec "$CADBOT_ROOT/.venv/bin/python" "$CADBOT_ROOT/scripts/install_addin.py" "$@"
