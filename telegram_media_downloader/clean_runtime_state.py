#!/usr/bin/env python3
"""Discard interrupted local work before every non-resuming pipeline start."""

from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import time
from pathlib import Path

from csv_status_store import reset_transient_statuses


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TEMP_DIRS = (
    BASE_DIR / "temp_processing",
    BASE_DIR / "temp_processing_pyrogram_acc2",
    BASE_DIR / "temp_processing_pyrogram_acc3",
    BASE_DIR / "temp_extract_ssd",
)
SHM_DIRS = (
    Path("/dev/shm/pipeline_acc1_temp"),
    Path("/dev/shm/pipeline_pyrogram_acc2_temp"),
    Path("/dev/shm/pipeline_pyrogram_acc3_temp"),
    Path("/dev/shm/pipeline_relay_temp"),
)
TDLIB_DATA = PROJECT_ROOT / ".runtime" / "tdlib" / "data"
TDLIB_CACHE_NAMES = {
    "animations", "audios", "documents", "photos", "temp",
    "thumbnails", "video", "videos", "voice",
}


def _stop_stale_extractors() -> int:
    proc = Path("/proc")
    if not proc.is_dir():
        return 0
    allowed = tuple(str(path.resolve()) for path in TEMP_DIRS + SHM_DIRS)
    killed = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except OSError:
            continue
        executable = command.split(" ", 1)[0]
        if Path(executable).name not in {"7z", "7za"}:
            continue
        if not any(path in command for path in allowed):
            continue
        try:
            os.kill(int(entry.name), signal.SIGKILL)
            killed += 1
        except (ProcessLookupError, PermissionError):
            pass
    if killed:
        time.sleep(1)
    return killed


def _clean_directory(path: Path, expected_parent: Path) -> int:
    resolved = path.resolve()
    if resolved.parent != expected_parent.resolve():
        raise RuntimeError(f"Refusing unsafe clean target: {resolved}")
    before = shutil.disk_usage(expected_parent).free
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return max(0, shutil.disk_usage(expected_parent).free - before)


def _clean_tdlib_cache() -> tuple[int, int]:
    database = TDLIB_DATA / "data.db"
    account_parent = (TDLIB_DATA / "account").resolve()
    if not database.is_file() or not account_parent.is_dir():
        return 0, 0

    with sqlite3.connect(database) as connection:
        roots = [Path(row[0]).resolve() for row in connection.execute(
            "SELECT root_path FROM telegram_record"
        )]
        if len(roots) != 3:
            raise RuntimeError(f"Expected 3 TDLib accounts before cache clean, got {len(roots)}")
        for root in roots:
            if root.parent != account_parent:
                raise RuntimeError(f"Unsafe TDLib account root: {root}")

        released = 0
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.iterdir():
                if path.is_dir() and path.name in TDLIB_CACHE_NAMES:
                    released += _clean_directory(path, root)

        records = connection.execute("SELECT count(*) FROM file_record").fetchone()[0]
        connection.execute("DELETE FROM file_record")
        connection.execute("DELETE FROM disk_reservation")
        connection.commit()
    return released, int(records)


def main() -> None:
    killed = _stop_stale_extractors()
    released = 0
    for path in TEMP_DIRS:
        released += _clean_directory(path, BASE_DIR)
    if Path("/dev/shm").is_dir():
        for path in SHM_DIRS:
            released += _clean_directory(path, Path("/dev/shm"))

    runtime = PROJECT_ROOT / ".runtime"
    for suffix in ("", "-shm", "-wal"):
        (runtime / f"upload-jobs.db{suffix}").unlink(missing_ok=True)

    tdlib_released, file_records = _clean_tdlib_cache()
    released += tdlib_released

    reset = reset_transient_statuses(BASE_DIR / "full_hoahoc.csv")
    print(
        f"Clean start: killed_extractors={killed} "
        f"released_gb={released / 1024**3:.2f} "
        f"file_records={file_records} reset_claims={reset}"
    )


if __name__ == "__main__":
    main()
