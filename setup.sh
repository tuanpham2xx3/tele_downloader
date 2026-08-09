#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required." >&2
    exit 2
fi

if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-pip git curl unzip p7zip-full rclone
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    python3 -m venv "$ROOT/.venv"
fi
PYTHON_BIN="$ROOT/.venv/bin/python"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install rich requests==2.32.3 websockets==15.0.1 PyYAML

bash "$ROOT/setup-tdlib.sh"
"$PYTHON_BIN" "$ROOT/tdlib_backend.py" start

for role in acc1 acc2 acc3; do
    if ! ROLE="$role" "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path
from telegram_media_downloader.tdlib_client import load_account_id
load_account_id(os.environ['ROLE'], Path.cwd())
PY
    then
        echo "Login TDLib account for $role"
        "$PYTHON_BIN" "$ROOT/tdlib_admin.py" login "$role"
    fi
done

echo "TDLib environment and all three accounts are ready."
echo "Start: ./start-multi-pipeline.sh start"
