#!/bin/sh
set -eu
CADBOT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$CADBOT_ROOT/.venv/bin/python" ]; then
  echo "Missing .venv. Create it with python3 -m venv .venv before installing the CLI bridge." >&2
  exit 1
fi
exec "$CADBOT_ROOT/.venv/bin/python" "$CADBOT_ROOT/scripts/install_addin.py" "$@"
