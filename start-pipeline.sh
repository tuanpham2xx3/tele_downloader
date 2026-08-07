#!/usr/bin/env bash
# Script khởi chạy quy trình tự động hóa Telegram Course Pipeline trên Ubuntu / Linux

PYTHON_BIN="python3"
SCRIPT_PATH="./telegram_media_downloader/course_pipeline.py"
RCLONE_DEST="gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"
PORT=5000

if [ -f "./.venv/bin/python" ]; then
    PYTHON_BIN="./.venv/bin/python"
fi

echo "🚀 Launching Telegram Course Pipeline Automator on Ubuntu..."
echo "📊 Real-time Log Monitor available at: http://YOUR_UBUNTU_IP:$PORT"

$PYTHON_BIN $SCRIPT_PATH -r "$RCLONE_DEST" -p $PORT "$@"
