#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
RUNTIME="$ROOT/.runtime"
PID_DIR="$RUNTIME/pids"
STATE="$RUNTIME/pipeline-state.json"
ACTION="${1:-start}"
RCLONE_DEST="${RCLONE_PARENT_FOLDER:-gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:}"
RELAY_GROUP_ACC2="${RELAY_GROUP_ACC2:--5040203514}"
RELAY_GROUP_ACC3="${RELAY_GROUP_ACC3:--5281140814}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then PYTHON_BIN="$ROOT/.venv/bin/python"; fi

mkdir -p "$PID_DIR"

alive() {
    local pid="$1"
    kill -0 "$pid" 2>/dev/null
}

status_one() {
    local name="$1" pid_file="$PID_DIR/$1.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid="$(cat "$pid_file")"
        if alive "$pid"; then
            printf '%-9s UP   PID=%s\n' "$name" "$pid"
            return
        fi
    fi
    printf '%-9s DOWN\n' "$name"
}

stop_one() {
    local name="$1" pid_file="$PID_DIR/$1.pid"
    [ -f "$pid_file" ] || return 0
    local pid
    pid="$(cat "$pid_file")"
    if alive "$pid"; then
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            alive "$pid" || break
            sleep 0.25
        done
        alive "$pid" && kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
}

if [ "$ACTION" = "status" ]; then
    "$PYTHON_BIN" tdlib_backend.py status || true
    for name in acc1 acc2 acc3 monitor; do status_one "$name"; done
    exit 0
fi

if [ "$ACTION" = "stop" ]; then
    for name in monitor acc3 acc2 acc1; do stop_one "$name"; done
    rm -f "$STATE"
    "$PYTHON_BIN" tdlib_backend.py stop
    echo "Native TDLib pipelines stopped."
    exit 0
fi

if [ "$ACTION" != "start" ]; then
    echo "Usage: $0 [start|status|stop]" >&2
    exit 2
fi

for name in acc1 acc2 acc3 monitor; do
    if [ -f "$PID_DIR/$name.pid" ] && alive "$(cat "$PID_DIR/$name.pid")"; then
        echo "$name is already running; use '$0 status' or '$0 stop'." >&2
        exit 2
    fi
done

if [ ! -f "$RUNTIME/tdlib/telegram-files.jar" ]; then
    bash "$ROOT/setup-tdlib.sh"
fi

"$PYTHON_BIN" -c "import requests, websockets, rich"
"$PYTHON_BIN" tdlib_backend.py start
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
from telegram_media_downloader.tdlib_client import load_account_id
root = Path.cwd()
for role in ('acc1', 'acc2', 'acc3'):
    print(f'{role}={load_account_id(role, root)}')
PY

command -v rclone >/dev/null 2>&1 || { echo "rclone is required" >&2; exit 2; }
command -v 7z >/dev/null 2>&1 || { echo "7z is required (apt install p7zip-full)" >&2; exit 2; }

for port in 5000 5001 5002 5003; do
    if command -v lsof >/dev/null 2>&1 && lsof -ti "tcp:$port" >/dev/null 2>&1; then
        echo "Port $port is already in use." >&2
        exit 2
    fi
done

"$PYTHON_BIN" telegram_media_downloader/recover_pipeline_state.py
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

nohup "$PYTHON_BIN" -u telegram_media_downloader/course_pipeline.py \
    -r "$RCLONE_DEST" -p 5000 \
    --relay-acc2 "$RELAY_GROUP_ACC2" --relay-acc3 "$RELAY_GROUP_ACC3" \
    >> "$RUNTIME/pipeline_acc1.stdout.log" 2>> "$RUNTIME/pipeline_acc1.stderr.log" &
ACC1_PID=$!
echo "$ACC1_PID" > "$PID_DIR/acc1.pid"

nohup "$PYTHON_BIN" -u telegram_media_downloader/relay_pipeline.py \
    --session pyrogram_acc2 --group "$RELAY_GROUP_ACC2" \
    --rclone-dest "$RCLONE_DEST" --port 5001 \
    >> pipeline_acc2.log 2>> "$RUNTIME/pipeline_acc2.stderr.log" &
ACC2_PID=$!
echo "$ACC2_PID" > "$PID_DIR/acc2.pid"

nohup "$PYTHON_BIN" -u telegram_media_downloader/relay_pipeline.py \
    --session pyrogram_acc3 --group "$RELAY_GROUP_ACC3" \
    --rclone-dest "$RCLONE_DEST" --port 5002 \
    >> pipeline_acc3.log 2>> "$RUNTIME/pipeline_acc3.stderr.log" &
ACC3_PID=$!
echo "$ACC3_PID" > "$PID_DIR/acc3.pid"

export ACC1_PID ACC2_PID ACC3_PID STATE
"$PYTHON_BIN" - <<'PY'
import json, os, time
from pathlib import Path
rows = [
    {'Name': 'acc1', 'Pid': int(os.environ['ACC1_PID']), 'Script': 'course_pipeline.py', 'Port': 5000},
    {'Name': 'acc2', 'Pid': int(os.environ['ACC2_PID']), 'Script': 'relay_pipeline.py', 'Port': 5001},
    {'Name': 'acc3', 'Pid': int(os.environ['ACC3_PID']), 'Script': 'relay_pipeline.py', 'Port': 5002},
]
for row in rows: row['StartedAt'] = time.time()
Path(os.environ['STATE']).write_text(json.dumps(rows, indent=2), encoding='utf-8')
PY

nohup "$PYTHON_BIN" -u monitor_windows.py \
    >> "$RUNTIME/pipeline_monitor.stdout.log" 2>> "$RUNTIME/pipeline_monitor.stderr.log" &
MONITOR_PID=$!
echo "$MONITOR_PID" > "$PID_DIR/monitor.pid"

sleep 5
failed=0
for name in acc1 acc2 acc3 monitor; do
    pid="$(cat "$PID_DIR/$name.pid")"
    if ! alive "$pid"; then
        echo "$name failed to start; check .runtime logs." >&2
        failed=1
    fi
done
[ "$failed" -eq 0 ] || exit 1

echo "Three TDLib accounts are running natively on Ubuntu."
echo "Dashboard: http://127.0.0.1:5000"
"$0" status
