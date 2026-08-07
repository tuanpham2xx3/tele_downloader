#!/usr/bin/env python3
"""
Telegram Quick Login / Logout & Status Helper
Giúp đăng nhập, đăng xuất và kiểm tra kết nối Telegram dễ dàng trên Ubuntu Server.

Ví dụ sử dụng:
  python3 login_telegram.py                         # Đăng nhập Acc 1 (mặc định)
  python3 login_telegram.py --session pyrogram_acc2 # Đăng nhập Acc 2
  python3 login_telegram.py --session pyrogram_acc3 # Đăng nhập Acc 3
  python3 login_telegram.py --check                 # Kiểm tra trạng thái Acc 1
  python3 login_telegram.py --check --session pyrogram_acc2 # Kiểm tra Acc 2
"""

import os
import sys
import subprocess
import asyncio
from pathlib import Path

try:
    from telethon import TelegramClient
except ImportError:
    print("Vui lòng cài đặt telethon: pip install telethon")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
CONFIG_YAML = BASE_DIR / "config.yaml"


def resolve_session_path(session_name: str) -> Path:
    """Trả về đường dẫn đầy đủ cho session name (không có đuôi .session - Telethon tự thêm)."""
    # Loại bỏ đuôi .session nếu có (để Telethon tự thêm chính xác)
    if session_name.endswith(".session"):
        session_name = session_name[:-8]
    p = Path(session_name)
    if not p.is_absolute():
        p = BASE_DIR / session_name
    return p

def session_file_exists(session_path: Path) -> bool:
    """Kiểm tra file session có tồn tại không (Telethon thêm đuôi .session tự động)."""
    return session_path.exists() or (session_path.with_suffix('.session')).exists()


def get_credentials():
    api_id = os.environ.get("TELERECON_API_ID")
    api_hash = os.environ.get("TELERECON_API_HASH")

    if (not api_id or not api_hash) and CONFIG_YAML.exists():
        try:
            import yaml
            with open(CONFIG_YAML, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                if data.get("api_id") and str(data.get("api_id")) != "your_api_id":
                    api_id = str(data["api_id"])
                    api_hash = str(data.get("api_hash"))
        except Exception:
            pass

    return api_id, api_hash


async def do_login(session_path: Path):
    print(f"\n🔑 --- ĐĂNG NHẬP TELEGRAM ACCOUNT ---")
    print(f"💾 Session file: {session_path.resolve()}")
    api_id, api_hash = get_credentials()

    if not api_id or not api_hash or api_id == "your_api_id":
        print("Chưa có API ID / API Hash trong môi trường hoặc config.yaml.")
        api_id = input("Nhập Telegram API ID: ").strip()
        api_hash = input("Nhập Telegram API Hash: ").strip()

    phone = os.environ.get("TELERECON_PHONE") or input("Nhập Số điện thoại Telegram (VD: +84901234567): ").strip()

    client = TelegramClient(str(session_path), int(api_id), api_hash)
    await client.start(phone=phone)

    me = await client.get_me()
    print(f"\n🎉 ĐĂNG NHẬP THÀNH CÔNG!")
    print(f"👤 Tài khoản: {getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}")
    print(f"📞 SĐT/Username: @{getattr(me, 'username', '') or getattr(me, 'id', '')}")
    print(f"💾 Session file đã lưu tại: {session_path.resolve()}\n")
    await client.disconnect()

    try:
        subprocess.run(["git", "add", "-f", str(session_path)], cwd=str(BASE_DIR.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "commit", "-m", f"auto: save {session_path.name}"], cwd=str(BASE_DIR.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE_DIR.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"☁️ Đã tự động sao lưu session lên GitHub!")
    except Exception:
        pass


async def check_status(session_path: Path):
    print(f"\n🔍 --- KIỂM TRA TRẠNG THÁI: {session_path.name} ---")
    if not session_file_exists(session_path):
        print(f"❌ Chưa có file session ({session_path.name}.session). Hãy đăng nhập trước.")
        return False

    api_id, api_hash = get_credentials()
    if not api_id or not api_hash:
        api_id = 12345
        api_hash = "placeholder"

    try:
        client = TelegramClient(str(session_path), int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print("❌ File session không còn hiệu lực hoặc đã bị thu hồi.")
            await client.disconnect()
            return False

        me = await client.get_me()
        print(f"✔ Trạng thái: ĐÃ ĐĂNG NHẬP & HOẠT ĐỘNG")
        print(f"👤 Account: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', '') or getattr(me, 'id', '')})")
        await client.disconnect()
        return True
    except Exception as e:
        print(f"❌ Lỗi kết nối session: {e}")
        return False


def do_logout(session_path: Path):
    print(f"\n🚪 --- ĐĂNG XUẤT: {session_path.name} ---")
    if session_path.exists():
        os.remove(session_path)
        print(f"✔ Đã xóa file session ({session_path.name}). Đã đăng xuất thành công!")
    else:
        print(f"Không tìm thấy session: {session_path.name}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Telegram Account Login Helper")
    parser.add_argument("--session", default="pyrogram",
                        help="Tên session (VD: pyrogram, pyrogram_acc2, pyrogram_acc3). Mặc định: pyrogram")
    parser.add_argument("--logout", action="store_true", help="Đăng xuất session này")
    parser.add_argument("--check",  action="store_true", help="Kiểm tra trạng thái session")
    args = parser.parse_args()

    session_path = resolve_session_path(args.session)

    if args.logout:
        do_logout(session_path)
    elif args.check:
        asyncio.run(check_status(session_path))
    else:
        asyncio.run(do_login(session_path))
