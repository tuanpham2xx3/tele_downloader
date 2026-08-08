"""Cross-process safe storage for the shared course status CSV."""

from __future__ import annotations

import csv
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, Tuple


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


def _write_rows_atomic(csv_path: Path, rows: list[list[str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{csv_path.name}.", suffix=".tmp", dir=csv_path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        replace_deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(temporary_name, csv_path)
                break
            except PermissionError:
                if time.monotonic() >= replace_deadline:
                    raise
                time.sleep(0.05)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


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

        _write_rows_atomic(csv_path, rows)


def claim_status(
    csv_path: Path,
    title: str,
    new_status: str,
    allowed_statuses: Iterable[str],
    normalize: Normalize,
) -> Tuple[bool, str]:
    """Atomically change status only when its current value is allowed."""
    clean_title = normalize(title)
    allowed = set(allowed_statuses)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _exclusive_lock(csv_path):
        rows: list[list[str]] = []
        found = False
        current_status = "PENDING"
        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8", newline="") as handle:
                for row in csv.reader(handle):
                    if not row:
                        continue
                    if normalize(row[0]) == clean_title:
                        current_status = row[1].strip() if len(row) >= 2 else "PENDING"
                        found = True
                    rows.append(row)

        if current_status not in allowed:
            return False, current_status

        replacement = [clean_title, new_status, timestamp]
        if found:
            rows = [
                [row[0].strip(), new_status, timestamp]
                if row and normalize(row[0]) == clean_title
                else row
                for row in rows
            ]
        else:
            rows.append(replacement)

        _write_rows_atomic(csv_path, rows)
        return True, current_status


def reset_transient_statuses(csv_path: Path) -> int:
    """Release in-flight ownership after all pipeline processes have stopped."""
    with _exclusive_lock(csv_path):
        if not csv_path.exists():
            return 0

        rows: list[list[str]] = []
        reset_count = 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(csv_path, "r", encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2 and row[1].strip().startswith(("PROCESSING_", "FORWARDED_")):
                    rows.append([row[0].strip(), "PENDING", timestamp])
                    reset_count += 1
                else:
                    rows.append(row)

        if reset_count:
            _write_rows_atomic(csv_path, rows)
        return reset_count
