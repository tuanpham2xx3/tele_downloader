#!/usr/bin/env python3
"""Dedicated rclone upload, verification, completion-marker, and cleanup service."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

try:
    from .csv_status_store import update_status
    from .rclone_watchdog import mark_remote_complete, run_rclone_with_watchdog
    from .upload_queue import (
        READY_UPLOAD, RETRY_UPLOAD, UPLOADING, COMPLETED, UploadQueue,
        normalize_course_title,
    )
except ImportError:
    from csv_status_store import update_status
    from rclone_watchdog import mark_remote_complete, run_rclone_with_watchdog
    from upload_queue import (
        READY_UPLOAD, RETRY_UPLOAD, UPLOADING, COMPLETED, UploadQueue,
        normalize_course_title,
    )


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "full_hoahoc.csv"


def sanitize_name(name: str) -> str:
    clean = re.sub(r"[*`~_]", "", name)
    clean = re.sub(r'[\\/*?:"<>|]', "", clean).strip().strip(".").strip("_")
    return clean[:120] or "Unassigned_Course"


def log(message: str, level: str = "INFO") -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] [UPLOADER] {message}", flush=True)


def _verify(source: Path, remote: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["rclone", "check", str(source), remote, "--one-way", "--size-only",
             "--checkers", "8", "--fast-list"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3600,
        )
        return result.returncode == 0, result.stdout[-2000:]
    except subprocess.TimeoutExpired:
        return False, "rclone check timed out after 3600s"


def upload_job(job) -> tuple[bool, str]:
    upload_dir = job.course_dir / "upload"
    if not upload_dir.is_dir() or not any(upload_dir.iterdir()):
        return False, f"upload directory is empty: {upload_dir}"
    remote = f"{job.rclone_parent.rstrip('/')}/{sanitize_name(job.title)}"
    command = [
        "rclone", "copy", str(upload_dir), remote,
        "--transfers", "2", "--checkers", "4",
        "--buffer-size", "64M", "--drive-chunk-size", "64M",
        "--tpslimit", "8", "--tpslimit-burst", "8",
        "--timeout", "10m", "--contimeout", "30s",
        "--retries", "3", "--low-level-retries", "10",
        "--stats", "10s", "--stats-one-line-date", "--stats-log-level", "NOTICE",
    ]
    log(f"Uploading [{job.title}] -> {remote}")
    copied = run_rclone_with_watchdog(
        command, on_output=lambda line: log(line), on_warning=lambda line: log(line, "WARN"),
        idle_timeout=180, max_attempts=3, retry_delay=30,
    )
    if not copied:
        return False, "rclone copy failed or made no byte progress for 30 minutes"
    log(f"Verifying [{job.title}] against Drive")
    verified, detail = _verify(upload_dir, remote)
    if not verified:
        return False, f"rclone check failed: {detail}"
    if not mark_remote_complete(remote):
        return False, "could not create remote completion marker"
    return True, ""


def cleanup_completed(queue: UploadQueue) -> None:
    for job in queue.jobs_with_status(COMPLETED):
        if not job.course_dir.exists():
            continue
        try:
            shutil.rmtree(job.course_dir, ignore_errors=False)
            log(f"Cleaned completed local job [{job.title}]", "SUCCESS")
        except OSError as exc:
            log(f"Cleanup still pending [{job.title}]: {exc}", "WARN")


def run(poll_interval: float) -> None:
    queue = UploadQueue()
    cleanup_completed(queue)
    last_cleanup = time.monotonic()
    while True:
        job = queue.claim((READY_UPLOAD, RETRY_UPLOAD), UPLOADING)
        if job is None:
            if time.monotonic() - last_cleanup >= 300:
                cleanup_completed(queue)
                last_cleanup = time.monotonic()
            time.sleep(poll_interval)
            continue
        try:
            ok, error = upload_job(job)
        except Exception as exc:
            ok, error = False, str(exc)
        if not ok:
            delay = min(3600, 60 * (2 ** min(job.attempts, 5)))
            queue.set_status(job.id, RETRY_UPLOAD, error=error,
                             retry_delay=delay, increment_attempt=True)
            log(f"Failed [{job.title}]: {error}; retry in {delay}s, local retained", "ERROR")
            continue
        update_status(CSV_PATH, job.title, "COMPLETED", normalize_course_title)
        queue.set_status(job.id, COMPLETED)
        try:
            shutil.rmtree(job.course_dir, ignore_errors=False)
            log(f"Completed and cleaned [{job.title}]", "SUCCESS")
        except OSError as exc:
            log(f"Completed [{job.title}], but local cleanup failed: {exc}", "WARN")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-interval", type=float, default=2)
    run(parser.parse_args().poll_interval)
