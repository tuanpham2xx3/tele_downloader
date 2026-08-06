#!/usr/bin/env bash
# Script chạy Auto Course Downloader trên Ubuntu / Linux Server

PYTHON_BIN="python3"
SCRIPT_PATH="./telegram_media_downloader/auto_course_downloader.py"
OUTPUT_DIR="./downloads"
CHAT="@coursebusters_bot"

if [ -f "./.venv/bin/python" ]; then
    PYTHON_BIN="./.venv/bin/python"
fi

echo "🚀 Starting Telegram Auto Course Stream Downloader on Ubuntu..."
$PYTHON_BIN $SCRIPT_PATH -c "$CHAT" -o "$OUTPUT_DIR" "$@"
