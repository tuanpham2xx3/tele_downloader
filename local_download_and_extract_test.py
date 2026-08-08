import os
import sys
import math
import time
import shutil
import asyncio
import subprocess
from pathlib import Path

# Cấu hình UTF-8 cho Console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    from telethon import TelegramClient
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename, InputDocumentFileLocation
except ImportError:
    print("[ERROR] Thiếu thư viện telethon. Vui lòng chạy: pip install telethon rich")
    sys.exit(1)

# Thư mục làm việc
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "local_test_download"
EXTRACT_DIR = BASE_DIR / "local_test_extracted"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

# Thông tin API Telegram mặc định từ dự án
API_ID = 21503923
API_HASH = "5f891b689bf15eb2be4938d2f5a6538b"

def find_session_file() -> Path:
    candidates = [
        Path.home() / ".telegram_sessions" / "pyrogram.session",
        BASE_DIR / "telegram_media_downloader" / "pyrogram.session",
        BASE_DIR / "pyrogram.session"
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]

def get_file_name(msg) -> str:
    if not getattr(msg, "media", None) or not isinstance(msg.media, MessageMediaDocument):
        return ""
    if getattr(msg, "file", None) and getattr(msg.file, "name", None):
        return str(msg.file.name)
    doc = getattr(msg.media, "document", None)
    if doc:
        for attr in getattr(doc, "attributes", []):
            if isinstance(attr, DocumentAttributeFilename):
                return str(attr.file_name)
    return f"media_file_{msg.id}"

async def fast_parallel_download(client: TelegramClient, msg, dest_path: Path):
    """
    Thuật toán Fast Parallel Streamer (512KB Aligned Block Queue - 8 Parallel Connections):
    - Chia 1 file thành các block 512KB (đảm bảo bội số 4096 bytes).
    - Mở 8 connection kéo song song các block.
    - Lưu vào mảng chunks[idx] đảm bảo thứ tự byte tuyệt đối, 100% không bị lỗi CRC!
    """
    doc = msg.media.document
    file_size = doc.size
    location = InputDocumentFileLocation(
        id=doc.id,
        access_hash=doc.access_hash,
        file_reference=doc.file_reference,
        thumb_size=""
    )

    CHUNK_SIZE = 512 * 1024  # 512 KB (chuẩn alignment Telegram)
    total_chunks = math.ceil(file_size / CHUNK_SIZE)
    chunks = [None] * total_chunks

    # Kết nối trực tiếp tới đúng Datacenter chứa file (DC 1..5)
    print(f"[INFO] Kết nối tới Telegram Datacenter {doc.dc_id}...")
    sender = await client._borrow_exported_sender(doc.dc_id)

    sem = asyncio.Semaphore(8)  # 8 luồng song song per file
    downloaded_bytes = 0
    start_time = time.time()
    last_print = time.time()

    async def download_chunk(idx: int):
        nonlocal downloaded_bytes, last_print
        offset = idx * CHUNK_SIZE
        limit = min(CHUNK_SIZE, file_size - offset)

        async with sem:
            res = await client._call(sender, GetFileRequest(
                location=location,
                offset=offset,
                limit=limit
            ))
            chunks[idx] = res.bytes
            downloaded_bytes += len(res.bytes)

            now = time.time()
            if now - last_print >= 0.5 or downloaded_bytes == file_size:
                last_print = now
                mb_done = downloaded_bytes / (1024 * 1024)
                mb_total = file_size / (1024 * 1024)
                elapsed = now - start_time
                speed = mb_done / elapsed if elapsed > 0 else 0
                pct = (downloaded_bytes / file_size) * 100 if file_size > 0 else 0
                print(f"  - ⚡ FAST STREAMER: {mb_done:.1f} MB / {mb_total:.1f} MB ({pct:.1f}%) | Tốc độ: {speed:.2f} MB/s", end="\r")

    print(f"[INFO] Khởi chạy Fast Parallel Streamer (8 connections, 512KB blocks)...")
    tasks = [download_chunk(i) for i in range(total_chunks)]
    await asyncio.gather(*tasks)
    print("")

    # Giải phóng DC sender
    try:
        await client._return_exported_sender(sender)
    except Exception:
        pass

    # Ghi toàn bộ chunks theo đúng thứ tự mốc chỉ mục vào file
    print("[INFO] Đang ghi file nhị phân nguyên vẹn vào đĩa...")
    with open(dest_path, "wb") as f:
        for chunk in chunks:
            f.write(chunk)

    return time.time() - start_time

