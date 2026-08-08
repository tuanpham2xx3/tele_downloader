import os
import json
import csv
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_JSON_PATH = BASE_DIR / "upload_pack_tracker.json"
LOCAL_CSV_PATH = BASE_DIR / "upload_pack_tracker.csv"

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

    print(f"[📦 PACK TRACKER] {timestamp} | {course_title} | {pack_name} (Đợt {batch_num}/{total_packs}) -> {status} ({size_mb:.1f} MB)")

def get_pack_tracker_summary():
    """Trả về dữ liệu tổng hợp đợt upload."""
    if not LOCAL_JSON_PATH.exists():
        return []
    try:
        with open(LOCAL_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

if __name__ == "__main__":
    log_pack_upload("Test Course", "SECTION 01.zip", 1, 3, 450.5)
