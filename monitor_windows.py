#!/usr/bin/env python3
"""Read-only health monitor for the native Windows Telegram pipelines."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "telegram_media_downloader"))
from csv_status_store import load_status


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
STATE_PATH = RUNTIME / "windows-pipelines.json"
CSV_PATH = ROOT / "telegram_media_downloader" / "full_hoahoc.csv"
MONITOR_LOG = RUNTIME / "windows-monitor.log"
ALERT_LOG = RUNTIME / "windows-monitor-alerts.log"
INTERVAL_SECONDS = 30
STALL_SECONDS = 15 * 60

LOG_FILES = {
    "acc1": [RUNTIME / "pipeline_acc1.stdout.log", RUNTIME / "pipeline_acc1.stderr.log"],
    "acc2": [ROOT / "pipeline_acc2.log", RUNTIME / "pipeline_acc2.stderr.log"],
    "acc3": [ROOT / "pipeline_acc3.log", RUNTIME / "pipeline_acc3.stderr.log"],
}

ERROR_PATTERNS = re.compile(
    r"Traceback|PermissionError|UnicodeEncodeError|database is locked|"
    r"size mismatch|FAILED_DOWNLOAD|FAILED_RCLONE|FAILED_EXTRACT|\[ERROR\]",
    re.IGNORECASE,
)


def write_line(message: str, alert: bool = False) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level = "ALERT" if alert else "MONITOR"
    line = f"[{timestamp}] [{level}] {message}"
    print(line, flush=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with open(MONITOR_LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    if alert:
        with open(ALERT_LOG, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def process_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information, False, int(pid)
    )
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def load_pipeline_state() -> List[dict]:
    if not STATE_PATH.exists():
        return []
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else [data]
    except (OSError, json.JSONDecodeError):
        return []


def load_ownership() -> List[Tuple[str, str]]:
    if not CSV_PATH.exists():
        return []
    try:
        statuses = load_status(CSV_PATH, lambda value: value.strip())
        return [
            (title, status)
            for title, status in statuses.items()
            if re.match(r"^(PROCESSING|FORWARDED)_ACC[123]$", status)
        ]
    except (OSError, TimeoutError):
        return []


def ownership_alerts(ownership: Iterable[Tuple[str, str]]) -> List[str]:
    rows = list(ownership)
    alerts: List[str] = []
    by_status: Dict[str, List[str]] = {}
    by_title: Dict[str, List[str]] = {}
    for title, status in rows:
        by_status.setdefault(status, []).append(title)
        by_title.setdefault(title.casefold(), []).append(status)

    for owner in ("ACC1", "ACC2", "ACC3"):
        active = by_status.get(f"PROCESSING_{owner}", [])
        if len(active) > 1:
            alerts.append(f"{owner} owns {len(active)} active courses: {active}")

    for title, statuses in by_title.items():
        processing = [status for status in statuses if status.startswith("PROCESSING_")]
        if len(processing) > 1:
            alerts.append(f"Duplicate active course [{title}] across {processing}")
    return alerts


def newest_log_age(paths: Iterable[Path]) -> float | None:
    mtimes = [path.stat().st_mtime for path in paths if path.exists()]
    return time.time() - max(mtimes) if mtimes else None


def read_new_errors(path: Path, offsets: Dict[str, int]) -> List[str]:
    key = str(path)
    if not path.exists():
        return []
    size = path.stat().st_size
    offset = offsets.get(key, max(0, size - 32 * 1024))
    if size < offset:
        offset = 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        content = handle.read()
        offsets[key] = handle.tell()
    matches = []
    for line in content.splitlines():
        if "d.innerHTML" in line:
            continue
        if ERROR_PATTERNS.search(line):
            matches.append(line[-500:])
    return matches


def get_memory_free_gb() -> float:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    if os.name != "nt":
        return 0.0
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullAvailPhys / 1024**3


def monitor_loop() -> None:
    offsets: Dict[str, int] = {}
    write_line("Windows pipeline monitor started (read-only, interval=30s).")

    for _ in range(20):
        if any(entry.get("Name") in LOG_FILES for entry in load_pipeline_state()):
            break
        time.sleep(0.5)
    else:
        write_line("Pipeline state did not appear during startup; monitor exiting.", alert=True)
        return

    while True:
        state = load_pipeline_state()
        pipelines = {entry.get("Name"): entry for entry in state if entry.get("Name") in LOG_FILES}
        if not pipelines:
            write_line("Pipeline state is absent; monitor exiting.")
            return

        alerts: List[str] = []
        statuses = []
        for name, port in (("acc1", 5000), ("acc2", 5001), ("acc3", 5002)):
            entry = pipelines.get(name)
            alive = bool(entry and process_alive(int(entry.get("Pid", 0))))
            listening = port_listening(port)
            statuses.append(f"{name}={'UP' if alive and listening else 'DOWN'}")
            if not alive or not listening:
                alerts.append(f"{name} unhealthy: process={alive}, port{port}={listening}")

            age = newest_log_age(LOG_FILES[name])
            if alive and age is not None and age > STALL_SECONDS:
                alerts.append(f"{name} log stalled for {int(age)}s")

            for path in LOG_FILES[name]:
                for error_line in read_new_errors(path, offsets):
                    alerts.append(f"{name} error: {error_line}")

        ownership = load_ownership()
        alerts.extend(ownership_alerts(ownership))

        free_ram = get_memory_free_gb()
        free_disk = shutil.disk_usage(ROOT).free / 1024**3
        if free_ram and free_ram < 2.0:
            alerts.append(f"Low RAM: {free_ram:.1f}GB free")
        if free_disk < 10.0:
            alerts.append(f"Low disk: {free_disk:.1f}GB free")

        write_line(
            f"{' | '.join(statuses)} | active={sum(1 for _, status in ownership if status.startswith('PROCESSING_'))} "
            f"| queued={sum(1 for _, status in ownership if status.startswith('FORWARDED_'))} "
            f"| RAM={free_ram:.1f}GB | disk={free_disk:.1f}GB"
        )
        for alert in alerts:
            write_line(alert, alert=True)

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    monitor_loop()
