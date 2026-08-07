#!/usr/bin/env bash
# Script Quản lý Đăng nhập/Đăng xuất Telegram & Rclone Google Drive trên Ubuntu

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="python3"
if [ -f "$BASE_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$BASE_DIR/.venv/bin/python"
fi

LOGIN_SCRIPT="$BASE_DIR/telegram_media_downloader/login_telegram.py"

while true; do
    echo ""
    echo "=========================================================="
    echo "  🚀 UBUNTU TELEGRAM & RCLONE MANAGER - HỆ THỐNG QUẢN LÝ"
    echo "=========================================================="
    echo "  1. 🔑 Đăng nhập Telegram mới (Login OTP)"
    echo "  2. 🚪 Đăng xuất Telegram (Logout / Xóa Session)"
    echo "  3. 📋 Dán file rclone.conf từ Windows sang Ubuntu (Nhanh nhất)"
    echo "  4. ☁️ Khởi chạy cấu hình Rclone thủ công (rclone config)"
    echo "  5. 🔍 Kiểm tra trạng thái kết nối (Telegram & Rclone)"
    echo "  6. ▶ Khởi chạy Pipeline Tự Động Hóa (start-pipeline.sh)"
    echo "  0. ❌ Thoát"
    echo "=========================================================="
    read -p "Nhập lựa chọn của bạn [0-6]: " choice

    case $choice in
        1)
            echo "🔑 Đang mở trình đăng nhập Telegram..."
            $PYTHON_BIN "$LOGIN_SCRIPT"
            ;;
        2)
            echo "🚪 Đang thực hiện đăng xuất Telegram..."
            $PYTHON_BIN "$LOGIN_SCRIPT" --logout
            ;;
        3)
            echo "📋 Paste nội dung rclone.conf từ Windows vào đây (Nhấn Ctrl+D khi hoàn tất):"
            mkdir -p ~/.config/rclone
            cat > ~/.config/rclone/rclone.conf
            echo "✔ Đã lưu cấu hình ~/.config/rclone/rclone.conf thành công!"
            ;;
        4)
            echo "☁️ Khởi chạy cấu hình Rclone Google Drive tự động..."
            echo "👉 Bạn chỉ cần copy đường link bên dưới dán vào trình duyệt để đăng nhập Google, sau đó copy mã xác nhận dán lại vào đây!"
            echo ""
            rclone config create gdrive drive config_is_local false scope "drive"
            ;;
        5)
            echo "🔍 Kiểm tra Telegram..."
            $PYTHON_BIN "$LOGIN_SCRIPT" --check
            echo ""
            echo "🔍 Kiểm tra Rclone Google Drive Remotes..."
            if command -v rclone &> /dev/null; then
                rclone listremotes
            else
                echo "❌ Chưa cài đặt Rclone trên Ubuntu. Hãy cài bằng: sudo apt install rclone"
            fi
            ;;
        6)
            echo "▶ Đang khởi chạy Pipeline..."
            bash "$BASE_DIR/start-pipeline.sh"
            ;;
        0)
            echo "Thoát chương trình. Tạm biệt!"
            exit 0
            ;;
        *)
            echo "Lựa chọn không hợp lệ. Vui lòng thử lại!"
            ;;
    esac
done
