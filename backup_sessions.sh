#!/usr/bin/env bash
# backup_sessions.sh - Commit & Push các file Telegram .session lên GitHub
set +e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${CYAN}[INFO] Đang kiểm tra các file session...${NC}"
mkdir -p telegram_media_downloader

SESSIONS=(telegram_media_downloader/*.session)
if [ ${#SESSIONS[@]} -eq 0 ] || [ ! -e "${SESSIONS[0]}" ]; then
    echo -e "${RED}[ERROR] Không tìm thấy file .session nào trong telegram_media_downloader!${NC}"
    exit 1
fi

echo -e "${GREEN}[OK] Tìm thấy các file session:${NC}"
ls -lh telegram_media_downloader/*.session

echo -e "${CYAN}[INFO] Đang đẩy session files lên GitHub...${NC}"
git add telegram_media_downloader/*.session
git commit -m "chore: backup telegram session files"
git push origin main

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=================================================="${NC}
    echo -e "${GREEN}🎉 ĐÃ LƯU SESSION LÊN GITHUB THÀNH CÔNG!${NC}"
    echo -e "${GREEN}Lần sau ONA reset, hệ thống sẽ tự dùng lại session cũ.${NC}"
    echo -e "${GREEN}=================================================="${NC}
else
    echo -e "${RED}[ERROR] Không thể push lên GitHub. Hãy kiểm tra kết nối/quyền Git.${NC}"
fi
