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

# ─── RAM Disk tự động: ưu tiên /dev/shm (Linux RAM disk), fallback về đĩa ───
_SHM_DIR = Path("/dev/shm")
_PREFER_RAM = _SHM_DIR.exists() and _SHM_DIR.is_dir()
# Mỗi Relay dùng thư mục riêng trong /dev/shm (acc2 hay acc3 sẽ set runtime)
_SHM_RELAY_NAME = "pipeline_relay_temp"
TEMP_DIR = (_SHM_DIR / _SHM_RELAY_NAME) if _PREFER_RAM else (BASE_DIR / "temp_processing_relay")

if _PREFER_RAM:
    _stat = shutil.disk_usage(str(_SHM_DIR))
    print(f"[✔] RAM disk /dev/shm khả dụng! Free: {_stat.free / 1024**3:.1f} GB | TEMP tại: {TEMP_DIR}")
else:
    print(f"[!] /dev/shm không khả dụng, dùng đĩa thường: {TEMP_DIR}")


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

class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def start_web_log_server(port: int):
    def _serve():
        try:
            server = ReusableHTTPServer(("0.0.0.0", port), WebLogHandler)
            server.serve_forever()
        except Exception as e:
            log(f"Lỗi khởi động Relay Web Log Server port {port}: {e}", "ERROR")
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    log(f"Đã khởi động Relay Web Log Server tại http://0.0.0.0:{port}", "INFO")


# ==========================================
# HELPERS
# ==========================================
SENTINEL_PREFIX = "##COURSE_START##"
SENTINEL_END    = "##COURSE_END##"

def sanitize_name(name: str) -> str:
    if not name:
        return "Unassigned_Course"
    clean = re.sub(r'[*`~_]', '', name)
    clean = re.sub(r'[\\/*?:"<>|]', '', clean)
    clean = clean.strip().strip('.').strip('_')
    return clean[:120] if clean else "Unassigned_Course"

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
        cmd = [cmd_7z, "x", "-y", "-aoa", "-p-", "-mmt=16", f"-o{extracted_dir}", str(file_path)]
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

    # 2. Nén tài liệu phụ thành Class_Materials.zip bằng 7z siêu tốc
    if other_files:
        log("Đóng gói tài liệu phụ thành Class_Materials.zip (Multi-threaded FAST)...", "INFO")
        zip_path = upload_dir / "Class_Materials.zip"
        cmd_7z = shutil.which("7z") or shutil.which("7za") or "7z"
        packed_ok = False
        try:
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
    log(f"Uploading to Google Drive (16GB RAM BEAST MODE: 256M CHUNK, 256M BUFFER, 6 TRANSFERS): {target_remote_path}...", "INFO")
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

def normalize_title(title: str) -> str:
    if not title:
        return ""
    return re.sub(r'[*`_]', '', title).strip()


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


