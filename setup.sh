#!/usr/bin/env bash
# setup.sh - Cài đặt môi trường và login Telegram từ đầu sau khi ONA reset
set +e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }
info() { echo -e "${CYAN}[INFO]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

PYTHON_BIN="python3"
if [ -f "./.venv/bin/python" ]; then PYTHON_BIN="./.venv/bin/python"; fi

echo ""
echo "=================================================="
echo "  🔧 SETUP - SAU KHI ONA RESET"
echo "=================================================="

# ── BƯỚC 0: Tự động chuyển vào đúng thư mục dự án ─────
REPO_URL="https://github.com/tuanpham2xx3/tele_downloader.git"

if [ -d "telegram_media_downloader" ]; then
    info "Đang ở trong thư mục dự án: $(pwd)"
elif [ -d "tele_downloader/telegram_media_downloader" ]; then
    cd tele_downloader
    info "Đã chuyển vào thư mục: $(pwd)"
elif [ -d "app/telegram_media_downloader" ]; then
    cd app
    info "Đã chuyển vào thư mục: $(pwd)"
else
    info "Không tìm thấy thư mục dự án. Tiến hành clone $REPO_URL..."
    git clone $REPO_URL tele_downloader
    cd tele_downloader
    info "Đã clone và chuyển vào: $(pwd)"
fi

mkdir -p telegram_media_downloader

# ── BƯỚC 1: Pull code ────────────────────────────────
info "Pull code mới nhất từ GitHub..."
if git rev-parse --is-inside-work-tree &>/dev/null; then
    git fetch origin main 2>/dev/null || true
    git reset --hard origin/main 2>/dev/null || true
    git pull origin main 2>/dev/null || true
    ok "Code cập nhật xong"
else
    warn "Không phải git repository, bỏ qua git pull."
fi

# ── BƯỚC 2: Cài dependencies ─────────────────────────
info "Cài Python dependencies..."
$PYTHON_BIN -m pip install -q --upgrade telethon rich python-dotenv
ok "Dependencies OK"

# ── BƯỚC 3: Cài 7z/unrar ─────────────────────────────
if ! command -v 7z &>/dev/null; then
    info "Cài 7z/unrar..."
    sudo rm -f /etc/apt/sources.list.d/yarn.list || true
    sudo apt-get update -qq
    sudo apt-get install -y p7zip-full p7zip-rar unrar -qq
    ok "7z/unrar OK"
fi

# ── BƯỚC 4: Cài cloudflared nếu chưa có ─────────────
if [ ! -f "./cloudflared" ]; then
    info "Tải cloudflared..."
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
    chmod +x cloudflared
    ok "cloudflared OK"
fi

# ── BƯỚC 5: Kiểm tra session file ───────────────────
echo ""
echo "=================================================="
echo "  📋 TRẠNG THÁI SESSION FILE"
echo "=================================================="
SESSIONS=("pyrogram" "pyrogram_acc2" "pyrogram_acc3")
NAMES=("Acc 1 (Master)" "Acc 2 (Relay)" "Acc 3 (Relay)")
MISSING=()

for i in "${!SESSIONS[@]}"; do
    sess="${SESSIONS[$i]}"
    name="${NAMES[$i]}"
    f="telegram_media_downloader/${sess}.session"
    if [ -f "$f" ]; then
        size=$(du -h "$f" | cut -f1)
        ok "$name: $f ($size) ✔"
    else
        err "$name: MISSING - cần login lại"
        MISSING+=("$i")
    fi
done

# ── BƯỚC 6: Login lại các acc bị mất session ────────
if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo "=================================================="
    echo "  🔐 LOGIN TELEGRAM"
    echo "=================================================="
    warn "Cần login lại ${#MISSING[@]} tài khoản. Chuẩn bị OTP trên điện thoại!"
    echo ""

    for i in "${MISSING[@]}"; do
        sess="${SESSIONS[$i]}"
        name="${NAMES[$i]}"
        echo -e "${CYAN}━━━ Login $name (session: $sess) ━━━${NC}"
        $PYTHON_BIN - <<PYEOF
import asyncio, os, sys
sys.path.insert(0, 'telegram_media_downloader')

async def login():
    try:
        from telethon import TelegramClient
    except ImportError:
        print("ERROR: telethon chưa được cài!")
        return
    api_id   = os.environ.get('TELERECON_API_ID',   '2040')
    api_hash = os.environ.get('TELERECON_API_HASH', 'b18441a12607e109d9496d9a244ead1c')
    os.makedirs('telegram_media_downloader', exist_ok=True)
    session  = 'telegram_media_downloader/${sess}'
    client   = TelegramClient(session, int(api_id), str(api_hash))
    await client.start()
    me = await client.get_me()
    print(f"[OK] Đã login: {getattr(me,'first_name','')} (@{getattr(me,'username',me.id)})")
    await client.disconnect()

asyncio.run(login())
PYEOF
        echo ""
    done
else
    ok "Tất cả session đã có, không cần login lại!"
fi

# ── BƯỚC 7: Kiểm tra lại sau login ──────────────────
echo ""
echo "=================================================="
echo "  ✅ KẾT QUẢ"
echo "=================================================="
ALL_OK=true
for i in "${!SESSIONS[@]}"; do
    sess="${SESSIONS[$i]}"
    name="${NAMES[$i]}"
    f="telegram_media_downloader/${sess}.session"
    if [ -f "$f" ]; then
        ok "$name: READY ✔"
    else
        err "$name: VẪN THIẾU! Chạy lại: bash setup.sh"
        ALL_OK=false
    fi
done

echo ""
if $ALL_OK; then
    ok "Môi trường sẵn sàng! Chạy pipeline:"
    echo ""
    echo "  ./start-multi-pipeline.sh"
    echo ""
else
    warn "Một số account chưa login xong. Chạy lại: bash setup.sh"
fi
