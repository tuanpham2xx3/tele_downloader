#!/usr/bin/env python3
# pyright: reportGeneralTypeIssues=false
# pyright: reportOptionalMemberAccess=false
# pyright: reportAttributeAccessIssue=false
# type: ignore
"""
Telegram Auto Course Pipeline & Rclone Uploader
Quy trình 6 bước tự động hóa khép kín:
  1. Load lịch sử tin nhắn Bot Telegram
  2. Detect khóa học & gom file theo luồng (Stream Grouping)
  3. Tải từng khóa học theo thứ tự (Single-Course Queue)
  4. Giải nén: .mp4 giữ nguyên, các file còn lại nén thành 1 file Class_Materials.zip
  5. Upload lên Google Drive qua Rclone vào thư mục cha chọn sẵn
  6. Xóa dữ liệu tạm trên Ubuntu, cập nhật CSV status, ghi log & hỗ trợ Web Viewer từ xa
"""

import os
import sys
import re
import csv
import shutil
import asyncio
import argparse
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import yaml
except ImportError:
    yaml = None

# Dependency check
try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename
    from rich.console import Console
    from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
except ImportError:
    print("Vui lòng cài đặt dependency: pip install telethon rich python-dotenv")
    sys.exit(1)

console = Console()

# File paths
BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "full_hoahoc.csv"
LOG_PATH = BASE_DIR / "pipeline.log"

# ─── RAM Disk tự động: ưu tiên /dev/shm (Linux RAM disk), fallback về đĩa ───
_SHM_DIR = Path("/dev/shm")
_PREFER_RAM = _SHM_DIR.exists() and _SHM_DIR.is_dir()
TEMP_DIR = (_SHM_DIR / "pipeline_acc1_temp") if _PREFER_RAM else (BASE_DIR / "temp_processing")

if _PREFER_RAM:
    import shutil as _shutil
    _shm_stat = _shutil.disk_usage(str(_SHM_DIR))
    print(f"[✔] RAM disk /dev/shm khả dụng! Free: {_shm_stat.free / 1024**3:.1f} GB | TEMP tại: {TEMP_DIR}")
else:
    print(f"[!] /dev/shm không khả dụng, dùng đĩa thường: {TEMP_DIR}")


def check_shm_free_gb(min_gb: float = 2.0) -> bool:
    """Kiểm tra RAM disk còn đủ chỗ không."""
    if not _PREFER_RAM:
        return True
    try:
        stat = shutil.disk_usage(str(_SHM_DIR))
        free_gb = stat.free / 1024**3
        return free_gb >= min_gb
    except Exception:
        return True


def get_temp_dir_for_course(course_title: str, estimated_gb: float = 3.0) -> Path:
    """Chọn TEMP_DIR thông minh: dùng RAM nếu đủ chỗ, fallback về đĩa."""
    if _PREFER_RAM and check_shm_free_gb(estimated_gb + 1.0):
        ram_path = _SHM_DIR / f"pipeline_acc1_temp" / sanitize_name(course_title)
        log(f"[RAM Disk] Sử dụng /dev/shm cho [{course_title}] (free={shutil.disk_usage(str(_SHM_DIR)).free/1024**3:.1f}GB)", "INFO")
        return ram_path
    else:
        disk_path = BASE_DIR / "temp_processing" / sanitize_name(course_title)
        log(f"[Disk] /dev/shm không đủ chỗ, dùng đĩa cho [{course_title}]", "WARN")
        return disk_path

# Global Live Log Memory Buffer
log_history: List[str] = []

def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    log_history.append(formatted)
    if len(log_history) > 2000:
        log_history.pop(0)

    # Console Output
    color = "green" if level == "SUCCESS" else "yellow" if level == "WARN" else "red" if level == "ERROR" else "white"
    console.print(f"[{color}]{formatted}[/{color}]")

    # Write to log file
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


# ==========================================
# WEB LOG MONITOR (Serves on Port 5000)
# ==========================================
LOG_PATH_ACC2 = BASE_DIR.parent / "pipeline_acc2.log"
LOG_PATH_ACC3 = BASE_DIR.parent / "pipeline_acc3.log"
LOG_PATH_DISPATCHER = BASE_DIR.parent / "pipeline_dispatcher.log"

dispatcher_log_history: List[str] = []

