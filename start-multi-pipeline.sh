#!/usr/bin/env bash
# start-multi-pipeline.sh - Pipeline launcher with full diagnostics
set +e

PYTHON_BIN="python3"
PIPELINE_SCRIPT="./telegram_media_downloader/course_pipeline.py"
RELAY_SCRIPT="./telegram_media_downloader/relay_pipeline.py"
WEBSERVER_SCRIPT="./webserver.py"
RCLONE_DEST="gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"
RELAY_GROUP_ACC2="-5040203514"
RELAY_GROUP_ACC3="-5281140814"

if [ -f "./.venv/bin/python" ]; then PYTHON_BIN="./.venv/bin/python"; fi

# ── Màu sắc terminal ──────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log_info()    { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_section() { echo -e "\n${BLUE}══════════════════════════════════════════${NC}"; echo -e "${BLUE}  $1${NC}"; echo -e "${BLUE}══════════════════════════════════════════${NC}"; }

# ── BƯỚC 1: Chuẩn bị môi trường & Mở rộng RAM Disk lên 10GB ───
log_section "CHUẨN BỊ MÔI TRƯỜNG & RAM DISK"

# Mở rộng /dev/shm từ 128MB mặc định của Docker lên 10GB RAM thực tế
log_info "Cấu hình RAM Disk 10GB..."
sudo mount -o remount,size=10G /dev/shm 2>/dev/null || true

# Tạo thêm RAM disk dự phòng tại /mnt/ramdisk nếu cần
if [ ! -d "/mnt/ramdisk" ]; then
    sudo mkdir -p /mnt/ramdisk 2>/dev/null || true
    sudo mount -t tmpfs -o size=10G tmpfs /mnt/ramdisk 2>/dev/null || true
    sudo chmod 777 /mnt/ramdisk 2>/dev/null || true
fi

log_info "Python: $($PYTHON_BIN --version 2>&1)"
log_info "Rclone: $(rclone --version 2>/dev/null | head -1 || echo 'NOT FOUND')"
log_info "7z:     $(7z --version 2>/dev/null | head -1 || echo 'NOT FOUND')"
log_info "Disk:   $(df -h . | tail -1)"
log_info "RAM:    $(free -h | grep Mem | awk '{print "Total:"$2" Used:"$3" Free:"$4}')"
if [ -d "/dev/shm" ]; then
    log_ok  "RAM disk /dev/shm: $(df -h /dev/shm | tail -1 | awk '{print "Size:"$2" Free:"$4}')"
else
    log_warn "/dev/shm không tồn tại"
fi

# Cài 7z và rclone nếu chưa có
if ! command -v 7z &> /dev/null || ! command -v rclone &> /dev/null; then
    log_warn "Cài đặt công cụ 7z/unrar/rclone..."
    sudo rm -f /etc/apt/sources.list.d/yarn.list || true
    sudo apt-get update -qq && sudo apt-get install -y p7zip-full p7zip-rar unrar rclone -qq || true
fi

# ── BƯỚC 2: Kill tất cả process cũ ──────────────────────
log_section "DỪNG PROCESS CŨ"

log_info "Kill process cũ..."
pkill -9 -f course_pipeline.py && log_ok "Đã kill course_pipeline.py" || log_info "course_pipeline.py chưa chạy"
pkill -9 -f relay_pipeline.py  && log_ok "Đã kill relay_pipeline.py"  || log_info "relay_pipeline.py chưa chạy"
pkill -9 -f webserver.py       && log_ok "Đã kill webserver.py"        || log_info "webserver.py chưa chạy"
pkill -9 -f cloudflared        && log_ok "Đã kill cloudflared"         || log_info "cloudflared chưa chạy"

