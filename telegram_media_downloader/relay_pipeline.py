#!/usr/bin/env python3
# pyright: reportGeneralTypeIssues=false
# pyright: reportOptionalMemberAccess=false
# pyright: reportAttributeAccessIssue=false
# type: ignore
"""
Relay Pipeline - Acc 2 / Acc 3
Lắng nghe tin nhắn được forward vào relay group từ Acc 1 (master),
tải xuống và upload lên Google Drive độc lập theo cùng quy trình.

Chạy lệnh:
  python3 relay_pipeline.py --session pyrogram_acc2 --group -5040203514 --port 5001
  python3 relay_pipeline.py --session pyrogram_acc3 --group -5281140814 --port 5002
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
from typing import List, Tuple, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename
except ImportError:
    print("Vui lòng cài đặt: pip install telethon")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp_processing_relay"

# ==========================================
# LOGGING
# ==========================================
log_history: List[str] = []

def log(msg: str, level: str = "INFO", log_path: Optional[Path] = None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    log_history.append(formatted)
    if len(log_history) > 2000:
        log_history.pop(0)
    print(formatted, flush=True)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass


# ==========================================
# WEB LOG MONITOR
# ==========================================
class WebLogHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
<title>Relay Pipeline Log Monitor</title>
<style>
body { background: #0d1117; color: #c9d1d9; font-family: ui-sans-serif, system-ui, sans-serif; padding: 20px; }
h1 { color: #58a6ff; font-size: 20px; border-bottom: 1px solid #30363d; padding-bottom: 10px; margin-top: 0; }
#logs { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px;
        height: 80vh; overflow-y: auto; white-space: pre-wrap;
        font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; line-height: 1.5; }
.SUCCESS { color: #3fb950; font-weight: bold; }
.WARN { color: #d29922; }
.ERROR { color: #f85149; font-weight: bold; }
.INFO { color: #58a6ff; }
</style></head><body>
<h1>🚀 Relay Pipeline Log Monitor</h1>
<div id="logs"></div>
<script>
async function fetchLogs() {
  const r = await fetch('/logs'); const t = await r.text();
  const d = document.getElementById('logs');
  d.innerHTML = t.split('\\n').map(l => {
    const m = l.match(/\\[(SUCCESS|WARN|ERROR|INFO)\\]/);
    return m ? `<span class="${m[1]}">${l}</span>` : l;
  }).join('\\n');
  d.scrollTop = d.scrollHeight;
}
fetchLogs(); setInterval(fetchLogs, 2000);
</script></body></html>"""
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/logs":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("\n".join(log_history).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def start_web_log_server(port: int):
    def _serve():
        server = HTTPServer(("0.0.0.0", port), WebLogHandler)
        server.serve_forever()
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    log(f"Đã khởi động Relay Web Log Server tại http://0.0.0.0:{port}", "INFO")


# ==========================================
# HELPERS
# ==========================================
SENTINEL_PREFIX = "##COURSE_START##"
SENTINEL_END    = "##COURSE_END##"

