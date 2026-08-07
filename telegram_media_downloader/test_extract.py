#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess

print("==========================================")
print("🔍 KIỂM TRA & CÀI ĐẶT HỆ THỐNG GIẢI NÉN TRÊN ONA")
print("==========================================")

cmd_7z = shutil.which("7z") or shutil.which("7za")
if not cmd_7z:
    print("📦 7z chưa có sẵn, đang tự động dọn dẹp apt & cài đặt p7zip-full...")
    try:
        subprocess.run("sudo rm -f /etc/apt/sources.list.d/yarn.list", shell=True, check=False)
        subprocess.run("sudo apt-get update -qq", shell=True, check=False)
        subprocess.run("sudo apt-get install -y p7zip-full p7zip-rar unrar", shell=True, check=False)
        cmd_7z = shutil.which("7z") or shutil.which("7za") or "/usr/bin/7z"
    except Exception as e:
        print(f"Cảnh báo khi cài: {e}")

print(f"📌 Đường dẫn 7z: {cmd_7z}")

if cmd_7z and (os.path.exists(cmd_7z) or shutil.which("7z")):
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
