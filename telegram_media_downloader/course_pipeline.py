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
TEMP_DIR = BASE_DIR / "temp_processing"

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
class WebLogHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return  # Suppress default HTTP logging

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = r"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Telegram Course Pipeline Log Monitor</title>
    <style>
        body { background: #0d1117; color: #c9d1d9; font-family: ui-sans-serif, system-ui, sans-serif; padding: 20px; }
        h1 { color: #58a6ff; font-size: 20px; border-bottom: 1px solid #30363d; padding-bottom: 10px; margin-top: 0; }
        #logs { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; height: 72vh; overflow-y: auto; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; line-height: 1.5; }
        .SUCCESS { color: #3fb950; font-weight: bold; }
        .WARN { color: #d29922; }
        .ERROR { color: #f85149; font-weight: bold; }
        .INFO { color: #58a6ff; }
        .controls { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
        button { background: #238636; color: white; border: 0; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 13px; }
        button:hover { background: #2ea043; }
        button.secondary { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; }
        button.secondary:hover { background: #30363d; color: white; }
        label { margin-left: auto; font-size: 13px; color: #8b949e; cursor: pointer; }
    </style>
</head>
<body>
    <h1>🚀 Telegram Course Pipeline Live Log Monitor</h1>
    <div class="controls">
        <button onclick="fetchLogs()">🔄 Làm mới Logs</button>
        <button onclick="window.location.href='/api/download-log'" class="secondary">📥 Xuất Log (.txt)</button>
        <button onclick="window.location.href='/api/download-csv'" class="secondary">📊 Tải CSV Status</button>
        <label><input type="checkbox" id="autoscroll" checked> Tự động cuộn xuống</label>
    </div>
    <div id="logs">Đang kết nối tới Server Logs...</div>
    <script>
        async function fetchLogs() {
            try {
                const res = await fetch('/api/logs');
                const text = await res.text();
                const container = document.getElementById('logs');
                container.innerHTML = text.replace(/\[SUCCESS\]/g, '<span class="SUCCESS">[SUCCESS]</span>')
                                          .replace(/\[ERROR\]/g, '<span class="ERROR">[ERROR]</span>')
                                          .replace(/\[WARN\]/g, '<span class="WARN">[WARN]</span>')
                                          .replace(/\[INFO\]/g, '<span class="INFO">[INFO]</span>');
                if (document.getElementById('autoscroll').checked) {
                    container.scrollTop = container.scrollHeight;
                }
            } catch(e){}
        }
        setInterval(fetchLogs, 2000);
        fetchLogs();
    </script>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("\n".join(log_history).encode("utf-8"))
        elif self.path == "/api/download-log":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            filename = f"pipeline-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
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


def start_web_log_server(port: int = 5000):
    def run_server():
        server = HTTPServer(("0.0.0.0", port), WebLogHandler)
        log(f"Đã khởi động Web Log Server tại http://0.0.0.0:{port}", "INFO")
        server.serve_forever()

    t = threading.Thread(target=run_server, daemon=True)
    t.start()


# ==========================================
# HELPER FUNCTIONS & REGEX
# ==========================================
def sanitize_name(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
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
                return str(chosen)
            return str(line)
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
            if not row:
                continue
            title = row[0].strip()
            status = row[1].strip() if len(row) > 1 else "PENDING"
            status_map[title] = status
    return status_map


def update_csv_status(title: str, status: str):
    rows = []
    found = False
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                if row[0].strip() == title.strip():
                    rows.append([row[0].strip(), status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                    found = True
                else:
                    rows.append(row)

    if not found:
        rows.append([title.strip(), status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


import zipfile


def extract_single_archive(file_path: Path, extracted_dir: Path) -> bool:
    """Giải nén an toàn: Thử 7z/7za trước (vì 7z xử lý được cả RAR đổi tên thành ZIP), sau đó thử zipfile & unrar"""
    cmd_7z = shutil.which("7z") or shutil.which("7za") or "/usr/bin/7z"
    try:
        cmd = [cmd_7z if cmd_7z else "7z", "x", "-y", "-mmt=on", f"-o{extracted_dir}", str(file_path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return True
    except Exception as e:
        log(f"Cảnh báo 7z: {e}", "WARN")

    if file_path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)
            return True
        except Exception as e:
            log(f"Cảnh báo zipfile: {e}", "WARN")

    cmd_unrar = shutil.which("unrar") or "/usr/bin/unrar"
    try:
        res = subprocess.run([cmd_unrar if cmd_unrar else "unrar", "x", "-o+", str(file_path), str(extracted_dir)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    return False


# ==========================================
# STEP 4: ARCHIVE EXTRACTION & RE-PACKAGING
# ==========================================
def extract_and_repackage(course_dir: Path, upload_dir: Path) -> bool:
    archives_dir = course_dir / "archives"
    extracted_dir = course_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    log(f"Bắt đầu giải nén tài nguyên trong {archives_dir.name}...", "INFO")

    archive_files = list(archives_dir.glob("*.rar")) + list(archives_dir.glob("*.zip")) + list(archives_dir.glob("*.7z"))
    if not archive_files:
        log("Không tìm thấy file nén trong thư mục archives.", "WARN")
        return False

    for file_path in archive_files:
        if re.search(r'\.part(0[2-9]|[1-9]\d+)\.rar$', file_path.name, re.I):
            continue

        log(f"Đang giải nén file: {file_path.name}...", "INFO")
        extract_single_archive(file_path, extracted_dir)

    # Phân loại file sau khi giải nén
    all_files = list(extracted_dir.rglob("*"))
    video_files = [f for f in all_files if f.is_file() and f.suffix.lower() in ('.mp4', '.mkv', '.mov', '.avi')]
    other_files = [f for f in all_files if f.is_file() and f not in video_files]

    log(f"Kết quả giải nén: {len(video_files)} video (.mp4), {len(other_files)} file tài liệu khác.", "SUCCESS")

    # 1. Di chuyển toàn bộ video .mp4 ra thư mục upload
    for vid in video_files:
        dest = upload_dir / vid.name
        # Tránh ghi đè nếu trùng tên
        if dest.exists():
            dest = upload_dir / f"{vid.stem}_{vid.stat().st_size}{vid.suffix}"
        shutil.move(str(vid), str(dest))

    # 2. Nén toàn bộ file còn lại không phải video thành 1 file Class_Materials.zip duy nhất
    if other_files:
        materials_zip_path = upload_dir / "Class_Materials.zip"
        log("Đang đóng gói tài liệu phụ thành Class_Materials.zip...", "INFO")
        shutil.make_archive(str(upload_dir / "Class_Materials"), 'zip', str(extracted_dir))

    return True


# ==========================================
# STEP 5: RCLONE UPLOAD TO GOOGLE DRIVE
# ==========================================
def rclone_upload(upload_dir: Path, rclone_parent: str, course_title: str) -> bool:
    sanitized_folder = sanitize_name(course_title)
    target_remote_path = f"{rclone_parent.rstrip('/')}/{sanitized_folder}"

    log(f"Đang tải lên Google Drive qua Rclone: {target_remote_path}...", "INFO")

    cmd = ["rclone", "copy", str(upload_dir), target_remote_path, "--progress", "--stats-one-line"]
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


def check_rclone_folder_exists(rclone_parent: str, course_title: str) -> bool:
    sanitized_folder = sanitize_name(course_title)
    target_remote_path = f"{rclone_parent.rstrip('/')}/{sanitized_folder}"

    log(f"Đang kiểm tra tồn tại trên Rclone Google Drive: {target_remote_path}...", "INFO")
    cmd = ["rclone", "lsf", target_remote_path, "--max-depth", "1"]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
        if res.returncode == 0 and res.stdout.strip():
            return True
    except Exception as e:
        log(f"Cảnh báo khi kiểm tra rclone lsf: {e}", "WARN")
    return False


async def parallel_download_media(client: TelegramClient, msg: Any, save_path: Path, workers: int = 16) -> None:
    file_size = getattr(msg.file, "size", 0) if getattr(msg, "file", None) else 0
    if not file_size or file_size < 5 * 1024 * 1024:
        await client.download_media(msg, file=str(save_path))
        return

    chunk_size = 512 * 1024
    total_chunks = (file_size + chunk_size - 1) // chunk_size

    temp_path = save_path.with_suffix(save_path.suffix + ".tmp")
    with open(temp_path, "wb") as f:
        f.truncate(file_size)

    semaphore = asyncio.Semaphore(workers)

    async def download_part(chunk_index: int):
        async with semaphore:
            offset = chunk_index * chunk_size
            limit = min(chunk_size, file_size - offset)
            for attempt in range(3):
                try:
                    data = await client.download_file(msg.media, offset=offset, limit=limit)
                    if data:
                        with open(temp_path, "r+b") as f:
                            f.seek(offset)
                            f.write(data)
                        return
                except Exception:
                    await asyncio.sleep(0.3)

    tasks = [download_part(i) for i in range(total_chunks)]
    await asyncio.gather(*tasks)

    if temp_path.exists() and temp_path.stat().st_size == file_size:
        temp_path.replace(save_path)
    else:
        await client.download_media(msg, file=str(save_path))
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


# ==========================================
# MAIN PIPELINE WORKFLOW
# ==========================================
async def main():
    parser = argparse.ArgumentParser(description="Telegram Course Pipeline Automator")
    parser.add_argument("-c", "--chat", help="Telegram Bot Target", default="@coursebusters_bot")
    parser.add_argument("-r", "--rclone-dest", help="Thư mục cha trên Google Drive qua Rclone (VD: gdrive:/COURSES)", default=None)
    parser.add_argument("-p", "--port", help="Cổng Web Monitor Log từ xa", type=int, default=5000)
    args = parser.parse_args()

    # Nạp Web Log Server
    start_web_log_server(args.port)
    log("==========================================", "INFO")
    log("🚀 Bắt đầu quy trình Telegram Course Pipeline", "SUCCESS")
    log("==========================================", "INFO")

    # Cấu hình Rclone Parent Folder
    rclone_parent = args.rclone_dest or os.environ.get("RCLONE_PARENT_FOLDER") or "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"
    log(f"Thư mục cha Rclone Google Drive: {rclone_parent}", "INFO")

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

    if not api_id_val or not api_hash_val or api_id_val == "your_api_id":
        api_id_val = "2040"
        api_hash_val = "b18441a12607e109d9496d9a244ead1c"

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
    # BƯỚC 3, 4, 5, 6: VÒNG LẶP XỬ LÝ TỪNG KHÓA
    # ------------------------------------------
    for idx, (course_title, files) in enumerate(courses_map, 1):
        log(f"\n==========================================", "INFO")
        log(f"▶ XỬ LÝ KHÓA [{idx}/{len(courses_map)}]: {course_title}", "SUCCESS")
        log(f"Tổng số file đính kèm: {len(files)}", "INFO")
        log("==========================================", "INFO")

        # 1. Kiểm tra xem đã hoàn tất trong full_hoahoc.csv chưa
        current_status = csv_status.get(course_title, "PENDING")
        if current_status == "COMPLETED":
            log(f"⏭ Đã đánh dấu COMPLETED trong full_hoahoc.csv, BỎ QUA.", "WARN")
            continue

        # 2. Kiểm tra trước xem thư mục khóa học đã tồn tại trên Rclone Google Drive chưa
        if check_rclone_folder_exists(rclone_parent, course_title):
            log(f"⏭ Thư mục đã TỒN TẠI trên Google Drive (Rclone), BỎ QUA & cập nhật CSV status thành COMPLETED.", "SUCCESS")
            update_csv_status(course_title, "COMPLETED")
            csv_status[course_title] = "COMPLETED"
            continue

        # Thư mục làm việc tạm thời cho khóa học này
        course_dir = TEMP_DIR / sanitize_name(course_title)
        archives_dir = course_dir / "archives"
        upload_dir = course_dir / "upload"

        archives_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)


        # BƯỚC 3: TẢI TỪNG FILE ĐÍNH KÈM CỦA KHÓA
        log("BƯỚC 3: Tải file đính kèm của khóa học (16 luồng song song)...", "INFO")
        download_success = True
        for filename, msg in files:
            save_path = archives_dir / filename
            file_size = getattr(msg.file, "size", 0) if getattr(msg, "file", None) else 0
            if save_path.exists() and save_path.stat().st_size == file_size:
                log(f"  - File đã tồn tại: {filename}", "INFO")
                continue

            size_mb = file_size / 1024 / 1024 if file_size else 0.0
            log(f"  - Đang tải [16 luồng]: {filename} ({size_mb:.1f} MB)", "INFO")
            try:
                await parallel_download_media(client, msg, save_path, workers=16)
            except Exception as e:
                log(f"Thất bại khi tải {filename}: {e}", "ERROR")
                download_success = False

        if not download_success:
            log(f"Khóa học {course_title} bị lỗi khi tải file, chuyển sang khóa tiếp theo.", "ERROR")
            update_csv_status(course_title, "FAILED_DOWNLOAD")
            continue

        # BƯỚC 4: GIẢI NÉN & ĐÓNG GÓI (.MP4 VÀ CLASS_MATERIALS.ZIP)
        log("BƯỚC 4: Giải nén & Phân loại file...", "INFO")
        extracted_ok = extract_and_repackage(course_dir, upload_dir)
        if not extracted_ok:
            log(f"Lỗi ở bước giải nén cho khóa {course_title}", "ERROR")
            update_csv_status(course_title, "FAILED_EXTRACT")
            continue

        # BƯỚC 5: UPLOAD LÊN GOOGLE DRIVE QUA RCLONE
        log("BƯỚC 5: Upload lên Google Drive qua Rclone...", "INFO")
        uploaded_ok = rclone_upload(upload_dir, rclone_parent, course_title)
        if not uploaded_ok:
            log(f"Thất bại khi Upload Rclone cho khóa {course_title}", "ERROR")
            update_csv_status(course_title, "FAILED_RCLONE")
            continue

        # BƯỚC 6: XÓA SẢN PHẨM TRÊN UBUNTU & CẬP NHẬT CSV STATUS
        log("BƯỚC 6: Kiểm tra, Xóa tài nguyên tạm trên Ubuntu & Lưu CSV status...", "SUCCESS")
        try:
            shutil.rmtree(str(course_dir))
            log(f"✔ Đã giải phóng dung lượng đĩa Ubuntu: Xóa {course_dir.name}", "INFO")
        except Exception as e:
            log(f"Cảnh báo khi xóa thư mục tạm: {e}", "WARN")

        # Cập nhật CSV status thành COMPLETED
        update_csv_status(course_title, "COMPLETED")
        csv_status[course_title] = "COMPLETED"
        log(f"🎉 HOÀN THÀNH TOÀN BỘ WORKFLOW CHO KHÓA: {course_title}\n", "SUCCESS")

    log("\n==========================================", "SUCCESS")
    log("🏁 QUY TRÌNH ĐÃ XỬ LÝ XONG TẤT CẢ CÁC KHÓA HỌC!", "SUCCESS")
    log("==========================================", "SUCCESS")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