def sanitize_name(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name.strip().strip(".")[:120]

def get_file_name(msg: Any) -> Optional[str]:
    if not msg.media:
        return None
    if hasattr(msg.media, "document") and msg.media.document:
        for attr in msg.media.document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name
    return None

def extract_single_archive(file_path: Path, extracted_dir: Path) -> bool:
    if not file_path.exists() or file_path.stat().st_size == 0:
        log(f"File nén rỗng hoặc không tồn tại: {file_path.name}", "WARN")
        return False
    cmd_7z = shutil.which("7z") or shutil.which("7za") or "7z"
    try:
        cmd = [cmd_7z, "x", "-y", "-aoa", "-p-", "-mmt=on", f"-o{extracted_dir}", str(file_path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        if res.returncode == 0:
            log(f"✔ 7z đã giải nén thành công: {file_path.name}", "SUCCESS")
            return True
        else:
            log(f"Cảnh báo 7z ({file_path.name}): {res.returncode}", "WARN")
    except Exception as e:
        log(f"Lỗi 7z ({file_path.name}): {e}", "WARN")

    if file_path.suffix.lower() == ".zip":
        try:
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(extracted_dir)
            log(f"✔ zipfile đã giải nén thành công: {file_path.name}", "SUCCESS")
            return True
        except Exception as e:
            log(f"Cảnh báo zipfile ({file_path.name}): {e}", "WARN")

    cmd_unrar = shutil.which("unrar") or "unrar"
    try:
        res = subprocess.run([cmd_unrar, "x", "-o+", "-p-", str(file_path), str(extracted_dir)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
        if res.returncode == 0:
            log(f"✔ unrar đã giải nén thành công: {file_path.name}", "SUCCESS")
            return True
    except Exception as e:
        log(f"Lỗi unrar ({file_path.name}): {e}", "WARN")
    return False

def repackage_and_upload(course_dir: Path, upload_dir: Path, rclone_parent: str, course_title: str) -> bool:
    extracted_dir = course_dir / "extracted"
    upload_dir.mkdir(parents=True, exist_ok=True)
    all_files = list(extracted_dir.rglob("*")) if extracted_dir.exists() else []
    video_files = [f for f in all_files if f.is_file() and f.suffix.lower() in ('.mp4', '.mkv', '.mov', '.avi')]
    other_files = [f for f in all_files if f.is_file() and f not in video_files]
    log(f"Giải nén xong: {len(video_files)} video, {len(other_files)} file tài liệu khác.", "SUCCESS")

    if not video_files and not other_files:
        log("Cảnh báo: Không tìm thấy file nào sau khi giải nén!", "WARN")
        return False

    # 1. Di chuyển video ra thư mục upload
    for vid in video_files:
        dest = upload_dir / vid.name
        if dest.exists():
            dest = upload_dir / f"{vid.stem}_{vid.stat().st_size}{vid.suffix}"
        shutil.move(str(vid), str(dest))

    # 2. Nén tài liệu phụ thành Class_Materials.zip
    if other_files:
        log("Đóng gói tài liệu phụ thành Class_Materials.zip...", "INFO")
        try:
            import zipfile
            zip_path = upload_dir / "Class_Materials.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in other_files:
                    arcname = f.relative_to(extracted_dir)
                    zf.write(f, arcname)
            log(f"✔ Đã tạo Class_Materials.zip ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)", "SUCCESS")
        except Exception as e:
            log(f"Cảnh báo: Không thể nén Class_Materials.zip: {e}", "WARN")

    # 3. Cập nhật mtime về thời gian hiện tại
    for f in upload_dir.rglob("*"):
        if f.is_file():
            try:
                os.utime(str(f), None)
            except Exception:
                pass

    # 4. Rclone upload
    sanitized_folder = sanitize_name(course_title)
    target_remote_path = f"{rclone_parent.rstrip('/')}/{sanitized_folder}"
    log(f"Uploading to Google Drive: {target_remote_path}...", "INFO")
    cmd = [
        "rclone", "copy", str(upload_dir), target_remote_path,
        "--transfers", "8",
        "--checkers", "16",
        "--drive-chunk-size", "128M",
        "--fast-list",
        "--progress", "--stats-one-line",
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
            log(f"✔ Upload thành công: {sanitized_folder}", "SUCCESS")
            return True
        else:
            log(f"✘ Lỗi Rclone upload: {process.returncode}", "ERROR")
            return False
    except Exception as e:
        log(f"Lỗi Rclone: {e}", "ERROR")
        return False



# ==========================================
# MAIN RELAY PIPELINE
# ==========================================
CSV_PATH = BASE_DIR / "full_hoahoc.csv"

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


async def process_course_batch(client: Any, course_title: str, msgs: List[Any],
                                rclone_parent: str, log_path: Path):
    """Tải & upload toàn bộ file của 1 khóa học được forward vào relay group."""
    log(f"\n▶ [RELAY] Bắt đầu xử lý khóa: {course_title}", "SUCCESS", log_path)

    allowed_exts = (".rar", ".zip", ".7z", ".mp4", ".mkv", ".pdf", ".001", ".002", ".z01", ".z02")
    course_dir = TEMP_DIR / sanitize_name(course_title)
    archives_dir = course_dir / "archives"
    upload_dir   = course_dir / "upload"
    extracted_dir = course_dir / "extracted"
    for d in [archives_dir, upload_dir, extracted_dir]:
        d.mkdir(parents=True, exist_ok=True)

    download_success = True
    sem = asyncio.Semaphore(3)

    async def dl_file(msg: Any):
        nonlocal download_success
        fname = get_file_name(msg)
        if not fname:
            return
        if not fname.lower().endswith(allowed_exts):
            return
        save_path = archives_dir / fname
        file_size = getattr(msg.file, "size", 0) if getattr(msg, "file", None) else 0
        size_mb = file_size / 1024 / 1024 if file_size else 0.0
        async with sem:
            log(f"  - 🚀 [RELAY] Tải: {fname} ({size_mb:.1f} MB)...", "INFO", log_path)
            try:
                await client.download_media(msg, file=str(save_path))
                log(f"  - ✔ [RELAY] Tải xong {fname}, ⚡ Giải nén...", "SUCCESS", log_path)
                if not re.search(r'\.part(0[2-9]|[1-9]\d+)\.rar$', fname, re.I):
                    extract_single_archive(save_path, extracted_dir)
            except Exception as e:
                log(f"  - ✘ [RELAY] Lỗi khi tải {fname}: {e}", "ERROR", log_path)
                download_success = False

    tasks = [dl_file(m) for m in msgs]
    await asyncio.gather(*tasks)

    if not download_success:
        log(f"[RELAY] ✘ Lỗi tải file cho khóa {course_title}. Bỏ qua.", "ERROR", log_path)
        shutil.rmtree(str(course_dir), ignore_errors=True)
        update_csv_status(course_title, "FAILED_DOWNLOAD")
        return

    ok = repackage_and_upload(course_dir, upload_dir, rclone_parent, course_title)
    shutil.rmtree(str(course_dir), ignore_errors=True)
    if ok:
        update_csv_status(course_title, "COMPLETED")
        log(f"🎉 [RELAY] HOÀN THÀNH: {course_title}\n", "SUCCESS", log_path)
    else:
        update_csv_status(course_title, "FAILED_RCLONE")
        log(f"[RELAY] ✘ Upload thất bại cho khóa {course_title}.", "ERROR", log_path)


async def main():
    parser = argparse.ArgumentParser(description="Relay Pipeline (Acc 2 / Acc 3)")
    parser.add_argument("--session",  required=True, help="Tên session file (VD: pyrogram_acc2)")
    parser.add_argument("--group",    required=True, help="Relay Group ID (VD: -5040203514)", type=int)
    parser.add_argument("--rclone-dest", default=None, help="Rclone Google Drive path")
    parser.add_argument("--port",     type=int, default=5001, help="Cổng Web Log Monitor")
    args = parser.parse_args()

    log_path = BASE_DIR / f"relay_{args.session}.log"
    rclone_parent = args.rclone_dest or os.environ.get("RCLONE_PARENT_FOLDER") or "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"

    start_web_log_server(args.port)
    log(f"🚀 Relay Pipeline khởi động | Session: {args.session} | Group: {args.group}", "SUCCESS", log_path)

    # Telegram credentials
    api_id_val   = os.environ.get("TELERECON_API_ID", "2040")
    api_hash_val = os.environ.get("TELERECON_API_HASH", "b18441a12607e109d9496d9a244ead1c")
    session_path = str(BASE_DIR / args.session)

    client = TelegramClient(session_path, int(api_id_val), str(api_hash_val))
    await client.start()
    me = await client.get_me()
    log(f"✔ Đã kết nối: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', getattr(me, 'id', ''))})", "SUCCESS", log_path)

    # Lấy relay group entity
    relay_group = await client.get_entity(args.group)

    # Buffer để gom tin nhắn theo từng khóa
    # Acc 1 sẽ gửi:  "##COURSE_START## <tên khóa>" → các file → "##COURSE_END##"
    pending_batch: dict = {}  # group_id -> {title, msgs}
    processing_queue: asyncio.Queue = asyncio.Queue()

    @client.on(events.NewMessage(chats=relay_group))
    async def handler(event):
        msg = event.message
        text = getattr(msg, "text", "") or ""

        if text.startswith(SENTINEL_PREFIX):
            course_title = text[len(SENTINEL_PREFIX):].strip()
            pending_batch["current"] = {"title": course_title, "msgs": []}
            log(f"[RELAY] 📥 Nhận khóa mới: {course_title}", "INFO", log_path)
            return

        if text.strip() == SENTINEL_END:
            batch = pending_batch.pop("current", None)
            if batch and batch["msgs"]:
                await processing_queue.put((batch["title"], batch["msgs"]))
            return

        # Tin nhắn media - thêm vào batch hiện tại
        if "current" in pending_batch and msg.media:
            pending_batch["current"]["msgs"].append(msg)

    log(f"[RELAY] ⏳ Đang lắng nghe relay group {args.group}...", "INFO", log_path)

    # Chạy song song: lắng nghe event + xử lý queue download
    async def queue_processor():
        while True:
            try:
                course_title, msgs = await asyncio.wait_for(processing_queue.get(), timeout=30)
                await process_course_batch(client, course_title, msgs, rclone_parent, log_path)
            except asyncio.TimeoutError:
                pass  # Tiếp tục chờ tin nhắn mới

    await asyncio.gather(
        client.run_until_disconnected(),
        queue_processor()
    )


if __name__ == "__main__":
    asyncio.run(main())