def log_dispatcher(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    dispatcher_log_history.append(formatted)
    if len(dispatcher_log_history) > 2000:
        dispatcher_log_history.pop(0)

    # Ghi vào file log riêng của Dispatcher
    try:
        with open(LOG_PATH_DISPATCHER, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

    # Đồng thời in ra console với màu tím / cyan
    color = "magenta" if level == "SUCCESS" else "yellow" if level == "WARN" else "red" if level == "ERROR" else "cyan"
    console.print(f"[{color}]{formatted}[/{color}]")

def _read_log_tail(log_path: Path, max_lines: int = 500) -> str:
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                return "".join(lines[-max_lines:])
        except Exception:
            pass
    return "(Chưa có log)"


class WebLogHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return  # Suppress default HTTP logging

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = r"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>🚀 Pipeline Monitor - 4 Bảng Điều Khiển</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0d1117; color: #c9d1d9; font-family: ui-sans-serif, system-ui, sans-serif; padding: 16px; height: 100vh; display: flex; flex-direction: column; }
        h1 { color: #58a6ff; font-size: 18px; margin-bottom: 12px; }
        .tabs { display: flex; gap: 4px; margin-bottom: 0; }
        .tab {
            padding: 8px 18px; border-radius: 8px 8px 0 0; cursor: pointer;
            font-size: 13px; font-weight: bold; border: 1px solid #30363d;
            border-bottom: none; background: #161b22; color: #8b949e;
            transition: all 0.15s;
        }
        .tab.active { background: #1f2937; color: #f0f6fc; border-color: #58a6ff; border-bottom-color: #1f2937; }
        .tab:hover:not(.active) { background: #21262d; color: #c9d1d9; }
        .tab.acc1 { border-top: 2px solid #3fb950; }
        .tab.acc2 { border-top: 2px solid #58a6ff; }
        .tab.acc3 { border-top: 2px solid #f78166; }
        .tab.disp { border-top: 2px solid #d2a8ff; }
        .panel {
            display: none; background: #161b22; border: 1px solid #30363d;
            border-radius: 0 8px 8px 8px; padding: 14px; flex: 1;
            overflow-y: auto; white-space: pre-wrap;
            font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
            font-size: 12.5px; line-height: 1.6;
        }
        .panel.active { display: block; }
        .controls { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
        button { background: #238636; color: white; border: 0; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 12px; }
        button:hover { background: #2ea043; }
        button.sec { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; }
        button.sec:hover { background: #30363d; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; margin-left: 6px; }
        .badge.ok { background: #1a4731; color: #3fb950; }
        label { margin-left: auto; font-size: 12px; color: #8b949e; cursor: pointer; display: flex; align-items: center; gap: 5px; }
        .SUCCESS { color: #3fb950; font-weight: bold; }
        .WARN    { color: #d29922; }
        .ERROR   { color: #f85149; font-weight: bold; }
        .INFO    { color: #58a6ff; }
    </style>
</head>
<body>
<h1>🚀 Pipeline Monitor &nbsp;<span class="badge ok">LIVE</span></h1>
<div class="controls">
    <button onclick="fetchAll()">🔄 Làm mới</button>
    <button onclick="window.location.href='/api/download-log'" class="sec">📥 Log Acc1</button>
    <button onclick="window.location.href='/api/download-csv'" class="sec">📊 CSV Status</button>
    <label><input type="checkbox" id="autoscroll" checked> Tự động cuộn xuống</label>
</div>
<div class="tabs">
    <div class="tab acc1 active" onclick="switchTab(0)">🟢 Acc 1 (Master)</div>
    <div class="tab acc2"        onclick="switchTab(1)">🔵 Acc 2 (Relay)</div>
    <div class="tab acc3"        onclick="switchTab(2)">🟠 Acc 3 (Relay)</div>
    <div class="tab disp"        onclick="switchTab(3)">🟣 🛰️ Dispatcher (Điều Phối)</div>
</div>
<div class="panel active" id="panel0">Đang tải log Acc 1...</div>
<div class="panel"        id="panel1">Đang tải log Acc 2...</div>
<div class="panel"        id="panel2">Đang tải log Acc 3...</div>
<div class="panel"        id="panel3">Đang tải log Dispatcher...</div>

<script>
let currentTab = 0;
function colorize(text) {
    return text
        .replace(/\[SUCCESS\]/g, '<span class="SUCCESS">[SUCCESS]</span>')
        .replace(/\[ERROR\]/g,   '<span class="ERROR">[ERROR]</span>')
        .replace(/\[WARN\]/g,    '<span class="WARN">[WARN]</span>')
        .replace(/\[INFO\]/g,    '<span class="INFO">[INFO]</span>');
}
function switchTab(idx) {
    document.querySelectorAll('.tab').forEach((t,i)   => t.classList.toggle('active', i===idx));
    document.querySelectorAll('.panel').forEach((p,i) => p.classList.toggle('active', i===idx));
    currentTab = idx;
}
async function fetchPanel(url, panelId) {
    try {
        const r = await fetch(url);
        const t = await r.text();
        const p = document.getElementById(panelId);
        p.innerHTML = colorize(t.replace(/</g,'&lt;').replace(/>/g,'&gt;'));
        if (document.getElementById('autoscroll').checked && panelId === 'panel' + currentTab) {
            p.scrollTop = p.scrollHeight;
        }
    } catch(e) {}
}
function fetchAll() {
    fetchPanel('/api/logs',            'panel0');
    fetchPanel('/api/logs/acc2',       'panel1');
    fetchPanel('/api/logs/acc3',       'panel2');
    fetchPanel('/api/logs/dispatcher', 'panel3');
}
fetchAll();
setInterval(fetchAll, 2500);
</script>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))

        elif self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("\n".join(log_history).encode("utf-8"))

        elif self.path == "/api/logs/acc2":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(_read_log_tail(LOG_PATH_ACC2).encode("utf-8"))

        elif self.path == "/api/logs/acc3":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(_read_log_tail(LOG_PATH_ACC3).encode("utf-8"))

        elif self.path == "/api/logs/dispatcher":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            content = "\n".join(dispatcher_log_history) if dispatcher_log_history else _read_log_tail(LOG_PATH_DISPATCHER)
            self.wfile.write(content.encode("utf-8"))

        elif self.path == "/api/download-log":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            filename = f"pipeline-acc1-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            if LOG_PATH.exists():
                with open(LOG_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write("\n".join(log_history).encode("utf-8"))

        elif self.path == "/api/download-csv":
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="full_hoahoc.csv"')
            self.end_headers()
            if CSV_PATH.exists():
                with open(CSV_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"")
        else:
            self.send_error(404)


def start_dispatcher_web_log_server(port: int = 5003):
    class DispatcherWebLogHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8"><title>🛰️ Dispatcher Log Monitor</title>
<style>body{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;padding:16px}
h1{color:#d2a8ff;font-size:18px;margin-bottom:12px}#logs{background:#161b22;padding:14px;border-radius:8px;border:1px solid #30363d;white-space:pre-wrap;height:85vh;overflow-y:auto;font-size:13px;line-height:1.6}
.SUCCESS{color:#3fb950;font-weight:bold}.WARN{color:#d29922}.ERROR{color:#f85149;font-weight:bold}.INFO{color:#58a6ff}
</style></head><body><h1>🛰️ Dispatcher & Supervisor Log Monitor (Port 5003)</h1><div id="logs"></div>
<script>async function f(){try{const r=await fetch('/logs');const t=await r.text();const d=document.getElementById('logs');
d.innerHTML=t.replace(/\[SUCCESS\]/g,'<span class="SUCCESS">[SUCCESS]</span>').replace(/\[ERROR\]/g,'<span class="ERROR">[ERROR]</span>').replace(/\[WARN\]/g,'<span class="WARN">[WARN]</span>').replace(/\[INFO\]/g,'<span class="INFO">[INFO]</span>');
d.scrollTop=d.scrollHeight}catch(e){}}f();setInterval(f,2000);</script></body></html>"""
                self.wfile.write(html.encode("utf-8"))
            elif self.path == "/logs":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                content = "\n".join(dispatcher_log_history) if dispatcher_log_history else _read_log_tail(LOG_PATH_DISPATCHER)
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_error(404)

    def run_server():
        try:
            server = ReusableHTTPServer(("0.0.0.0", port), DispatcherWebLogHandler)
            log(f"Đã khởi động Dispatcher Web Log Server tại http://0.0.0.0:{port}", "INFO")
            server.serve_forever()
        except Exception as e:
            log(f"Cảnh báo khởi động Dispatcher Web Log Server port {port}: {e}", "WARN")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()


def start_web_log_server(port: int = 5000):
    def run_server():
        import time
        for attempt in range(5):
            try:
                server = ReusableHTTPServer(("0.0.0.0", port), WebLogHandler)
                log(f"Đã khởi động Web Log Server tại http://0.0.0.0:{port}", "INFO")
                server.serve_forever()
                return
            except OSError as e:
                if attempt < 4:
                    log(f"Port {port} bận ({e}), thử lại sau 2s... (lần {attempt+1}/5)", "WARN")
                    time.sleep(2)
                else:
                    log(f"Lỗi khởi động Web Log Server trên port {port}: {e}", "ERROR")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()



# ==========================================
# HELPER FUNCTIONS & REGEX
# ==========================================
def normalize_title(title: str) -> str:
    if not title:
        return ""
    clean = re.sub(r'[*`~_]', '', title).strip()
    return clean


def sanitize_name(name: str) -> str:
    if not name:
        return "Unassigned_Course"
    clean = re.sub(r'[*`~_]', '', name)
    clean = re.sub(r'[\\/*?:"<>|]', '', clean)
    clean = clean.strip().strip('.').strip('_')
    return clean[:120] if clean else "Unassigned_Course"


def is_metadata_line(line: str) -> bool:
    if not line:
        return True
    clean = re.sub(r'^[^\w\s]+', '', line).strip()
    if not clean:
        return True
    if re.match(r'^(artist|artist name|audio|subtitles?|legendas|course material|recursos adicionales|hashtag|for files|get files|publisher|language|format|size|duration)\b', clean, re.I):
        return True
    return line.startswith("#") or bool(re.match(r'^\d{1,2}:\d{2}$', line)) or line.startswith("http")


def extract_course_title(text: str) -> Optional[str]:
    if not text:
        return None
    if not re.search(r'🎨\s*Artist|🔊\s*Audio|📃\s*Subtitles|📁\s*Course|#️⃣\s*Hashtag|🖼', text, re.I):
        return None

    for line in text.splitlines():
        line = line.strip()
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        line = re.sub(r'^[🖼🎨🔊📃📁#️⃣\s]+', '', line).strip()

        if len(line) > 5 and not is_metadata_line(line) and not line.startswith("/") and not line.startswith("@"):
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                chosen = next((p for p in parts if re.search(r'[a-zA-Z]{4,}', p)), parts[-1])
                return normalize_title(str(chosen))
            return normalize_title(str(line))
    return None


def get_file_name(msg) -> Optional[str]:
    if not getattr(msg, "media", None) or not isinstance(msg.media, MessageMediaDocument):
        return None
    if getattr(msg, "file", None) and getattr(msg.file, "name", None):
        return str(msg.file.name)
    doc = getattr(msg.media, "document", None)
    if doc:
        for attr in getattr(doc, "attributes", []):
            if isinstance(attr, DocumentAttributeFilename):
                return str(attr.file_name)
    return None


# ==========================================
# STEP 6: STATUS CSV MANAGEMENT
# ==========================================
def load_csv_status() -> Dict[str, str]:
    status_map = {}
    if not CSV_PATH.exists():
        return status_map

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            status_map[normalize_title(row[0])] = row[1].strip()
    return status_map


def update_csv_status(title: str, status: str):
    clean_t = normalize_title(title)
    rows = []
    found = False
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                if normalize_title(row[0]) == clean_t:
                    rows.append([row[0].strip(), status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                    found = True
                else:
                    rows.append(row)

    if not found:
        rows.append([clean_t, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


import zipfile


def extract_single_archive(file_path: Path, extracted_dir: Path) -> bool:
    """
    Hàm giải nén đa định dạng thông minh (ZIP, RAR, 7Z, TAR, RAR giả dạng ZIP):
    1. Kiểm tra 7z/7za đầu tiên với cờ -y -aoa (overwrite all) & -p- (no prompt pass).
    2. Kiểm tra Python built-in zipfile nếu 7z thất bại.
    3. Thử unrar / tarfile cho các định dạng RAR/TAR.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        log(f"File nén rỗng hoặc không tồn tại: {file_path.name}", "WARN")
        return False

    cmd_7z = shutil.which("7z") or shutil.which("7za") or "7z"
    try:
        cmd = [cmd_7z, "x", "-y", "-aoa", "-p-", "-mmt=16", f"-o{extracted_dir}", str(file_path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
        if res.returncode == 0:
            log(f"✔ 7z đã giải nén thành công: {file_path.name}", "SUCCESS")
            return True
        else:
            log(f"Cảnh báo 7z ({file_path.name}): exit_code={res.returncode}, msg={res.stderr.strip()[:150] or res.stdout.strip()[:150]}", "WARN")
    except Exception as e:
        log(f"Lỗi 7z ({file_path.name}): {e}", "WARN")

    if file_path.suffix.lower() == ".zip":
        try:
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)
            log(f"✔ zipfile đã giải nén thành công: {file_path.name}", "SUCCESS")
            return True
        except Exception as e:
            log(f"Cảnh báo zipfile ({file_path.name}): {e}", "WARN")

    cmd_unrar = shutil.which("unrar") or "unrar"
    try:
        res = subprocess.run([cmd_unrar, "x", "-o+", "-p-", str(file_path), str(extracted_dir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
        if res.returncode == 0:
            log(f"✔ unrar đã giải nén thành công: {file_path.name}", "SUCCESS")
            return True
        else:
            log(f"Cảnh báo unrar ({file_path.name}): exit_code={res.returncode}", "WARN")
    except Exception as e:
        log(f"Lỗi unrar ({file_path.name}): {e}", "WARN")

    return False


def repackage_extracted(course_dir: Path, upload_dir: Path) -> bool:
    extracted_dir = course_dir / "extracted"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Phân loại file sau khi giải nén
    all_files = list(extracted_dir.rglob("*")) if extracted_dir.exists() else []
    video_files = [f for f in all_files if f.is_file() and f.suffix.lower() in ('.mp4', '.mkv', '.mov', '.avi')]
    other_files = [f for f in all_files if f.is_file() and f not in video_files]

    log(f"Kết quả giải nén tổng hợp: {len(video_files)} video, {len(other_files)} file tài liệu khác.", "SUCCESS")

    if not video_files and not other_files:
        log("Cảnh báo: Không tìm thấy file nào sau khi giải nén!", "WARN")
        return False

    # 1. Di chuyển toàn bộ video ra thư mục upload
    for vid in video_files:
        dest = upload_dir / vid.name
        if dest.exists():
            dest = upload_dir / f"{vid.stem}_{vid.stat().st_size}{vid.suffix}"
        shutil.move(str(vid), str(dest))

    # 2. Nén toàn bộ file còn lại (không phải video) thành Class_Materials.zip bằng 7z siêu tốc
    if other_files:
        log("Đóng gói tài liệu phụ thành Class_Materials.zip (Multi-threaded FAST)...", "INFO")
        zip_path = upload_dir / "Class_Materials.zip"
        cmd_7z = shutil.which("7z") or shutil.which("7za") or "7z"
        packed_ok = False
        try:
            # Dùng 7z nén đa luồng với -mx=1 để hoàn thành trong 2-3 giây
            pack_cmd = [cmd_7z, "a", "-tzip", "-mmt=on", "-mx=1", str(zip_path)] + [str(f) for f in other_files]
            pres = subprocess.run(pack_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
            if pres.returncode == 0 and zip_path.exists():
                log(f"✔ Đã tạo Class_Materials.zip ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)", "SUCCESS")
                packed_ok = True
        except Exception:
            pass

        if not packed_ok:
            try:
                import zipfile
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
                    for f in other_files:
                        arcname = f.relative_to(extracted_dir)
                        zf.write(f, arcname)
                log(f"✔ Đã tạo Class_Materials.zip ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)", "SUCCESS")
            except Exception as e:
                log(f"Cảnh báo: Không thể nén Class_Materials.zip: {e}", "WARN")

    # 3. Cập nhật mtime về thời gian hiện tại cho tất cả file trước khi upload
    for f in upload_dir.rglob("*"):
        if f.is_file():
            try:
                os.utime(str(f), None)
            except Exception:
                pass

    return True


# ==========================================
# STEP 5: RCLONE UPLOAD TO GOOGLE DRIVE
# ==========================================
def rclone_upload(upload_dir: Path, rclone_parent: str, course_title: str) -> bool:
    sanitized_folder = sanitize_name(course_title)
    target_remote_path = f"{rclone_parent.rstrip('/')}/{sanitized_folder}"

    log(f"Đang tải lên Google Drive qua Rclone (16GB RAM BEAST MODE: 256M CHUNK, 256M BUFFER, 6 TRANSFERS): {target_remote_path}...", "INFO")

    cmd = [
        "rclone", "copy", str(upload_dir), target_remote_path,
        "--transfers", "6",
        "--checkers", "16",
        "--drive-chunk-size", "256M",
        "--buffer-size", "256M",
        "--use-mmap",
        "--no-traverse",
        "--drive-pacer-min-sleep", "10ms",
        "--drive-pacer-burst", "200",
        "--drive-upload-cutoff", "0",
        "--drive-use-trash=false",
        "--progress", "--stats-one-line",
        "--stats", "2s",
        "--no-update-modtime"
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            line_str = line.strip()
            if line_str and ("Transferred:" in line_str or "ETA" in line_str):
                log(f"[RClone] {line_str}", "INFO")
        process.wait()

        if process.returncode == 0:
            log(f"✔ Đã upload thành công khóa học lên Rclone: {sanitized_folder}", "SUCCESS")
            return True
        else:
            log(f"✘ Lỗi Rclone upload, exit code: {process.returncode}", "ERROR")
            return False
    except Exception as e:
        log(f"Thất bại khi thực thi Rclone: {e}", "ERROR")
        return False


_remote_folders_cache = None

def get_all_remote_folders(rclone_parent: str) -> set:
    global _remote_folders_cache
    if _remote_folders_cache is not None:
        return _remote_folders_cache

    log(f"⚡ Đang quét 1 lần duy nhất toàn bộ thư mục đã có trên Google Drive...", "INFO")
    cmd = ["rclone", "lsf", rclone_parent, "--dirs-only", "--max-depth", "1", "--fast-list"]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode == 0:
            folders = set(line.strip().rstrip('/') for line in res.stdout.splitlines() if line.strip())
            _remote_folders_cache = folders
            log(f"✔ Đã quét xong! Tìm thấy {len(folders)} thư mục đã có sẵn trên Google Drive.", "SUCCESS")
            return _remote_folders_cache
    except Exception as e:
        log(f"Cảnh báo khi quét danh sách thư mục Google Drive: {e}", "WARN")

    _remote_folders_cache = set()
    return _remote_folders_cache


def check_rclone_folder_exists(rclone_parent: str, course_title: str) -> bool:
    sanitized_folder = sanitize_name(course_title)
    existing_folders = get_all_remote_folders(rclone_parent)
    return sanitized_folder in existing_folders


async def parallel_download_media(client: TelegramClient, msg: Any, save_path: Path, workers: int = 16) -> None:
    """Tải chuẩn từ Telegram API, đảm bảo 100% tính toàn vẹn byte không bị hỏng file nén"""
    await client.download_media(msg, file=str(save_path))


# ==========================================
# MAIN PIPELINE WORKFLOW
# ==========================================
SENTINEL_PREFIX = "##COURSE_START##"
SENTINEL_END    = "##COURSE_END##"

async def forward_course_to_relay(client: Any, relay_group_id: int, course_title: str, files: List[Tuple[str, Any]]) -> bool:
    """
    Forward toàn bộ file của 1 khóa học sang relay group với sentinel báo hiệu.
    Protocol:
      1. Gửi '##COURSE_START## <tên khóa>'
      2. Forward từng file message
      3. Gửi '##COURSE_END##'
    """
    try:
        relay_entity = await client.get_entity(relay_group_id)
        # Gửi sentinel bắt đầu
        await client.send_message(relay_entity, f"{SENTINEL_PREFIX} {course_title}")
        # Forward từng file
        for fname, msg in files:
            try:
                await client.forward_messages(relay_entity, msg)
                await asyncio.sleep(0.5)  # Tránh spam flood
            except Exception as e:
                log(f"  - ⚠️ Cảnh báo forward file {fname}: {e}", "WARN")
        # Gửi sentinel kết thúc
        await client.send_message(relay_entity, SENTINEL_END)
        log(f"  - ✔ Đã forward {len(files)} file của [{course_title}] sang relay group {relay_group_id}", "SUCCESS")
        return True
    except Exception as e:
        log(f"  - ✘ Lỗi forward sang relay group {relay_group_id}: {e}", "ERROR")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Telegram Course Pipeline Automator")
    parser.add_argument("-c", "--chat", help="Telegram Bot Target", default="@coursebusters_bot")
    parser.add_argument("-r", "--rclone-dest", help="Thư mục cha trên Google Drive qua Rclone (VD: gdrive:/COURSES)", default=None)
    parser.add_argument("-p", "--port", help="Cổng Web Monitor Log từ xa", type=int, default=5000)
    parser.add_argument("--relay-acc2", help="Relay Group ID cho Acc 2 (VD: -5040203514)", type=int, default=None)
    parser.add_argument("--relay-acc3", help="Relay Group ID cho Acc 3 (VD: -5281140814)", type=int, default=None)
    args = parser.parse_args()

    # Nạp Web Log Servers (Port 5000 Dashboard chính, Port 5003 Dispatcher riêng)
    start_web_log_server(args.port)
    start_dispatcher_web_log_server(5003)
    log("==========================================", "INFO")
    log("🚀 Bắt đầu quy trình Telegram Course Pipeline", "SUCCESS")
    log("==========================================", "INFO")

    # Cấu hình Rclone Parent Folder
    rclone_parent = args.rclone_dest or os.environ.get("RCLONE_PARENT_FOLDER") or "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"
    log(f"Thư mục cha Rclone Google Drive: {rclone_parent}", "INFO")

    # Cấu hình relay groups từ args hoặc biến môi trường
    relay_acc2 = args.relay_acc2 or (int(os.environ.get("RELAY_GROUP_ACC2", "0")) or None)
    relay_acc3 = args.relay_acc3 or (int(os.environ.get("RELAY_GROUP_ACC3", "0")) or None)

    if relay_acc2:
        log(f"⚡ Chế độ Round-Robin: Acc 2 relay group = {relay_acc2}", "INFO")
    if relay_acc3:
        log(f"⚡ Chế độ Round-Robin: Acc 3 relay group = {relay_acc3}", "INFO")
    if not relay_acc2 and not relay_acc3:
        log("⚡ Chế độ ĐƠN LẾ: Chỉ Acc 1 tải trực tiếp (chưa cấu hình relay).", "INFO")

    # Load Status từ full_hoahoc.csv
    csv_status = load_csv_status()

    # Lấy Telegram Credentials
    api_id_val = os.environ.get("TELERECON_API_ID")
    api_hash_val = os.environ.get("TELERECON_API_HASH")
    phone_val = os.environ.get("TELERECON_PHONE")

    if not api_id_val or not api_hash_val:
        # Thử đọc từ config.yaml
        config_yaml = BASE_DIR / "config.yaml"
        if config_yaml.exists() and yaml is not None:
            with open(config_yaml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                if data.get("api_id") and str(data.get("api_id")) != "your_api_id":
                    api_id_val = str(data.get("api_id"))
                    api_hash_val = str(data.get("api_hash"))

    if not api_id_val or not api_hash_val or api_id_val == "your_api_id" or api_id_val == "2040":
        api_id_val = "21724"
        api_hash_val = "3e0fe5dadb9b1612e3e5b6d912b72449"

    session_path = str(BASE_DIR / "pyrogram.session")
    client = TelegramClient(session_path, int(api_id_val), str(api_hash_val))

    if phone_val:
        await client.start(phone=phone_val)
    else:
        await client.start()

    me = await client.get_me()
    name = getattr(me, "first_name", "User") or "User"
    user_handle = getattr(me, "username", None) or getattr(me, "id", "")
    log(f"Đã kết nối Telegram Account: {name} (@{user_handle})", "SUCCESS")

    entity = await client.get_entity(args.chat)

    # ------------------------------------------
    # BƯỚC 1 & 2: LOAD MESSAGES & DETECT COURSES
    # ------------------------------------------
    log(f"BƯỚC 1 & 2: Load toàn bộ tin nhắn từ bot {args.chat} & Phân cụm bài đăng...", "INFO")
    messages = []
    async for msg in client.iter_messages(entity, limit=3000, reverse=True):
        messages.append(msg)

    courses_map: List[Tuple[str, List[Tuple[str, Any]]]] = []
    current_title = None
    current_files = []
    allowed_exts = (".rar", ".zip", ".7z", ".mp4", ".mkv", ".pdf", ".001", ".002", ".z01", ".z02")

    for msg in messages:
        msg_text = getattr(msg, "text", "") or ""
        title = extract_course_title(msg_text)
        if title:
            if current_title and current_files:
                courses_map.append((current_title, current_files))
            current_title = title
            current_files = []
            continue

        fname = get_file_name(msg)
        if fname and fname.lower().endswith(allowed_exts) and current_title:
            current_files.append((fname, msg))

    if current_title and current_files:
        courses_map.append((current_title, current_files))

    log(f"✔ Đã phân cụm thành công {len(courses_map)} khóa học từ luồng tin nhắn Bot!", "SUCCESS")

    # ------------------------------------------
    # BƯỚC 3, 4, 5, 6: DISPATCHER & WORKER CHẠY SONG SONG
    # ------------------------------------------
    # -------------------------------------------------------------
    # BƯỚC 3 & 4: BỘ ĐIỀU PHỐI GIÁM SÁT LIÊN TỤC & WORKER ĐỘC LẬP
    # -------------------------------------------------------------
    # Danh sách toàn bộ khóa học cần tải
    pending_pool: List[Tuple[int, str, List[Tuple[str, Any]]]] = []
    for idx, (c_title, c_files) in enumerate(courses_map, 1):
        clean_t = normalize_title(c_title)
        st = csv_status.get(clean_t, "PENDING")
        if st in ("COMPLETED", "FAILED_DOWNLOAD", "FAILED_EXTRACT", "FAILED_RCLONE"):
            continue
        if check_rclone_folder_exists(rclone_parent, c_title):
            update_csv_status(c_title, "COMPLETED")
            continue
        pending_pool.append((idx, c_title, c_files))

    log(f"📋 Danh sách khóa học chờ phân công: {len(pending_pool)}/{len(courses_map)} khóa", "SUCCESS")

    pool_idx = 0
    pool_lock = asyncio.Lock()

    acc1_queue: asyncio.Queue = asyncio.Queue()
    acc1_is_busy = False
    acc1_dispatching = False   # Flag ngăn double-assign trong dispatcher

    acc2_current_course: Optional[str] = None
    acc3_current_course: Optional[str] = None

    async def get_next_unprocessed_course() -> Optional[Tuple[int, str, List[Tuple[str, Any]]]]:
        nonlocal pool_idx
        async with pool_lock:
            while pool_idx < len(pending_pool):
                item = pending_pool[pool_idx]
                pool_idx += 1
                c_title = normalize_title(item[1])
                st = load_csv_status().get(c_title, "PENDING")
                if st in ("COMPLETED", "FORWARDED_ACC2", "FORWARDED_ACC3", "FAILED_DOWNLOAD", "FAILED_EXTRACT", "FAILED_RCLONE"):
                    continue
                if check_rclone_folder_exists(rclone_parent, item[1]):
                    update_csv_status(item[1], "COMPLETED")
                    continue
                return item
            return None

    # ── Dispatcher Giám Sát & Điều Phối Liên Tục ─────────────
    async def continuous_dispatcher():
        nonlocal acc2_current_course, acc3_current_course, acc1_dispatching
        log_msg = "🚀 [DISPATCHER] Khởi chạy Bộ Giám Sát & Điều Phối Liên Tục 3 Worker..."
        log(log_msg, "SUCCESS")
        log_dispatcher(log_msg, "SUCCESS")

        while True:
            latest_csv = load_csv_status()

            # 1. Giám sát trạng thái Acc 2
            if relay_acc2 and acc2_current_course:
                st2 = latest_csv.get(normalize_title(acc2_current_course), "FORWARDED_ACC2")
                if st2 != "FORWARDED_ACC2":
                    msg = f"✔ [DISPATCHER] 🔵 Acc 2 đã xong [{acc2_current_course}] (status={st2})! Sẵn sàng nhận khóa tiếp theo."
                    log(msg, "SUCCESS")
                    log_dispatcher(msg, "SUCCESS")
                    acc2_current_course = None

            # 2. Giám sát trạng thái Acc 3
            if relay_acc3 and acc3_current_course:
                st3 = latest_csv.get(normalize_title(acc3_current_course), "FORWARDED_ACC3")
                if st3 != "FORWARDED_ACC3":
                    msg = f"✔ [DISPATCHER] 🟠 Acc 3 đã xong [{acc3_current_course}] (status={st3})! Sẵn sàng nhận khóa tiếp theo."
                    log(msg, "SUCCESS")
                    log_dispatcher(msg, "SUCCESS")
                    acc3_current_course = None

            # 3. Phân công cho Acc 1 chỉ khi THỰC SỰ rảnh (không busy, queue rỗng, và không đang dispatch)
            if not acc1_is_busy and acc1_queue.empty() and not acc1_dispatching:
                acc1_dispatching = True
                item = await get_next_unprocessed_course()
                if item:
                    idx, c_title, c_files = item
                    msg = f"🟢 [DISPATCHER] Acc 1 rảnh -> Giao khóa [{c_title}] vào Acc 1 Worker Queue"
                    log(msg, "INFO")
                    log_dispatcher(msg, "INFO")
                    await acc1_queue.put(item)
                acc1_dispatching = False

            # 4. Phân công cho Acc 2 ngay khi Acc 2 rảnh
            if relay_acc2 and acc2_current_course is None:
                item = await get_next_unprocessed_course()
                if item:
                    idx, c_title, c_files = item
                    clean_t = normalize_title(c_title)
                    msg = f"🔵 [DISPATCHER] Acc 2 rảnh -> Forward khóa [{clean_t}] ({len(c_files)} file) sang Group Acc 2 ({relay_acc2})..."
                    log(msg, "INFO")
                    log_dispatcher(msg, "INFO")
                    fwd_ok = await forward_course_to_relay(client, relay_acc2, c_title, c_files)
                    if fwd_ok:
                        update_csv_status(c_title, "FORWARDED_ACC2")
                        acc2_current_course = clean_t
                    else:
                        update_csv_status(c_title, "FAILED_FORWARD")

            # 5. Phân công cho Acc 3 ngay khi Acc 3 rảnh
            if relay_acc3 and acc3_current_course is None:
                item = await get_next_unprocessed_course()
                if item:
                    idx, c_title, c_files = item
                    clean_t = normalize_title(c_title)
                    msg = f"🟠 [DISPATCHER] Acc 3 rảnh -> Forward khóa [{clean_t}] ({len(c_files)} file) sang Group Acc 3 ({relay_acc3})..."
                    log(msg, "INFO")
                    log_dispatcher(msg, "INFO")
                    fwd_ok = await forward_course_to_relay(client, relay_acc3, c_title, c_files)
                    if fwd_ok:
                        update_csv_status(c_title, "FORWARDED_ACC3")
                        acc3_current_course = clean_t
                    else:
                        update_csv_status(c_title, "FAILED_FORWARD")

            # Kiểm tra xem toàn bộ danh sách đã hoàn thành chưa
            if pool_idx >= len(pending_pool) and acc1_queue.empty() and not acc1_is_busy and not acc2_current_course and not acc3_current_course:
                done_msg = "🎉 [DISPATCHER] Toàn bộ các khóa học đã được phân công và xử lý hoàn tất!"
                log(done_msg, "SUCCESS")
                log_dispatcher(done_msg, "SUCCESS")
                await acc1_queue.put(None)
                break

            await asyncio.sleep(2)  # Quét và theo dõi liên tục mỗi 2 giây

    # ── Worker Acc 1 (Tải & Upload Trực Tiếp Độc Lập) ───────────
    async def acc1_worker_loop():
        nonlocal acc1_is_busy
        while True:
            item = await acc1_queue.get()
            if item is None:
                acc1_queue.task_done()
                break

            acc1_is_busy = True
            idx, course_title, files = item
            log(f"\n==========================================", "INFO")
            log(f"▶ [Acc 1 Worker] XỬ LÝ KHÓA [{idx}/{len(courses_map)}]: {course_title}", "SUCCESS")
            log(f"Tổng số file đính kèm: {len(files)}", "INFO")
            log("==========================================", "INFO")

            # Ước lượng dung lượng course (MB → GB) để chọn RAM hay đĩa
            total_mb = sum(
                getattr(m.file, "size", 0) / 1024 / 1024
                for _, m in files if getattr(m, "file", None)
            )
            estimated_gb = max(total_mb / 1024 * 2.5, 2.0)  # x2.5 vì giải nén thường lớn hơn rar

            course_dir = get_temp_dir_for_course(course_title, estimated_gb)
            archives_dir = course_dir / "archives"
            upload_dir = course_dir / "upload"
            extracted_dir = course_dir / "extracted"

            for d in [archives_dir, upload_dir, extracted_dir]:
                d.mkdir(parents=True, exist_ok=True)

            # Giảm concurrency khi dùng đĩa (tránh disk I/O bão hòa)
            is_ram = _PREFER_RAM and str(course_dir).startswith("/dev/shm")
            max_concurrent = 4 if is_ram else 2  # RAM: 4 song song, đĩa: 2 song song
            log(f"BƯỚC 3 & 4: Tải & Giải nén trực tiếp ({max_concurrent} file song song, {'RAM disk' if is_ram else 'đĩa thường'})...", "INFO")
            download_success = True
            file_semaphore = asyncio.Semaphore(max_concurrent)

            async def process_single_file(filename: str, msg: Any):
                nonlocal download_success
                save_path = archives_dir / filename
                file_size = getattr(msg.file, "size", 0) if getattr(msg, "file", None) else 0
                size_mb = file_size / 1024 / 1024 if file_size else 0.0
                # Timeout dựa theo tốc độ tối thiểu: 1MB/s, tối đa 3h
                dl_timeout = min(max(int(size_mb / 1.0), 300), 10800)

                async with file_semaphore:
                    log(f"  - 🚀 Bắt đầu tải: {filename} ({size_mb:.1f} MB, timeout={dl_timeout//60}phút)...", "INFO")
                    try:
                        # Progress watchdog: hủy nếu 5 phút không có bytes mới
                        last_size = [0]
                        last_progress_time = [asyncio.get_event_loop().time()]
                        STALL_TIMEOUT = 300  # 5 phút không có bytes mới

                        async def watchdog():
                            while True:
                                await asyncio.sleep(60)
                                cur = save_path.stat().st_size if save_path.exists() else 0
                                if cur > last_size[0]:
                                    last_size[0] = cur
                                    last_progress_time[0] = asyncio.get_event_loop().time()
                                    log(f"  - 📊 [{filename}] Progress: {cur/1024/1024:.1f}MB/{size_mb:.1f}MB", "INFO")
                                elif asyncio.get_event_loop().time() - last_progress_time[0] > STALL_TIMEOUT:
                                    raise asyncio.TimeoutError(f"Stalled 5min")

                        wd_task = asyncio.ensure_future(watchdog())
                        try:
                            await asyncio.wait_for(
                                client.download_media(msg, file=str(save_path)),
                                timeout=dl_timeout
                            )
                        finally:
                            wd_task.cancel()

                        log(f"  - ✔ Tải xong {filename}, ⚡ Giải nén trực tiếp...", "SUCCESS")
                        if not re.search(r'\.part\d+\.rar$', filename, re.I):
                            extract_single_archive(save_path, extracted_dir)
                    except asyncio.TimeoutError:
                        elapsed = int(asyncio.get_event_loop().time() - last_progress_time[0])
                        log(f"  - ✘ STALL/TIMEOUT sau {elapsed}s khi tải {filename}, bỏ qua.", "ERROR")
                        download_success = False
                    except Exception as e:
                        log(f"Thất bại khi xử lý {filename}: {e}", "ERROR")
                        download_success = False

            tasks = [process_single_file(fn, m) for fn, m in files]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=21600)
            except asyncio.TimeoutError:
                log(f"✘ TIMEOUT 6h toàn khóa {course_title}, dừng xử lý.", "ERROR")
                download_success = False

            if not download_success:
                log(f"Khóa học {course_title} bị lỗi khi tải/giải nén file, dọn dẹp & chuyển sang khóa tiếp theo.", "ERROR")
                update_csv_status(course_title, "FAILED_DOWNLOAD")
                shutil.rmtree(str(course_dir), ignore_errors=True)
                acc1_is_busy = False
                acc1_queue.task_done()
                continue

            for file_path in archives_dir.glob("*.rar"):
                if re.search(r'\.part0?1\.rar$', file_path.name, re.I):
                    extract_single_archive(file_path, extracted_dir)

            log("Đóng gói & Phân loại file (.mp4 và Class_Materials.zip)...", "INFO")
            extracted_ok = repackage_extracted(course_dir, upload_dir)
            if not extracted_ok:
                log(f"Lỗi ở bước đóng gói cho khóa {course_title}, dọn dẹp & chuyển sang khóa tiếp theo.", "ERROR")
                update_csv_status(course_title, "FAILED_EXTRACT")
                shutil.rmtree(str(course_dir), ignore_errors=True)
                acc1_is_busy = False
                acc1_queue.task_done()
                continue

            log("BƯỚC 5: Upload lên Google Drive qua Rclone...", "INFO")
            uploaded_ok = rclone_upload(upload_dir, rclone_parent, course_title)
            if not uploaded_ok:
                log(f"Thất bại khi Upload Rclone cho khóa {course_title}, dọn dẹp & chuyển sang khóa tiếp theo.", "ERROR")
                update_csv_status(course_title, "FAILED_RCLONE")
                shutil.rmtree(str(course_dir), ignore_errors=True)
                acc1_is_busy = False
                acc1_queue.task_done()
                continue

            log("BƯỚC 6: Kiểm tra, Xóa tài nguyên tạm trên Ubuntu & Lưu CSV status...", "SUCCESS")
            try:
                shutil.rmtree(str(course_dir))
                log(f"✔ Đã giải phóng dung lượng đĩa Ubuntu: Xóa {course_dir.name}", "INFO")
            except Exception as e:
                log(f"Cảnh báo khi xóa thư mục tạm: {e}", "WARN")

            update_csv_status(course_title, "COMPLETED")
            log(f"🎉 HOÀN THÀNH TOÀN BỘ WORKFLOW CHO KHÓA: {course_title}\n", "SUCCESS")
            acc1_is_busy = False
            acc1_queue.task_done()

    log("🚀 Khởi chạy Bộ Giám Sát Dispatcher & Acc 1 Worker song song...", "SUCCESS")
    await asyncio.gather(continuous_dispatcher(), acc1_worker_loop())

    log("\n==========================================", "SUCCESS")
    log("🏁 QUY TRÌNH ĐÃ XỬ LÝ XONG TẤT CẢ CÁC KHÓA HỌC!", "SUCCESS")
    log("==========================================", "SUCCESS")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