log_info "Force-kill port 5000-5003..."
for port in 5000 5001 5002 5003; do
    pid=$(lsof -ti tcp:$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        kill -9 $pid 2>/dev/null || true
        log_warn "Port $port: kill PID $pid"
    else
        log_info "Port $port: trống"
    fi
done
sleep 3

# ── BƯỚC 3: Khởi động Web Dashboard ĐỘC LẬP ────────────
log_section "WEB DASHBOARD (Port 5000 - ĐỘC LẬP)"

if [ -f "$WEBSERVER_SCRIPT" ]; then
    nohup $PYTHON_BIN $WEBSERVER_SCRIPT > webserver.log 2>&1 &
    WEB_PID=$!
    sleep 2

    # Kiểm tra web server đã lên chưa
    if kill -0 $WEB_PID 2>/dev/null; then
        log_ok "Web Dashboard đang chạy (PID=$WEB_PID)"
        # Test thử kết nối
        if curl -s --max-time 3 http://localhost:5000/health > /dev/null 2>&1; then
            log_ok "Port 5000: ONLINE ✔"
        else
            log_warn "Port 5000: chưa phản hồi (đang khởi động...)"
        fi
    else
        log_error "Web Dashboard CRASH! Xem: cat webserver.log"
        cat webserver.log | tail -20
    fi
else
    log_error "Không tìm thấy $WEBSERVER_SCRIPT!"
fi

# ── BƯỚC 4: Cloudflare Tunnel ────────────────────────────
log_section "CLOUDFLARE TUNNEL"

if [ -f "./cloudflared" ]; then
    nohup ./cloudflared tunnel --url http://localhost:5000 > cloudflared.log 2>&1 &
    CF_PID=$!
    log_info "Cloudflared PID=$CF_PID, đợi lấy URL (tối đa 25s)..."

    URL=""
    for i in $(seq 1 25); do
        sleep 1
        URL=$(grep -o "https://[a-zA-Z0-9-]*\.trycloudflare\.com" cloudflared.log 2>/dev/null | tail -n 1)
        if [ -n "$URL" ]; then
            log_ok "URL lấy được sau ${i}s"
            break
        fi
        # In tiến trình mỗi 5s
        if [ $((i % 5)) -eq 0 ]; then
            log_info "Đang chờ... ${i}s"
            # Hiển thị log cloudflared gần nhất
            tail -3 cloudflared.log 2>/dev/null | while read l; do echo "  > $l"; done
        fi
    done

    if [ -n "$URL" ]; then
        echo ""
        echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║  🌐 DASHBOARD URL:                                   ║${NC}"
        echo -e "${GREEN}║  $URL${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
        echo ""
    else
        log_error "Không lấy được URL sau 25s!"
        log_info "Tail cloudflared.log:"
        tail -10 cloudflared.log 2>/dev/null | while read l; do echo "  $l"; done
        log_info "Thủ công: grep trycloudflare cloudflared.log"
    fi
else
    log_warn "Không tìm thấy ./cloudflared, bỏ qua tunnel"
fi

# ── BƯỚC 5: Khởi động Pipelines ──────────────────────────
log_section "KHỞI ĐỘNG PIPELINES"

CMD_PREFIX=""
if command -v ona &> /dev/null; then CMD_PREFIX="ona environment keep-alive -- "; fi

# Acc 1 Master
log_info "Khởi chạy Acc 1 (Master)..."
nohup $CMD_PREFIX$PYTHON_BIN $PIPELINE_SCRIPT \
    -r "$RCLONE_DEST" \
    -p 5000 \
    --relay-acc2 "$RELAY_GROUP_ACC2" \
    --relay-acc3 "$RELAY_GROUP_ACC3" \
    >> pipeline_acc1.log 2>&1 &
ACC1_PID=$!
sleep 2
if kill -0 $ACC1_PID 2>/dev/null; then
    log_ok "Acc 1 đang chạy (PID=$ACC1_PID) → pipeline_acc1.log"
else
    log_error "Acc 1 CRASH! Xem log:"
    tail -20 pipeline_acc1.log 2>/dev/null | while read l; do echo "  $l"; done
fi

# Acc 2 Relay
log_info "Khởi chạy Acc 2 (Relay)..."
nohup $CMD_PREFIX$PYTHON_BIN $RELAY_SCRIPT \
    --session pyrogram_acc2 \
    --group "$RELAY_GROUP_ACC2" \
    --rclone-dest "$RCLONE_DEST" \
    --port 5001 \
    >> pipeline_acc2.log 2>&1 &
ACC2_PID=$!
sleep 2
if kill -0 $ACC2_PID 2>/dev/null; then
    log_ok "Acc 2 đang chạy (PID=$ACC2_PID) → pipeline_acc2.log"
else
    log_error "Acc 2 CRASH! Xem log:"
    tail -20 pipeline_acc2.log 2>/dev/null | while read l; do echo "  $l"; done
fi

# Acc 3 Relay
log_info "Khởi chạy Acc 3 (Relay)..."
nohup $CMD_PREFIX$PYTHON_BIN $RELAY_SCRIPT \
    --session pyrogram_acc3 \
    --group "$RELAY_GROUP_ACC3" \
    --rclone-dest "$RCLONE_DEST" \
    --port 5002 \
    >> pipeline_acc3.log 2>&1 &
ACC3_PID=$!
sleep 2
if kill -0 $ACC3_PID 2>/dev/null; then
    log_ok "Acc 3 đang chạy (PID=$ACC3_PID) → pipeline_acc3.log"
else
    log_error "Acc 3 CRASH! Xem log:"
    tail -20 pipeline_acc3.log 2>/dev/null | while read l; do echo "  $l"; done
fi

# ── Khởi động Daemon Giám Sát Tự Động 10s/lần ───────────
log_info "Khởi chạy Daemon Giám sát Tự động 10s/lần 24/7..."
pkill -9 -f monitor_daemon.py 2>/dev/null || true
nohup $PYTHON_BIN monitor_daemon.py >> monitor.log 2>&1 &
MONITOR_PID=$!
log_ok "Daemon 10s đang chạy 24/7 (PID=$MONITOR_PID) → monitor.log"

# ── BƯỚC 6: Kiểm tra trạng thái cuối ─────────────────────
log_section "TRẠNG THÁI HỆ THỐNG"

sleep 3
echo ""
echo "PROCESS STATUS:"
printf "  %-20s" "webserver.py:";  kill -0 $WEB_PID  2>/dev/null && echo -e "${GREEN}RUNNING${NC} (PID=$WEB_PID)"  || echo -e "${RED}DEAD${NC}"
printf "  %-20s" "course_pipeline:"; kill -0 $ACC1_PID 2>/dev/null && echo -e "${GREEN}RUNNING${NC} (PID=$ACC1_PID)" || echo -e "${RED}DEAD${NC}"
printf "  %-20s" "relay_acc2:";    kill -0 $ACC2_PID 2>/dev/null && echo -e "${GREEN}RUNNING${NC} (PID=$ACC2_PID)" || echo -e "${RED}DEAD${NC}"
printf "  %-20s" "relay_acc3:";    kill -0 $ACC3_PID 2>/dev/null && echo -e "${GREEN}RUNNING${NC} (PID=$ACC3_PID)" || echo -e "${RED}DEAD${NC}"

echo ""
echo "PORT STATUS:"
for port in 5000 5001 5002 5003; do
    pid=$(lsof -ti tcp:$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        printf "  Port %-6s" "$port:"; echo -e "${GREEN}LISTENING${NC} (PID=$pid)"
    else
        printf "  Port %-6s" "$port:"; echo -e "${RED}NOT BOUND${NC}"
    fi
done

echo ""
echo "LOG FILES:"
for f in pipeline_acc1.log pipeline_acc2.log pipeline_acc3.log pipeline_dispatcher.log webserver.log cloudflared.log; do
    if [ -f "$f" ]; then
        size=$(du -h "$f" | cut -f1)
        lines=$(wc -l < "$f")
        printf "  %-35s %s (%s lines)\n" "$f" "$size" "$lines"
    fi
done

echo ""
log_ok "Để xem log realtime:"
echo "   tail -f pipeline_acc1.log pipeline_acc2.log pipeline_acc3.log"
echo ""
log_ok "Để xem lỗi nhanh:"
echo "   grep -i error pipeline_acc1.log | tail -20"
echo ""
