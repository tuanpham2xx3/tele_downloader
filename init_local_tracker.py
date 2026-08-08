import json
import csv
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(r"c:\PROJECT\_EXTENTSION\_GETURL")
JSON_PATH = BASE_DIR / "upload_pack_tracker.json"
CSV_PATH = BASE_DIR / "upload_pack_tracker.csv"

scanned_courses = [
    ("A dark cyberpunk world drawn with Blender", "2026-08-08 03:00:54"),
    ("All About Japanese Key Animation Genga", "2026-08-07 13:55:27"),
    ("Creating Characters in a Fictional Universe through Lighting", "2026-08-07 16:04:38"),
    ("Creating Complete Dynamic and Stylish Characters", "2026-08-07 08:12:49"),
    ("Drawing & Coloring Anime-Style Characters", "2026-08-07 07:18:28"),
    ("Drawing Dynamic Action Scenes", "2026-08-07 13:28:48"),
    ("Drawing Monochromatic Characters Using Lineart", "2026-08-07 11:21:31"),
    ("From Sketch to 3D Anime Avatar Exploring Applications", "2026-08-07 20:41:33"),
    ("Illustrating & Animating Character Splash Art", "2026-08-07 12:45:28"),
    ("Impactful character illustrations incorporating fetishism", "2026-08-07 14:06:25"),
    ("Intro to Inbetweening Animations & Practical Skills", "2026-08-07 12:14:47"),
    ("Introduction to Chrometype Artwork with Blender", "2026-08-07 19:31:49"),
    ("Making Real-Time Cinematic Videos With Unreal Engine 5", "2026-08-07 21:35:54"),
    ("Making Stylized 3D Animation from Scratch", "2026-08-08 01:23:57"),
    ("Master Class Cinematic Illustrations", "2026-08-07 12:57:27"),
    ("Mastering VTuber Creation from Scratch in Live2D", "2026-08-08 00:50:37"),
    ("Modeling & Toon Shading Cartoon-Style Girl Characters", "2026-08-07 22:06:41"),
    ("Realistic Texturing with Cinema4D & Octane", "2026-08-07 20:54:36"),
    ("Step-by-Step Guide to Creature Design", "2026-08-07 12:16:53"),
    ("Stylish and immersive animations created with C4D", "2026-08-07 22:52:32"),
    ("Techniques to Create Unique Storytelling Illustrations", "2026-08-07 11:21:27"),
    ("The Ultimate Webtoon Illustration Tool Kit", "2026-08-07 23:03:35"),
    ("실전부터 시작하는 Houdini FX 트레이닝", "2026-08-07 13:18:57")
]

records = []
for title, ts in scanned_courses:
    records.append({
        "timestamp": ts,
        "course_title": title,
        "pack_name": "Full Course Pack / All Sections",
        "batch_info": "Khóa học hoàn chỉnh trên Drive",
        "batch_num": 1,
        "total_packs": 1,
        "size_mb": 0.0,
        "status": "UPLOADED_TO_DRIVE"
    })

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Timestamp", "Course Title", "Pack Name", "Batch Info", "Size MB", "Status"])
    for title, ts in scanned_courses:
        writer.writerow([ts, title, "Full Course Pack / All Sections", "Khóa học hoàn chỉnh trên Drive", 0.0, "UPLOADED_TO_DRIVE"])

print(f"[OK] Da khoi tao {len(records)} khoa hoc tu Google Drive vao local tracker.")
