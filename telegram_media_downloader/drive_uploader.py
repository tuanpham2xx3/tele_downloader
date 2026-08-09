#!/usr/bin/env python3
"""Dedicated rclone upload, verification, completion-marker, and cleanup service."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

try:
    from .csv_status_store import update_status
    from .drive_ownership import remote_name, replace_remote_name, transfer_remote_tree
    from .rclone_watchdog import mark_remote_complete, run_rclone_with_watchdog
    from .upload_queue import (
        READY_UPLOAD, RETRY_UPLOAD, UPLOADING, COMPLETED, UploadQueue,
        normalize_course_title,
    )
except ImportError:
    from csv_status_store import update_status
    from drive_ownership import remote_name, replace_remote_name, transfer_remote_tree
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


def refresh_upload_mtimes(upload_dir: Path) -> None:
    """Make Drive show this upload time instead of Telegram's old file dates."""
    uploaded_at = time.time()
    paths = sorted(upload_dir.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in [*paths, upload_dir]:
        if not path.is_symlink():
            os.utime(path, (uploaded_at, uploaded_at))


def upload_job(
    job, uploader_remote: str | None = None, owner_remote: str | None = None,
) -> tuple[bool, str]:
    upload_dir = job.course_dir / "upload"
    if not upload_dir.is_dir() or not any(upload_dir.iterdir()):
        return False, f"upload directory is empty: {upload_dir}"
    refresh_upload_mtimes(upload_dir)
    uploader = uploader_remote or job.upload_remote or remote_name(job.rclone_parent)
    owner = owner_remote or remote_name(job.rclone_parent)
    source_parent = replace_remote_name(job.rclone_parent, uploader)
    owner_parent = replace_remote_name(job.rclone_parent, owner)
    remote = f"{source_parent.rstrip('/')}/{sanitize_name(job.title)}"
    owner_path = f"{owner_parent.rstrip('/')}/{sanitize_name(job.title)}"
    command = [
        "rclone", "copy", str(upload_dir), remote,
        "--transfers", "2", "--checkers", "4",
        "--size-only", "--no-update-modtime",
        "--buffer-size", "64M", "--drive-chunk-size", "128M",
        "--tpslimit", "4", "--tpslimit-burst", "4",
        "--timeout", "2m", "--contimeout", "15s",
        "--retries", "3", "--low-level-retries", "3",
        "--stats", "10s", "--stats-one-line-date", "--stats-log-level", "NOTICE",
    ]
    log(f"Uploading [{job.title}] via [{uploader}] -> {remote}")
    copied = run_rclone_with_watchdog(
        command, on_output=lambda line: log(line), on_warning=lambda line: log(line, "WARN"),
        idle_timeout=300, max_attempts=3, retry_delay=15,
    )
    if not copied:
        return False, "rclone copy failed or made no file/byte progress for 5 minutes"
    log(f"Verifying [{job.title}] through [{uploader}]")
    verified, detail = _verify(upload_dir, remote)
    if not verified:
        return False, f"rclone check failed: {detail}"
    if remote_name(remote) != remote_name(owner_path):
        log(f"Transferring ownership [{job.title}] from [{uploader}] to [{owner}]")
        changed = transfer_remote_tree(
            remote, owner,
            on_progress=lambda message: log(f"[{uploader}] {message}"),
        )
        log(f"Transferred ownership for {changed} objects [{job.title}]", "SUCCESS")
        log(f"Verifying [{job.title}] through owner [{owner}]")
        verified, detail = _verify(upload_dir, owner_path)
        if not verified:
            return False, f"owner rclone check failed: {detail}"
    if not mark_remote_complete(owner_path):
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


def run(
    poll_interval: float, uploader_remote: str, owner_remote: str,
    cleanup_on_start: bool = True,
) -> None:
    queue = UploadQueue()
    if cleanup_on_start:
        cleanup_completed(queue)
    last_cleanup = time.monotonic()
    log(f"Uploader worker ready: remote={uploader_remote}, owner={owner_remote}")
    while True:
        job = queue.claim_for_uploader(
            (READY_UPLOAD, RETRY_UPLOAD), UPLOADING, uploader_remote,
        )
        if job is None:
            if time.monotonic() - last_cleanup >= 300:
                cleanup_completed(queue)
                last_cleanup = time.monotonic()
            time.sleep(poll_interval)
            continue
        try:
            ok, error = upload_job(job, uploader_remote, owner_remote)
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


def parse_remotes(value: str) -> list[str]:
    remotes: list[str] = []
    for raw in value.split(","):
        name = raw.strip().rstrip(":")
        if name and name not in remotes:
            remotes.append(name)
    if not remotes:
        raise ValueError("At least one uploader remote is required")
    return remotes


def validate_rclone_remotes(remotes: list[str], owner_remote: str) -> None:
    result = subprocess.run(
        ["rclone", "listremotes"], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rclone listremotes failed: {result.stderr[-1000:]}")
    configured = {line.strip().rstrip(":") for line in result.stdout.splitlines()}
    required = {*remotes, owner_remote}
    missing = sorted(required - configured)
    if missing:
        raise RuntimeError(f"Missing rclone remotes: {', '.join(missing)}")


def _run_worker(remote: str, owner_remote: str, poll_interval: float) -> None:
    # Forked Linux children inherit the supervisor's handlers. Restore normal
    # termination so stopping the tracked parent cannot leave orphan uploaders.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    run(poll_interval, remote, owner_remote, False)


def _start_worker(remote: str, owner_remote: str, poll_interval: float) -> multiprocessing.Process:
    process = multiprocessing.Process(
        target=_run_worker, args=(remote, owner_remote, poll_interval),
        name=f"uploader-{remote}", daemon=False,
    )
    process.start()
    return process


def run_pool(remotes: list[str], owner_remote: str, poll_interval: float) -> None:
    validate_rclone_remotes(remotes, owner_remote)
    queue = UploadQueue()
    cleanup_completed(queue)
    released = queue.release_inactive_upload_remotes(remotes)
    if released:
        log(f"Released {released} jobs pinned to inactive uploader remotes", "WARN")
    if len(remotes) == 1:
        run(poll_interval, remotes[0], owner_remote, False)
        return

    stopping = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    children = {
        remote: _start_worker(remote, owner_remote, poll_interval) for remote in remotes
    }
    log(f"Uploader pool started: {', '.join(remotes)}; canonical owner={owner_remote}")
    try:
        while not stopping:
            time.sleep(2)
            for remote, process in list(children.items()):
                if process.is_alive():
                    continue
                log(
                    f"Uploader child [{remote}] exited code={process.exitcode}; restarting",
                    "ERROR",
                )
                children[remote] = _start_worker(remote, owner_remote, poll_interval)
    finally:
        for process in children.values():
            if process.is_alive():
                process.terminate()
        for process in children.values():
            process.join(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-interval", type=float, default=2)
    parser.add_argument(
        "--remotes", default=os.environ.get("GETURL_UPLOAD_REMOTES", "gdrive"),
        help="Comma-separated rclone remote names used as parallel uploaders",
    )
    parser.add_argument(
        "--owner-remote", default=os.environ.get("GETURL_OWNER_REMOTE", "gdrive"),
        help="Canonical rclone remote that must own every completed file",
    )
    args = parser.parse_args()
    run_pool(parse_remotes(args.remotes), args.owner_remote.rstrip(":"), args.poll_interval)
