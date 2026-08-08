import os
import json
import csv
import subprocess
import threading
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_JSON_PATH = BASE_DIR / "upload_pack_tracker.json"
LOCAL_CSV_PATH = BASE_DIR / "upload_pack_tracker.csv"
_FILE_LOCK = threading.Lock()

def log_pack_upload(course_title: str, pack_name: str, batch_num: int, total_packs: int, size_mb: float, status: str = "UPLOADED_TO_DRIVE"):
    """Ghi lại lịch sử đợt Upload từng Pack/Section vào file bền vững không reset tại máy local."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "course_title": course_title,
        "pack_name": pack_name,
        "batch_info": f"Đợt {batch_num}/{total_packs}",
        "batch_num": batch_num,
        "total_packs": total_packs,
        "size_mb": round(size_mb, 1),
        "status": status
    }

    with _FILE_LOCK:
        # 1. Ghi JSON
        records = []
        if LOCAL_JSON_PATH.exists():
            try:
                with open(LOCAL_JSON_PATH, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except Exception:
                records = []
        
        records.append(entry)
        try:
            with open(LOCAL_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[PACK_TRACKER ERR] Ghi JSON thất bại: {e}")

        # 2. Ghi CSV
        file_exists = LOCAL_CSV_PATH.exists()
        try:
            with open(LOCAL_CSV_PATH, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "Course Title", "Pack Name", "Batch Info", "Size MB", "Status"])
                writer.writerow([timestamp, course_title, pack_name, f"Đợt {batch_num}/{total_packs}", round(size_mb, 1), status])
        except Exception as e:
            print(f"[PACK_TRACKER ERR] Ghi CSV thất bại: {e}")

    # 3. Đồng bộ nhật ký lên Cloud Google Drive (_SYSTEM_METADATA/)
    def sync_to_cloud():
        rclone_dest = os.environ.get("RCLONE_PARENT_FOLDER", "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:")
        remote_root = rclone_dest.rstrip('/')
        try:
            subprocess.run([
                "rclone", "copyto", str(LOCAL_JSON_PATH), f"{remote_root}/_SYSTEM_METADATA/upload_pack_tracker.json"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            subprocess.run([
                "rclone", "copyto", str(LOCAL_CSV_PATH), f"{remote_root}/_SYSTEM_METADATA/upload_pack_tracker.csv"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        except Exception as e:
            pass

    threading.Thread(target=sync_to_cloud, daemon=True).start()

    print(f"[📦 PACK TRACKER] {timestamp} | {course_title} | {pack_name} (Đợt {batch_num}/{total_packs}) -> {status} ({size_mb:.1f} MB)")

def ensure_local_tracker_restored():
    """Nếu chưa có file upload_pack_tracker.json cục bộ, tự động kéo bản mới nhất từ Cloud Google Drive về."""
    if LOCAL_JSON_PATH.exists() and LOCAL_JSON_PATH.stat().st_size > 10:
        return
    rclone_dest = os.environ.get("RCLONE_PARENT_FOLDER", "gdrive,root_folder_id=1-kq-gQkiCMcaTNmkFU5NBS3X0uiq5KX-:")
    remote_root = rclone_dest.rstrip('/')
    try:
        res = subprocess.run([
            "rclone", "copyto", f"{remote_root}/_SYSTEM_METADATA/upload_pack_tracker.json", str(LOCAL_JSON_PATH)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode == 0 and LOCAL_JSON_PATH.exists():
            pass
        subprocess.run([
            "rclone", "copyto", f"{remote_root}/_SYSTEM_METADATA/upload_pack_tracker.csv", str(LOCAL_CSV_PATH)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except Exception as e:
        print(f"[PACK_TRACKER RESTORE ERR] {e}")

def get_pack_tracker_summary():
    """Trả về dữ liệu tổng hợp đợt upload."""
    ensure_local_tracker_restored()
    if not LOCAL_JSON_PATH.exists():
        return []
    try:
        with open(LOCAL_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def is_pack_already_uploaded(course_title: str, pack_name: str) -> bool:
    """Kiểm tra xem Pack này đã được Upload thành công lên Drive ở đợt trước chưa."""
    ensure_local_tracker_restored()
    if not LOCAL_JSON_PATH.exists():
        return False
    try:
        with open(LOCAL_JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
            c_lower = course_title.strip().lower()
            p_lower = pack_name.strip().lower()
            for r in records:
                if r.get("course_title", "").strip().lower() == c_lower:
                    if r.get("pack_name", "").strip().lower() == p_lower and r.get("status") == "UPLOADED_TO_DRIVE":
                        return True
                    if r.get("pack_name") == "Full Course Pack / All Sections" and r.get("status") == "UPLOADED_TO_DRIVE":
                        return True
    except Exception:
        pass
    return False

def is_course_fully_completed(course_title: str) -> bool:
    """Kiểm tra xem khóa học đã TẢI HOÀN TẤT ALL PACKS trên Google Drive chưa."""
    ensure_local_tracker_restored()
    if not LOCAL_JSON_PATH.exists():
        return False
    try:
        with open(LOCAL_JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
            c_lower = course_title.strip().lower()
            course_records = [r for r in records if r.get("course_title", "").strip().lower() == c_lower]
            streaming_records = [r for r in course_records if r.get("pack_name") != "Full Course Pack / All Sections"]
            if streaming_records:
                max_batch = max(r.get("batch_num", 0) for r in streaming_records)
                total_p = max(r.get("total_packs", 0) for r in streaming_records)
                if total_p > 0 and max_batch >= total_p and any(r.get("status") == "UPLOADED_TO_DRIVE" for r in streaming_records):
                    return True
    except Exception:
        pass
    return False

def is_course_partially_in_progress(course_title: str) -> bool:
    """Trả về True nếu khóa học này ĐANG TẢI DỞ DANG (đã upload một số pack nhưng chưa đủ all packs)."""
    ensure_local_tracker_restored()
    if not LOCAL_JSON_PATH.exists():
        return False
    try:
        with open(LOCAL_JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
            c_lower = course_title.strip().lower()
            course_records = [r for r in records if r.get("course_title", "").strip().lower() == c_lower]
            if not course_records:
                return False  # Không có trong log -> Nếu có trên Drive thì là khóa cũ đã xong!
            streaming_records = [r for r in course_records if r.get("pack_name") != "Full Course Pack / All Sections"]
            if streaming_records:
                max_batch = max(r.get("batch_num", 0) for r in streaming_records)
                total_p = max(r.get("total_packs", 0) for r in streaming_records)
                if total_p > 0 and max_batch < total_p:
                    return True   # Đang tải dở dang (ví dụ 1/8 Pack)!
                if total_p > 0 and max_batch >= total_p:
                    return False  # Đã xong đủ All Packs 100%!
            has_full = any(r.get("pack_name") == "Full Course Pack / All Sections" for r in course_records)
            if has_full:
                return False
    except Exception:
        pass
    return False

if __name__ == "__main__":
    log_pack_upload("Test Course", "SECTION 01.zip", 1, 3, 450.5)
