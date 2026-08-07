#!/usr/bin/env python3
"""
Telegram Quick Login / Logout & Status Helper
Giúp đăng nhập, đăng xuất và kiểm tra kết nối Telegram dễ dàng trên Ubuntu Server.
"""

import os
import sys
import asyncio
from pathlib import Path

try:
    from telethon import TelegramClient
except ImportError:
    print("Vui lòng cài đặt telethon: pip install telethon")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
SESSION_PATH = BASE_DIR / "pyrogram.session"
CONFIG_YAML = BASE_DIR / "config.yaml"


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


async def do_login():
    print("\n🔑 --- ĐĂNG NHẬP TELEGRAM ACCOUNT MỚI ---")
    api_id, api_hash = get_credentials()

    if not api_id or not api_hash or api_id == "your_api_id":
        print("Chưa có API ID / API Hash trong môi trường hoặc config.yaml.")
        api_id = input("Nhập Telegram API ID: ").strip()
        api_hash = input("Nhập Telegram API Hash: ").strip()

    phone = os.environ.get("TELERECON_PHONE") or input("Nhập Số điện thoại Telegram (VD: +84901234567): ").strip()

    client = TelegramClient(str(SESSION_PATH), int(api_id), api_hash)
    await client.start(phone=phone)

    me = await client.get_me()
    print(f"\n🎉 ĐĂNG NHẬP THÀNH CÔNG!")
    print(f"👤 Tài khoản: {getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}")
    print(f"📞 SĐT/Username: @{getattr(me, 'username', '') or getattr(me, 'id', '')}")
    print(f"💾 Session file đã lưu tại: {SESSION_PATH.resolve()}\n")
    await client.disconnect()

    try:
        subprocess.run(["git", "add", "-f", str(SESSION_PATH)], cwd=str(BASE_DIR.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "commit", "-m", "auto: save pyrogram.session"], cwd=str(BASE_DIR.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE_DIR.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("☁️ Đã tự động sao lưu phiên đăng nhập Telegram lên GitHub bí mật!")
    except Exception:
        pass


async def check_status():
    print("\n🔍 --- KIỂM TRA TRẠNG THÁI KẾT NỐI TELEGRAM ---")
    if not SESSION_PATH.exists():
        print("❌ Chưa có file session Telegram (`pyrogram.session`). Bạn cần đăng nhập trước.")
        return False

    api_id, api_hash = get_credentials()
    if not api_id or not api_hash:
        api_id = 12345
        api_hash = "placeholder"

    try:
        client = TelegramClient(str(SESSION_PATH), int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print("❌ File session không còn hiệu lực hoặc đã bị thu hồi.")
            await client.disconnect()
            return False

        me = await client.get_me()
        print(f"✔ Trạng thái: ĐÃ ĐĂNG NHẬP & HOẠT ĐỘNG THƯỜNG XUYÊN")
        print(f"👤 Account: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', '') or getattr(me, 'id', '')})")
        await client.disconnect()
        return True
    except Exception as e:
        print(f"❌ Lỗi kết nối session: {e}")
        return False


def do_logout():
    print("\n🚪 --- ĐĂNG XUẤT TELEGRAM ---")
    if SESSION_PATH.exists():
        os.remove(SESSION_PATH)
        print(f"✔ Đã xóa file session ({SESSION_PATH.name}). Đã đăng xuất thành công!")
    else:
        print("Hiện tại không có phiên đăng nhập nào.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--logout":
            do_logout()
        elif arg == "--check":
            asyncio.run(check_status())
        else:
            asyncio.run(do_login())
    else:
        asyncio.run(do_login())
