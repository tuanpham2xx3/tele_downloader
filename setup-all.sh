#!/bin/bash
set -e

echo "=========================================================="
echo "🚀 TELEGRAM COURSE DOWNLOADER - ONA AUTOMATED SETUP"
echo "=========================================================="

echo "📦 1. Cài đặt công cụ hệ thống (7z, unrar, rclone)..."
sudo rm -f /etc/apt/sources.list.d/yarn.list || true
sudo apt-get update -qq && sudo apt-get install -y p7zip-full p7zip-rar unrar || true
if ! command -v rclone &> /dev/null; then
    curl https://rclone.org/install.sh | sudo bash
fi

echo "🐍 2. Cài đặt thư viện Python (Telethon, Rich...)..."
pip install telethon rich python-dotenv pyyaml requests speedtest-cli

echo "🌐 3. Tải công cụ Cloudflare Tunnel..."
if [ ! -f "./cloudflared" ]; then
    curl -L --output cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
fi

chmod +x cloudflared manage.sh start-pipeline.sh setup-all.sh

echo "🚀 4. Khởi chạy Pipeline tự động ngầm (nohup)..."
./start-pipeline.sh
