#!/usr/bin/env python3
"""
login.py - Tool đăng nhập Telegram tương tác trực tiếp bằng Telethon
Sử dụng:
  python3 login.py pyrogram          (Acc 1)
  python3 login.py pyrogram_acc2     (Acc 2)
  python3 login.py pyrogram_acc3     (Acc 3)
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
TELE_DIR = BASE_DIR / "telegram_media_downloader"
TELE_DIR.mkdir(exist_ok=True)

try:
    from telethon.sync import TelegramClient
except ImportError:
    print("❌ Vui lòng cài telethon: pip install telethon")
    sys.exit(1)

# Default Telegram App credentials (Official Android/Desktop app defaults)
DEFAULT_API_ID   = 21724
DEFAULT_API_HASH = "3e0fe5dadb9b1612e3e5b6d912b72449"

session_name = sys.argv[1] if len(sys.argv) > 1 else "pyrogram"
session_path = str(TELE_DIR / session_name)

env_api_id   = os.environ.get("TELERECON_API_ID")
env_api_hash = os.environ.get("TELERECON_API_HASH")

if env_api_id and env_api_hash and env_api_id != "2040":
    api_id   = int(env_api_id)
    api_hash = env_api_hash
else:
    api_id   = DEFAULT_API_ID
    api_hash = DEFAULT_API_HASH

print(f"\n🔑 Khởi tạo đăng nhập Telegram: [{session_name}] (API ID: {api_id})...")

def get_phone():
    raw = input("📱 Nhập số điện thoại đăng nhập (VD: +8437998458 hoặc 037998458): ").strip()
    raw = raw.replace(" ", "").replace("-", "")
    if raw.startswith("0"):
        raw = "+84" + raw[1:]
    elif not raw.startswith("+"):
        raw = "+84" + raw
    return raw

client = TelegramClient(session_path, api_id, api_hash)

try:
    with client:
        me = client.get_me()
        if not me:
            client.start(phone=get_phone)
            me = client.get_me()
        if me:
            print(f"\n✅ ĐÃ ĐĂNG NHẬP THÀNH CÔNG: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', me.id)})")
            print(f"📁 Session file đã lưu tại: {session_path}.session\n")
except Exception as e:
    print(f"\n❌ Lỗi đăng nhập: {e}")
    if "ApiIdInvalidError" in str(type(e)) or "ApiIdInvalid" in str(e):
        print("\n⚠️ API ID mặc định bị từ chối. Hãy thử nhập API ID & API Hash từ https://my.telegram.org:")
        custom_id   = input("API ID: ").strip()
        custom_hash = input("API Hash: ").strip()
        if custom_id and custom_hash:
            c2 = TelegramClient(session_path, int(custom_id), custom_hash)
            with c2:
                c2.start(phone=get_phone)
                me = c2.get_me()
                if me:
                    print(f"\n✅ ĐÃ ĐĂNG NHẬP THÀNH CÔNG: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', me.id)})")