async def process_course_batch(client: Any, course_title: str, msgs: List[Any],
                                rclone_parent: str, log_path: Path):
    """Tải & upload toàn bộ file của 1 khóa học được forward vào relay group."""
    clean_t = normalize_title(course_title)

    # 1. Kiểm tra trạng thái CSV
    if CSV_PATH.exists():
        try:
            with open(CSV_PATH, "r", encoding="utf-8") as cf:
                for row in csv.reader(cf):
                    if row and normalize_title(row[0]) == clean_t and row[1].strip() == "COMPLETED":
                        log(f"[RELAY] ⏭ Khóa [{course_title}] đã COMPLETED trong CSV. Bỏ qua không tải!", "SUCCESS", log_path)
                        return
        except Exception:
            pass

    # 2. Kiểm tra trực tiếp trên Google Drive qua Rclone
    sanitized = sanitize_name(course_title)
    target_remote_path = f"{rclone_parent.rstrip('/')}/{sanitized}"
    try:
        chk_cmd = ["rclone", "lsf", target_remote_path, "--max-depth", "1"]
        cres = subprocess.run(chk_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if cres.returncode == 0 and cres.stdout.strip():
            log(f"[RELAY] ⏭ Khóa [{course_title}] đã TỒN TẠI trên Google Drive. Ghi CSV = COMPLETED & Bỏ qua!", "SUCCESS", log_path)
            update_csv_status(course_title, "COMPLETED")
            return
    except Exception:
        pass

    log(f"\n▶ [RELAY] Bắt đầu xử lý khóa: {course_title}", "SUCCESS", log_path)

    allowed_exts = (".rar", ".zip", ".7z", ".mp4", ".mkv", ".pdf", ".001", ".002", ".z01", ".z02")

    # Ước lượng dung lượng để chọn RAM hay đĩa thường
    total_mb = sum(
        getattr(m.file, "size", 0) / 1024 / 1024
        for m in msgs if getattr(m, "file", None)
    )
    estimated_gb = max(total_mb / 1024 * 2.5, 2.0)

    if _PREFER_RAM:
        try:
            shm_stat = shutil.disk_usage(str(_SHM_DIR))
            shm_free_gb = shm_stat.free / 1024**3
        except Exception:
            shm_free_gb = 0
        if shm_free_gb >= estimated_gb + 1.0:
            course_dir = TEMP_DIR / sanitize_name(course_title)
            log(f"[RAM Disk] Dùng /dev/shm cho [{course_title}] (free={shm_free_gb:.1f}GB, cần≈{estimated_gb:.1f}GB)", "INFO", log_path)
        else:
            course_dir = BASE_DIR / "temp_relay_disk" / sanitize_name(course_title)
            log(f"[Disk] /dev/shm chỉ còn {shm_free_gb:.1f}GB, dùng đĩa cho [{course_title}]", "WARN", log_path)
    else:
        course_dir = TEMP_DIR / sanitize_name(course_title)

    archives_dir = course_dir / "archives"
    upload_dir   = course_dir / "upload"
    extracted_dir = course_dir / "extracted"
    for d in [archives_dir, upload_dir, extracted_dir]:
        d.mkdir(parents=True, exist_ok=True)

    download_success = True
    is_ram = _PREFER_RAM and str(course_dir).startswith("/dev/shm")
    max_dl = 4 if is_ram else 2  # đĩa: 2 concurrent để tránh I/O bão hòa
    sem = asyncio.Semaphore(max_dl)
    log(f"[RELAY] Tải {max_dl} file song song ({'RAM' if is_ram else 'Disk'})", "INFO", log_path)

    async def dl_file(msg: Any):
        nonlocal download_success
        fname = get_file_name(msg)
        if not fname or not fname.lower().endswith(allowed_exts):
            return
        save_path = archives_dir / fname
        file_size = getattr(msg.file, "size", 0) if getattr(msg, "file", None) else 0
        size_mb = file_size / 1024 / 1024 if file_size else 0.0
        dl_timeout = min(max(int(size_mb / 1.0), 300), 10800)  # 1MB/s min, max 3h

        async with sem:
            log(f"  - 🚀 [RELAY] Tải: {fname} ({size_mb:.1f} MB, timeout={dl_timeout//60}phút)...", "INFO", log_path)
            last_size = [0]
            last_progress_time = [asyncio.get_event_loop().time()]
            STALL_TIMEOUT = 300  # 5 phút không có bytes = treo

            async def watchdog():
                while True:
                    await asyncio.sleep(60)
                    cur = save_path.stat().st_size if save_path.exists() else 0
                    if cur > last_size[0]:
                        last_size[0] = cur
                        last_progress_time[0] = asyncio.get_event_loop().time()
                        log(f"  - 📊 [{fname}] {cur/1024/1024:.1f}MB/{size_mb:.1f}MB", "INFO", log_path)
                    elif asyncio.get_event_loop().time() - last_progress_time[0] > STALL_TIMEOUT:
                        raise asyncio.TimeoutError("Stalled 5min")

            wd_task = asyncio.ensure_future(watchdog())
            try:
                await asyncio.wait_for(
                    client.download_media(msg, file=str(save_path)),
                    timeout=dl_timeout
                )
                wd_task.cancel()
                log(f"  - ✔ [RELAY] Tải xong {fname}, ⚡ Giải nén...", "SUCCESS", log_path)
                if not re.search(r'\.part\d+\.rar$', fname, re.I):
                    extract_single_archive(save_path, extracted_dir)
            except asyncio.TimeoutError:
                wd_task.cancel()
                elapsed = int(asyncio.get_event_loop().time() - last_progress_time[0])
                log(f"  - ✘ [RELAY] STALL/TIMEOUT sau {elapsed}s khi tải {fname}, bỏ qua.", "ERROR", log_path)
                download_success = False
            except Exception as e:
                wd_task.cancel()
                log(f"  - ✘ [RELAY] Lỗi khi tải {fname}: {e}", "ERROR", log_path)
                download_success = False

    tasks = [dl_file(m) for m in msgs]
    # Timeout toàn bộ khóa: tối đa 6 giờ
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=21600)
    except asyncio.TimeoutError:
        log(f"[RELAY] ✘ TIMEOUT 6h toàn khóa {course_title}, dừng xử lý.", "ERROR", log_path)
        download_success = False

    if not download_success:
        log(f"[RELAY] ✘ Lỗi tải file cho khóa {course_title}. Bỏ qua.", "ERROR", log_path)
        shutil.rmtree(str(course_dir), ignore_errors=True)
        update_csv_status(course_title, "FAILED_DOWNLOAD")
        return

    # Thử giải nén cho các bộ file nén multi-part RAR sau khi đã tải đầy đủ tất cả các part
    for file_path in archives_dir.glob("*.rar"):
        if re.search(r'\.part0?1\.rar$', file_path.name, re.I):
            extract_single_archive(file_path, extracted_dir)

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
    rclone_parent = args.rclone_dest or os.environ.get("RCLONE_PARENT_FOLDER") or "getlink,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:"

    # Gán TEMP_DIR riêng theo session để tránh conflict giữa Acc 2 và Acc 3
    global TEMP_DIR
    if _PREFER_RAM:
        TEMP_DIR = _SHM_DIR / f"pipeline_{args.session}_temp"
        _stat = shutil.disk_usage(str(_SHM_DIR))
        log(f"[RAM Disk] Dùng /dev/shm cho {args.session} — Free: {_stat.free / 1024**3:.1f} GB → {TEMP_DIR}", "SUCCESS", log_path)
    else:
        TEMP_DIR = BASE_DIR / f"temp_processing_{args.session}"

    start_web_log_server(args.port)
    log(f"🚀 Relay Pipeline khởi động | Session: {args.session} | Group: {args.group}", "SUCCESS", log_path)

    # Telegram credentials
    api_id_val   = os.environ.get("TELERECON_API_ID", "21724")
    api_hash_val = os.environ.get("TELERECON_API_HASH", "3e0fe5dadb9b1612e3e5b6d912b72449")
    if api_id_val == "2040":
        api_id_val = "21724"
        api_hash_val = "3e0fe5dadb9b1612e3e5b6d912b72449"
    session_path = str(BASE_DIR / args.session)

    # Các lỗi MTProto nghiêm trọng cần reconnect hoàn toàn
    FATAL_MTPROTO_KEYWORDS = [
        "too many messages had to be ignored",
        "server closed the connection",
        "connection reset",
        "broken pipe",
        "bad message",
        "security error",
        "0 bytes read",
    ]

    def is_fatal_mtproto_error(e: Exception) -> bool:
        msg = str(e).lower()
        return any(kw in msg for kw in FATAL_MTPROTO_KEYWORDS)

    processing_queue: asyncio.Queue = asyncio.Queue()

    async def queue_processor():
        while True:
            try:
                course_title, msgs = await asyncio.wait_for(processing_queue.get(), timeout=60)
                log(f"[QUEUE] 🔄 Bắt đầu xử lý từ queue: {course_title}", "INFO", log_path)
                # client có thể bị thay thế, dùng biến nonlocal
                # Timeout toàn bộ quá trình xử lý 1 khóa: 8 giờ
                try:
                    await asyncio.wait_for(
                        process_course_batch(client_holder[0], course_title, msgs, rclone_parent, log_path),
                        timeout=28800
                    )
                except asyncio.TimeoutError:
                    log(f"[QUEUE] ✘ TIMEOUT 8h khi xử lý [{course_title}], chuyển sang khóa tiếp theo.", "ERROR", log_path)
            except asyncio.TimeoutError:
                pass  # queue rỗng, tiếp tục chờ
            except Exception as e:
                log(f"⚠️ Lỗi trong queue processor: {e}", "WARN", log_path)

    client_holder = [None]
    retry_delay = 5
    MAX_DELAY = 120

    asyncio.ensure_future(queue_processor())

    while True:
        try:
            client = TelegramClient(session_path, int(api_id_val), str(api_hash_val))
            client_holder[0] = client
            await client.connect()
            if not await client.is_user_authorized():
                log(f"🔴 [ERROR] Session [{args.session}] chưa đăng nhập hoặc hết hạn!", "ERROR", log_path)
                log(f"👉 Vui lòng chạy lệnh sau trên terminal để đăng nhập: python3 login.py {args.session}", "WARN", log_path)
                await client.disconnect()
                break

            await client.start()
            me = await client.get_me()
            log(f"✔ Đã kết nối: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', getattr(me, 'id', ''))})", "SUCCESS", log_path)
            retry_delay = 5

            relay_group = await client.get_entity(args.group)

            # -------------------------------------------------------------
            # BƯỚC 1: QUÉT LỊCH SỬ NHÓM ĐỂ LẤY TOÀN BỘ KHÓA ĐÃ FORWARD TỪ TRƯỚC
            # -------------------------------------------------------------
            log(f"[RELAY] 🔍 Quét lịch sử relay group {args.group} để tìm khóa học chưa hoàn thành...", "INFO", log_path)
            history_msgs = []
            async for hmsg in client.iter_messages(relay_group, limit=4000, reverse=True):
                history_msgs.append(hmsg)

            # Phân cụm các khóa học từ lịch sử
            history_courses: List[Tuple[str, List[Any]]] = []
            cur_hist_title = None
            cur_hist_files = []

            for hmsg in history_msgs:
                htext = (getattr(hmsg, "text", "") or "").strip()
                if htext.startswith(SENTINEL_PREFIX):
                    if cur_hist_title and cur_hist_files:
                        history_courses.append((cur_hist_title, cur_hist_files))
                    cur_hist_title = htext[len(SENTINEL_PREFIX):].strip()
                    cur_hist_files = []
                    continue

                if htext == SENTINEL_END:
                    if cur_hist_title and cur_hist_files:
                        history_courses.append((cur_hist_title, cur_hist_files))
                    cur_hist_title = None
                    cur_hist_files = []
                    continue

                if cur_hist_title and hmsg.media:
                    cur_hist_files.append(hmsg)

            if cur_hist_title and cur_hist_files:
                history_courses.append((cur_hist_title, cur_hist_files))

            log(f"[RELAY] ✔ Tìm thấy {len(history_courses)} khóa trong lịch sử nhóm!", "SUCCESS", log_path)

            # Đẩy các khóa chưa làm vào queue
            queued_count = 0
            for h_title, h_files in history_courses:
                clean_ht = normalize_title(h_title)
                # Kiểm tra trạng thái trong CSV
                csv_st = "PENDING"
                if CSV_PATH.exists():
                    try:
                        with open(CSV_PATH, "r", encoding="utf-8") as cf:
                            for row in csv.reader(cf):
                                if row and normalize_title(row[0]) == clean_ht:
                                    csv_st = row[1].strip() if len(row) > 1 else "PENDING"
                    except Exception:
                        pass

                if csv_st == "COMPLETED":
                    continue

                await processing_queue.put((h_title, h_files))
                queued_count += 1

            log(f"[RELAY] 📋 Đã đưa {queued_count} khóa chưa hoàn thành vào hàng đợi xử lý!", "SUCCESS", log_path)

            # -------------------------------------------------------------
            # BƯỚC 2: LẮNG NGHE TIN NHẮN MỚI REALTIME
            # -------------------------------------------------------------
            pending_batch: dict = {}

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
                        log(f"[RELAY] ➕ Đã thêm [{batch['title']}] ({len(batch['msgs'])} file) vào hàng đợi!", "SUCCESS", log_path)
                    return

                if "current" in pending_batch and msg.media:
                    pending_batch["current"]["msgs"].append(msg)

            log(f"[RELAY] ⏳ Đang lắng nghe relay group {args.group} liên tục...", "INFO", log_path)
            await client.run_until_disconnected()

        except KeyboardInterrupt:
            log("🛑 Dừng theo yêu cầu người dùng.", "INFO", log_path)
            break
        except Exception as e:
            if is_fatal_mtproto_error(e):
                log(f"🔴 Lỗi MTProto nghiêm trọng: {e}", "ERROR", log_path)
                log(f"♻️ Tạo lại TelegramClient hoàn toàn sau {retry_delay}s...", "WARN", log_path)
            else:
                log(f"⚠️ Gián đoạn kết nối ({e}), kết nối lại sau {retry_delay}s...", "WARN", log_path)

            # Đóng client cũ hoàn toàn
            try:
                if client_holder[0] and client_holder[0].is_connected():
                    await client_holder[0].disconnect()
            except Exception:
                pass

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_DELAY)  # exponential backoff, tối đa 120s


if __name__ == "__main__":
    asyncio.run(main())

