"""Cross-process safe storage for the shared course status CSV."""

from __future__ import annotations

import csv
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterator


Normalize = Callable[[str], str]


@contextmanager
def _exclusive_lock(csv_path: Path, timeout: float = 30.0) -> Iterator[None]:
    lock_path = csv_path.with_suffix(csv_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "a+b")
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"0")
        lock_file.flush()

    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for CSV lock: {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def load_status(csv_path: Path, normalize: Normalize) -> Dict[str, str]:
    status_map: Dict[str, str] = {}
    with _exclusive_lock(csv_path):
        if not csv_path.exists():
            return status_map
        with open(csv_path, "r", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2:
                    status_map[normalize(row[0])] = row[1].strip()
    return status_map


def update_status(csv_path: Path, title: str, status: str, normalize: Normalize) -> None:
    clean_title = normalize(title)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _exclusive_lock(csv_path):
        rows = []
        found = False
        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8", newline="") as handle:
                for row in csv.reader(handle):
                    if not row:
                        continue
                    if normalize(row[0]) == clean_title:
                        rows.append([row[0].strip(), status, timestamp])
                        found = True
                    else:
                        rows.append(row)

        if not found:
            rows.append([clean_title, status, timestamp])

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{csv_path.name}.", suffix=".tmp", dir=csv_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, csv_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
