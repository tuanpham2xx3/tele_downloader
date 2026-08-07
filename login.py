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

session_name = sys.argv[1] if len(sys.argv) > 1 else "pyrogram"
session_path = str(TELE_DIR / session_name)

api_id   = int(os.environ.get("TELERECON_API_ID", "2040"))
api_hash = os.environ.get("TELERECON_API_HASH", "b18441a12607e109d9496d9a244ead1c")

print(f"\n🔑 Khởi tạo đăng nhập Telegram: [{session_name}]...")
client = TelegramClient(session_path, api_id, api_hash)

with client:
    me = client.get_me()
    if me:
        print(f"✅ ĐÃ ĐĂNG NHẬP THÀNH CÔNG: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', me.id)})")
        print(f"📁 Session file đã lưu tại: {session_path}.session\n")
    else:
        print("❌ Đăng nhập không thành công.")