async def run_download_extract_test():
    print("==========================================")
    print("🚀 BẮT ĐẦU THỬ NGHIỆM FAST PARALLEL STREAMER (8 CONNECTIONS)")
    print("==========================================")

    session_path = find_session_file()
    print(f"[INFO] File Session: {session_path}")
    if not session_path.exists():
        print(f"[ERROR] Không tìm thấy file session Telegram tại: {session_path}")
        return

    session_str = str(session_path).replace(".session", "")
    client = TelegramClient(session_str, API_ID, API_HASH)

    print("[INFO] Đang kết nối tới Telegram API...")
    await client.start()

    me = await client.get_me()
    name = getattr(me, "first_name", "User") or "User"
    print(f"✔ Đã kết nối Telegram Account: {name}")

    bot_username = "coursebusters_bot"
    print(f"[INFO] Đang tìm kiếm tin nhắn từ Bot @{bot_username}...")

    target_msg = None
    target_filename = ""

    async for msg in client.iter_messages(bot_username, limit=30):
        fname = get_file_name(msg)
        if fname and fname.lower().endswith((".zip", ".rar", ".7z", ".mp4", ".001", ".z01")):
            target_msg = msg
            target_filename = fname
            break

    if not target_msg:
        print("[WARN] Không tìm thấy file nén đính kèm nào trong 30 tin nhắn gần nhất của Bot.")
        return

    dest_file = DOWNLOAD_DIR / target_filename
    print(f"\n📦 Tìm thấy File nén bài học: [{target_filename}]")
    print(f"💾 Lưu tạm tại: {dest_file}")

    # Tải file bằng thuật toán Fast Parallel Streamer
    elapsed_time = await fast_parallel_download(client, target_msg, dest_file)

    file_size_bytes = dest_file.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    avg_speed = file_size_mb / elapsed_time if elapsed_time > 0 else 0

    print("\n==========================================")
    print("🎉 TẢI THÀNH CÔNG BẰNG FAST PARALLEL STREAMER!")
    print(f"📦 Tên File: {target_filename}")
    print(f"💾 Dung lượng: {file_size_mb:.2f} MB ({file_size_bytes:,} bytes)")
    print(f"⏱️ Thời gian tải: {elapsed_time:.2f} giây")
    print(f"⚡ TỐC ĐỘ TẢI THỰC TẾ: {avg_speed:.2f} MB/s")
    print("==========================================")

    # ------------------------------------------
    # BƯỚC GIẢI NÉN & KIỂM TRA CHECKSUM
    # ------------------------------------------
    print("\n[INFO] Bắt đầu giải nén file để kiểm tra độ nguyên vẹn dữ liệu (CRC Check)...")
    cmd_7z = shutil.which("7z") or shutil.which("7za") or r"C:\Program Files\7-Zip\7z.exe"

    success = False
    if os.path.exists(cmd_7z):
        print(f"[INFO] Sử dụng 7-Zip: {cmd_7z}")
        cmd = [cmd_7z, "x", "-y", "-aoa", f"-o{EXTRACT_DIR}", str(dest_file)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            success = True
            print("✔ 7-Zip đã giải nén THÀNH CÔNG 100% (Exit Code = 0)!")
        else:
            print(f"⚠️ Cảnh báo 7-Zip: {res.stderr.strip() or res.stdout.strip()}")
    else:
        if dest_file.suffix.lower() == ".zip":
            import zipfile
            try:
                with zipfile.ZipFile(dest_file, 'r') as zip_ref:
                    zip_ref.extractall(EXTRACT_DIR)
                success = True
                print("✔ Python zipfile đã giải nén THÀNH CÔNG 100%!")
            except Exception as e:
                print(f"⚠️ Lỗi giải nén zipfile: {e}")

    if success:
        print("\n==========================================")
        print("🏆 KẾT QUẢ XÁC MINH NGUYÊN VẸN DỮ LIỆU:")
        print("✔ KHÔNG CÓ LỖI CRC! FILE DỮ LIỆU HOÀN TOÀN NGUYÊN VẸN 100%!")
        print("📁 Danh sách file/thư mục vừa giải nén ra:")
        extracted_files = list(EXTRACT_DIR.rglob("*"))
        for item in extracted_files[:10]:
            if item.is_file():
                sz_mb = item.stat().st_size / (1024 * 1024)
                print(f"   - 📄 {item.relative_to(EXTRACT_DIR)} ({sz_mb:.2f} MB)")
        if len(extracted_files) > 10:
            print(f"   ... và {len(extracted_files) - 10} file/thư mục khác.")
        print("==========================================")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_download_extract_test())
