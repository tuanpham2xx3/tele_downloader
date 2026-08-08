import os
import shutil
import time
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_PROCESSING = BASE_DIR / "temp_processing"
TEMP_RELAY = BASE_DIR / "temp_relay_disk"
TEMP_SSD = BASE_DIR / "temp_extract_ssd" / "extracted"
RAM_DISK_SHM = Path("/dev/shm")

def get_active_course_names() -> set:
    """Đọc log thực tế để lấy danh sách tên các khóa học đang tải hoạt động."""
    active_titles = set()
    log_files = [
        BASE_DIR.parent / "pipeline_acc1.log",
        BASE_DIR.parent / "pipeline_acc2.log",
        BASE_DIR.parent / "pipeline_acc3.log",
        BASE_DIR / "pipeline_dispatcher.log"
    ]
    for lf in log_files:
        if not lf.exists():
            continue
        try:
            with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-300:]  # 300 dòng mới nhất
                for line in lines:
                    # Pattern nhận diện khóa đang tải
                    m = re.search(r'(?:Bắt đầu tải|Bắt đầu xử lý khóa:|Nhận khóa mới:|RELAY\] Tải:|Khóa học:|Processing:)\s*\*?\*?([^\n\(\[\|]+)', line)
                    if m:
                        clean_name = m.group(1).strip().strip('*').strip()
                        if len(clean_name) > 3:
                            active_titles.add(clean_name.lower())
                    # Pattern nhận diện từ tên file tải
                    m_fn = re.search(r'\[(?:RELAY STREAMING|RELAY|STREAMING)\]\s*(?:Uploading Pack|Tải:)?\s*([^\n\(\[\|]+)', line)
                    if m_fn:
                        fn_name = m_fn.group(1).strip()
                        if len(fn_name) > 3:
                            active_titles.add(fn_name.lower())
        except Exception:
            pass
    return active_titles

def is_folder_stale(folder_path: Path, max_idle_seconds: int = 600) -> bool:
    """Kiểm tra xem thư mục có bị bỏ hắt (không có file nào mtime trong X giây) không."""
    now = time.time()
    newest_mtime = 0
    try:
        for root, _, files in os.walk(folder_path):
            for file in files:
                fp = os.path.join(root, file)
                try:
                    mt = os.path.getmtime(fp)
                    if mt > newest_mtime:
                        newest_mtime = mt
                except OSError:
                    pass
    except Exception:
        return False

    if newest_mtime == 0:
        # Thư mục rỗng hoặc tạo lâu mà không có file
        try:
            newest_mtime = folder_path.stat().st_mtime
        except Exception:
            return False

    return (now - newest_mtime) > max_idle_seconds

def clean_garbage(max_idle_minutes: int = 10):
    """Quét và xóa triệt để toàn bộ thư mục tạm rác đọng lại."""
    active_courses = get_active_course_names()
    target_dirs = [TEMP_PROCESSING, TEMP_RELAY, TEMP_SSD]
    
    # Kiểm tra thêm RAM disk /dev/shm
    if RAM_DISK_SHM.exists():
        for p in RAM_DISK_SHM.glob("pipeline_*"):
            if p.is_dir():
                target_dirs.append(p)

    freed_bytes = 0
    deleted_count = 0

    for target in target_dirs:
        if not target.exists():
            continue
        
        for item in target.iterdir():
            if not item.is_dir():
                continue
            
            folder_name_lower = item.name.lower()
            
            # Kiểm tra xem thư mục có bị bỏ tĩnh > max_idle_minutes không
            stale = is_folder_stale(item, max_idle_seconds=max_idle_minutes * 60)
            
            if stale:
                try:
                    # Tính dung lượng trước khi xóa
                    size = sum(f.stat().st_size for f in item.glob('**/*') if f.is_file())
                    shutil.rmtree(item, ignore_errors=True)
                    freed_bytes += size
                    deleted_count += 1
                    print(f"[AUTO-CLEANER] 🗑️ Đã dọn dẹp thư mục rác (tĩnh >{max_idle_minutes}phút): {item.name} ({size/1024/1024:.1f} MB)")
                except Exception as e:
                    print(f"[AUTO-CLEANER] ⚠️ Lỗi khi xóa {item.name}: {e}")

    if deleted_count > 0:
        print(f"[AUTO-CLEANER] ✔ Tổng cộng đã dọn dẹp {deleted_count} thư mục rác, giải phóng {freed_bytes/1024/1024/1024:.2f} GB!")
    else:
        print("[AUTO-CLEANER] ✨ Đĩa hoàn toàn sạch sẽ, không có rác dư thừa.")

if __name__ == "__main__":
    clean_garbage(max_idle_minutes=10)
