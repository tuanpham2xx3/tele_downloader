#!/usr/bin/env bash
# Script khởi chạy quy trình tự động hóa Telegram Course Pipeline trên Ubuntu #!/bin/bash
set -e

PYTHON_BIN="python3"
SCRIPT_PATH="./telegram_media_downloader/course_pipeline.py"
RCLONE_DEST="gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"
PORT=5000

if [ -f "./.venv/bin/python" ]; then
    PYTHON_BIN="./.venv/bin/python"
fi

echo "🚀 Khởi chạy Telegram Course Pipeline ngầm (nohup)..."

# Khởi chạy Cloudflare Tunnel ngầm nếu có file cloudflared
if [ -f "./cloudflared" ]; then
    echo "🌐 Khởi chạy Cloudflare Tunnel ngầm..."
    nohup ./cloudflared tunnel --url http://localhost:$PORT > cloudflared.log 2>&1 &
    sleep 3
    if [ -f "cloudflared.log" ]; then
        URL=$(grep -o "https://[a-zA-Z0-9-]*\.trycloudflare\.com" cloudflared.log | tail -n 1)
        if [ -n "$URL" ]; then
            echo "=========================================================="
            echo "🌐 Web Log Monitor Public URL: $URL"
            echo "=========================================================="
        fi
    fi
fi

# Khởi chạy Pipeline ngầm bằng nohup
nohup $PYTHON_BIN $SCRIPT_PATH -r "$RCLONE_DEST" -p "$PORT" "$@" > pipeline.log 2>&1 &

echo "✔ Pipeline đã được khởi chạy ngầm THÀNH CÔNG!"
echo "📊 Bạn có thể xem nhật ký thực thi tại: pipeline.log"
echo "👉 Dùng lệnh: tail -f pipeline.log để xem log realtime trong terminal!"
