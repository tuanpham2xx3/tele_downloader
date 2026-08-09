"""Persistent hand-off queue between Telegram, processing, and rclone workers."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_DB_PATH = Path(
    os.environ.get("GETURL_QUEUE_DB", PROJECT_ROOT / ".runtime" / "upload-jobs.db")
)

DOWNLOADED = "DOWNLOADED"
PROCESSING = "PROCESSING"
READY_UPLOAD = "READY_UPLOAD"
UPLOADING = "UPLOADING"
RETRY_UPLOAD = "RETRY_UPLOAD"
COMPLETED = "COMPLETED"
FAILED_PROCESS = "FAILED_PROCESS"
ACTIVE_STATUSES = (DOWNLOADED, PROCESSING, READY_UPLOAD, UPLOADING, RETRY_UPLOAD)


def normalize_course_title(title: str) -> str:
    if not title:
        return ""
    return re.sub(r"[*`~_]", "", title).strip()


@dataclass(frozen=True)
class UploadJob:
    id: int
    title: str
    normalized_title: str
    owner: str
    course_dir: Path
    rclone_parent: str
    status: str
    attempts: int
    next_retry_at: float
    error: str


class UploadQueue:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS upload_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL,
                    course_dir TEXT NOT NULL,
                    rclone_parent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_upload_jobs_claim
                    ON upload_jobs(status, next_retry_at, updated_at);
                """
            )

    @staticmethod
    def _job(row: sqlite3.Row | None) -> Optional[UploadJob]:
        if row is None:
            return None
        return UploadJob(
            id=int(row["id"]), title=str(row["title"]),
            normalized_title=str(row["normalized_title"]), owner=str(row["owner"]),
            course_dir=Path(str(row["course_dir"])),
            rclone_parent=str(row["rclone_parent"]), status=str(row["status"]),
            attempts=int(row["attempts"]), next_retry_at=float(row["next_retry_at"]),
            error=str(row["error"]),
        )

    def enqueue_downloaded(
        self, *, title: str, normalized_title: str, owner: str,
        course_dir: Path | str, rclone_parent: str,
    ) -> UploadJob:
        now = time.time()
        absolute_dir = str(Path(course_dir).resolve())
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO upload_jobs
                    (title, normalized_title, owner, course_dir, rclone_parent,
                     status, attempts, next_retry_at, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, '', ?, ?)
                ON CONFLICT(normalized_title) DO UPDATE SET
                    title=excluded.title, owner=excluded.owner,
                    course_dir=excluded.course_dir, rclone_parent=excluded.rclone_parent,
                    status=excluded.status, attempts=0, next_retry_at=0,
                    error='', updated_at=excluded.updated_at
                """,
                (title, normalized_title, owner, absolute_dir, rclone_parent,
                 DOWNLOADED, now, now),
            )
            row = connection.execute(
                "SELECT * FROM upload_jobs WHERE normalized_title=?", (normalized_title,)
            ).fetchone()
        job = self._job(row)
        assert job is not None
        return job

    def claim(self, statuses: Iterable[str], claimed_status: str) -> Optional[UploadJob]:
        values = tuple(statuses)
        if not values:
            return None
        now = time.time()
        placeholders = ",".join("?" for _ in values)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""SELECT * FROM upload_jobs
                    WHERE status IN ({placeholders}) AND next_retry_at <= ?
                    ORDER BY updated_at, id LIMIT 1""",
                (*values, now),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                "UPDATE upload_jobs SET status=?, updated_at=? WHERE id=?",
                (claimed_status, now, row["id"]),
            )
            updated = connection.execute(
                "SELECT * FROM upload_jobs WHERE id=?", (row["id"],)
            ).fetchone()
            connection.commit()
            return self._job(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_status(
        self, job_id: int, status: str, *, error: str = "",
        retry_delay: float = 0, increment_attempt: bool = False,
    ) -> None:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """UPDATE upload_jobs SET status=?, error=?, next_retry_at=?,
                   attempts=attempts+?, updated_at=? WHERE id=?""",
                (status, error[-2000:], now + retry_delay,
                 1 if increment_attempt else 0, now, job_id),
            )

    def recover_inflight(self) -> int:
        now = time.time()
        with closing(self._connect()) as connection, connection:
            first = connection.execute(
                "UPDATE upload_jobs SET status=?, updated_at=? WHERE status=?",
                (DOWNLOADED, now, PROCESSING),
            ).rowcount
            second = connection.execute(
                "UPDATE upload_jobs SET status=?, next_retry_at=0, updated_at=? WHERE status=?",
                (READY_UPLOAD, now, UPLOADING),
            ).rowcount
        return int(first + second)

    def pending_count(self) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM upload_jobs WHERE status IN ({placeholders})",
                ACTIVE_STATUSES,
            ).fetchone()
        return int(row["count"])

    def jobs_with_status(self, status: str) -> list[UploadJob]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM upload_jobs WHERE status=? ORDER BY updated_at, id",
                (status,),
            ).fetchall()
        return [job for row in rows if (job := self._job(row)) is not None]


def has_download_capacity(
    queue: UploadQueue, storage_path: Path | str, *, max_pending: int = 3,
    min_free_gb: float = 10.0,
) -> tuple[bool, str]:
    pending = queue.pending_count()
    if pending >= max_pending:
        return False, f"queue dang co {pending}/{max_pending} khoa cho"
    path = Path(storage_path)
    while not path.exists() and path.parent != path:
        path = path.parent
    free_gb = shutil.disk_usage(path).free / 1024**3
    if free_gb < min_free_gb:
        return False, f"dia chi con {free_gb:.1f}GB (<{min_free_gb:.1f}GB)"
    return True, f"queue={pending}, disk_free={free_gb:.1f}GB"
