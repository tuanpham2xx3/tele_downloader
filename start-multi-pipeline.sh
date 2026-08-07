#!/usr/bin/env bash
# start-multi-pipeline.sh
# Khởi chạy đồng thời 3 pipeline song song (Acc 1 + Acc 2 + Acc 3)
# Acc 1: Quét bot, tải trực tiếp khóa 1,4,7..., forward khóa 2,5,8... sang Acc 2 và khóa 3,6,9... sang Acc 3
# Acc 2: Lắng nghe relay group -5040203514, tải & upload
# Acc 3: Lắng nghe relay group -5281140814, tải & upload

set -e

PYTHON_BIN="python3"
PIPELINE_SCRIPT="./telegram_media_downloader/course_pipeline.py"
RELAY_SCRIPT="./telegram_media_downloader/relay_pipeline.py"
RCLONE_DEST="gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"

RELAY_GROUP_ACC2="-5040203514"
RELAY_GROUP_ACC3="-5281140814"

if [ -f "./.venv/bin/python" ]; then
    PYTHON_BIN="./.venv/bin/python"
fi

# Cài 7z nếu chưa có
if ! command -v 7z &> /dev/null; then
    echo "📦 Cài đặt công cụ giải nén..."
    sudo rm -f /etc/apt/sources.list.d/yarn.list || true
    sudo apt-get update -qq && sudo apt-get install -y p7zip-full p7zip-rar unrar || true
fi

# Kill triệt để các process cũ giải phóng port 5000 và file session
pkill -9 -f course_pipeline.py || true
pkill -9 -f relay_pipeline.py  || true
pkill -9 -f cloudflared        || true
sleep 2

echo ""
echo "=================================================="
echo "🚀 MULTI-ACCOUNT PIPELINE - 3 TÀI KHOẢN SONG SONG"
echo "=================================================="
echo "  Acc 1: Quét bot + tải trực tiếp (port 5000)"
echo "  Acc 2: Relay group $RELAY_GROUP_ACC2 (port 5001)"
echo "  Acc 3: Relay group $RELAY_GROUP_ACC3 (port 5002)"
echo "=================================================="

# ── Acc 1 Master Pipeline ─────────────────────────────
echo ""
echo "▶ Khởi chạy Acc 1 (Master)..."
CMD_PREFIX=""
if command -v ona &> /dev/null; then
    CMD_PREFIX="ona environment keep-alive -- "
fi

nohup $CMD_PREFIX$PYTHON_BIN $PIPELINE_SCRIPT \
    -r "$RCLONE_DEST" \
    -p 5000 \
    --relay-acc2 "$RELAY_GROUP_ACC2" \
    --relay-acc3 "$RELAY_GROUP_ACC3" \
    > pipeline_acc1.log 2>&1 &

echo "✔ Acc 1 đã khởi động! Log: pipeline_acc1.log"

sleep 3

# Khởi chạy Cloudflare Tunnel sau khi Acc 1 đã bind port 5000
if [ -f "./cloudflared" ]; then
    echo "🌐 Khởi chạy Cloudflare Tunnel (Dashboard port 5000)..."
    nohup ./cloudflared tunnel --url http://localhost:5000 > cloudflared.log 2>&1 &
    CF_PID=$!

    echo "⏳ Chờ Cloudflare khởi động (tối đa 20s)..."
    URL=""
    for i in $(seq 1 20); do
        sleep 1
        URL=$(grep -o "https://[a-zA-Z0-9-]*\.trycloudflare\.com" cloudflared.log 2>/dev/null | tail -n 1)
        if [ -n "$URL" ]; then
            break
        fi
    done

    if [ -n "$URL" ]; then
        echo ""
        echo "╔══════════════════════════════════════════════════════╗"
        echo "║  🌐 CLOUDFLARE DASHBOARD URL:                        ║"
        echo "║  $URL"
        echo "║                                                      ║"
        echo "║  📋 Tab 1: 🟢 Acc 1 (Master)                         ║"
        echo "║  📋 Tab 2: 🔵 Acc 2 (Relay)                          ║"
        echo "║  📋 Tab 3: 🟠 Acc 3 (Relay)                          ║"
        echo "║  📋 Tab 4: 🛰️ Dispatcher (port 5003)                 ║"
        echo "╚══════════════════════════════════════════════════════╝"
        echo ""
    else
        echo "⚠️  Cloudflare tunnel chưa lấy được URL sau 20s!"
        echo "    Kiểm tra: cat cloudflared.log | grep trycloudflare"
    fi
fi

sleep 2

# ── Acc 2 Relay Pipeline ──────────────────────────────
echo "▶ Khởi chạy Acc 2 (Relay)..."
nohup $CMD_PREFIX$PYTHON_BIN $RELAY_SCRIPT \
    --session pyrogram_acc2 \
    --group "$RELAY_GROUP_ACC2" \
    --rclone-dest "$RCLONE_DEST" \
    --port 5001 \
    > pipeline_acc2.log 2>&1 &

echo "✔ Acc 2 đã khởi động! Log: pipeline_acc2.log"

sleep 2

# ── Acc 3 Relay Pipeline ──────────────────────────────
echo "▶ Khởi chạy Acc 3 (Relay)..."
nohup $CMD_PREFIX$PYTHON_BIN $RELAY_SCRIPT \
    --session pyrogram_acc3 \
    --group "$RELAY_GROUP_ACC3" \
    --rclone-dest "$RCLONE_DEST" \
    --port 5002 \
    > pipeline_acc3.log 2>&1 &

echo "✔ Acc 3 đã khởi động! Log: pipeline_acc3.log"

echo ""
echo "=================================================="
echo "🎉 CẢ 3 PIPELINE ĐÃ CHẠY SONG SONG THÀNH CÔNG!"
echo "=================================================="
echo ""
echo "📊 Xem log realtime:"
echo "   Acc 1: tail -f pipeline_acc1.log"
echo "   Acc 2: tail -f pipeline_acc2.log"
echo "   Acc 3: tail -f pipeline_acc3.log"
echo ""
echo "📊 Hoặc xem tất cả 1 lúc:"
echo "   tail -f pipeline_acc1.log pipeline_acc2.log pipeline_acc3.log"
echo ""
