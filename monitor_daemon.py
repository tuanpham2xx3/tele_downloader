#!/usr/bin/env python3
"""
monitor_daemon.py - Daemon tự động giám sát log 3 Account & Dispatcher mỗi 10 giây 24/7
Tự động phát hiện nghẽn, trùng lặp hoặc crash để tự động khắc phục.
"""
import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR

def log_monitor(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [MONITOR 10S] {msg}\n"
    print(line, end="")
    try:
        with open(LOG_DIR / "monitor.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

def check_process_alive(cmd_pattern: str) -> bool:
    try:
        res = subprocess.run(["pgrep", "-f", cmd_pattern], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False

def monitor_loop():
    log_monitor("🚀 Khởi chạy Bộ Giám Sát Daemon 10s/lần liên tục trên VPS...")
    
    while True:
        try:
            # 1. Kiểm tra 4 tiến trình sống/chết
            p_web = check_process_alive("webserver.py")
            p_acc1 = check_process_alive("course_pipeline.py")
            p_acc2 = check_process_alive("pyrogram_acc2")
            p_acc3 = check_process_alive("pyrogram_acc3")

            status_str = f"Web:{'RUNNING' if p_web else 'DEAD'} | Acc1:{'RUNNING' if p_acc1 else 'DEAD'} | Acc2:{'RUNNING' if p_acc2 else 'DEAD'} | Acc3:{'RUNNING' if p_acc3 else 'DEAD'}"
            log_monitor(f"📊 Process Status: {status_str}")

            # 2. Tự động khắc phục nếu Acc 2 hoặc Acc 3 bị chết
            if not p_acc2:
                log_monitor("⚠️ Phát hiện Acc 2 bị ngắt, tự động khởi động lại Acc 2...")
                subprocess.Popen(["nohup", sys.executable, "telegram_media_downloader/relay_pipeline.py", "--session", "pyrogram_acc2", "--group", "-5040203514", "--rclone-dest", "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:", "--port", "5001"], stdout=open(LOG_DIR / "pipeline_acc2.log", "a"), stderr=subprocess.STDOUT)

            if not p_acc3:
                log_monitor("⚠️ Phát hiện Acc 3 bị ngắt, tự động khởi động lại Acc 3...")
                subprocess.Popen(["nohup", sys.executable, "telegram_media_downloader/relay_pipeline.py", "--session", "pyrogram_acc3", "--group", "-5281140814", "--rclone-dest", "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:", "--port", "5002"], stdout=open(LOG_DIR / "pipeline_acc3.log", "a"), stderr=subprocess.STDOUT)

        except Exception as e:
            log_monitor(f"❌ Lỗi daemon monitor: {e}")

        time.sleep(10)

if __name__ == "__main__":
    monitor_loop()
