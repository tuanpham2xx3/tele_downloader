#!/usr/bin/env python3
"""Dedicated extraction/repackaging service for downloaded course jobs."""

from __future__ import annotations

import argparse
import time
from datetime import datetime

try:
    from .artifact_processor import prepare_course
    from .upload_queue import DOWNLOADED, FAILED_PROCESS, PROCESSING, READY_UPLOAD, UploadQueue
except ImportError:
    from artifact_processor import prepare_course
    from upload_queue import DOWNLOADED, FAILED_PROCESS, PROCESSING, READY_UPLOAD, UploadQueue


def log(message: str, level: str = "INFO") -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] [PROCESSOR] {message}", flush=True)


def run(poll_interval: float) -> None:
    queue = UploadQueue()
    recovered = queue.recover_inflight()
    if recovered:
        log(f"Recovered {recovered} interrupted job(s)", "WARN")
    while True:
        job = queue.claim((DOWNLOADED, FAILED_PROCESS), PROCESSING)
        if job is None:
            time.sleep(poll_interval)
            continue
        try:
            log(f"Processing [{job.title}] from {job.owner}")
            prepare_course(job.course_dir, log)
            queue.set_status(job.id, READY_UPLOAD)
            log(f"Ready for upload [{job.title}]", "SUCCESS")
        except Exception as exc:
            queue.set_status(job.id, FAILED_PROCESS, error=str(exc),
                             retry_delay=300, increment_attempt=True)
            log(f"Failed [{job.title}]: {exc}; raw files retained", "ERROR")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-interval", type=float, default=2)
    run(parser.parse_args().poll_interval)
