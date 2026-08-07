#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess

print("==========================================")
print("🔍 KIỂM TRA HỆ THỐNG GIẢI NÉN TRÊN ONA")
print("==========================================")

cmd_7z = shutil.which("7z") or shutil.which("7za")
print(f"📌 Đường dẫn 7z: {cmd_7z}")

if cmd_7z:
    try:
        res = subprocess.run([cmd_7z], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(f"✔ 7z Status: ĐÃ CÀI ĐẶT VÀ SẴN SÀNG HOẠT ĐỘNG! (Return code: {res.returncode})")
    except Exception as e:
        print(f"❌ Lỗi khi gọi 7z: {e}")
else:
    print("❌ 7z Status: CHƯA ĐƯỢC CÀI ĐẶT!")

cmd_unrar = shutil.which("unrar")
print(f"📌 Đường dẫn unrar: {cmd_unrar}")
print("==========================================")
