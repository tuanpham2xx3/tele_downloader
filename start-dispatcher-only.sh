#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/.runtime"
PID_FILE="$RUNTIME/pids/dispatcher.pid"
PYTHON_BIN="$ROOT/.venv/bin/python"
RCLONE_DEST="${RCLONE_PARENT_FOLDER:-gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:}"
RELAY_GROUP_ACC2="${RELAY_GROUP_ACC2:--5040203514}"

cd "$ROOT"
mkdir -p "$RUNTIME/pids"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Dispatcher already running PID=$(cat "$PID_FILE")"
    exit 0
fi
if [ -f "$RUNTIME/tdlib.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$RUNTIME/tdlib.env"
    set +a
fi

PYTHONUTF8=1 PYTHONIOENCODING=utf-8 nohup "$PYTHON_BIN" -u \
    telegram_media_downloader/course_pipeline.py \
    -r "$RCLONE_DEST" -p 5000 --relay-acc2 "$RELAY_GROUP_ACC2" --dispatcher-only \
    >> "$RUNTIME/dispatcher.stdout.log" 2>> "$RUNTIME/dispatcher.stderr.log" &
pid=$!
echo "$pid" > "$PID_FILE"
sleep 3
kill -0 "$pid" 2>/dev/null || {
    echo "Dispatcher failed; check .runtime/dispatcher.stderr.log" >&2
    exit 1
}
echo "Dispatcher-only started PID=$pid -> acc2 relay $RELAY_GROUP_ACC2"
