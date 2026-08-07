#!/bin/bash
set -e

echo "=========================================================="
echo "🧹 TELEGRAM COURSE DOWNLOADER - CLEAN RESET SYSTEM"
echo "=========================================================="

echo "🛑 1. Tắt toàn bộ tiến trình cũ (Python & Cloudflare)..."
pkill -f course_pipeline.py || true
pkill -f cloudflared || true

echo "🗑️ 2. Xóa sạch dữ liệu tạm & log cũ..."
rm -rf telegram_media_downloader/temp_processing/*
rm -rf temp_processing/*
rm -f pipeline.log cloudflared.log

echo "📋 3. Reset trạng thái full_hoahoc.csv về PENDING..."
if [ -f "telegram_media_downloader/full_hoahoc.csv" ]; then
    python3 -c "
import csv
path = 'telegram_media_downloader/full_hoahoc.csv'
rows = []
try:
    with open(path, 'r', encoding='utf-8') as f:
        for r in csv.reader(f):
            if r:
                rows.append([r[0], 'PENDING', ''])
    with open(path, 'w', encoding='utf-8', newline='') as f:
        csv.writer(f).writerows(rows)
except Exception as e:
        print(f'Lỗi reset CSV: {e}')
"
fi

echo "🚀 4. Khởi chạy lại toàn bộ quy trình tự động từ Khóa 1..."
chmod +x start-pipeline.sh manage.sh setup-all.sh
./start-pipeline.sh
