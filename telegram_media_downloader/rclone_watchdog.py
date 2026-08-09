"""Progress-aware rclone execution shared by the course pipelines."""

from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional


COMPLETION_MARKER = ".geturl-complete"
_TRANSFERRED_RE = re.compile(
    r"Transferred:\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?i?B)",
    re.IGNORECASE,
)
_UNIT_FACTORS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "PB": 1000**5,
    "EB": 1000**6,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
    "PIB": 1024**5,
    "EIB": 1024**6,
}


def parse_transferred_bytes(line: str) -> Optional[int]:
    """Return rclone's completed byte count from a stats line."""
    match = _TRANSFERRED_RE.search(line)
    if not match:
        return None
    return int(float(match.group(1)) * _UNIT_FACTORS[match.group(2).upper()])


def _stop_process(process: subprocess.Popen) -> None:
    process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_rclone_with_watchdog(
    command: Iterable[str],
    *,
    on_output: Callable[[str], None],
    on_warning: Callable[[str], None],
    idle_timeout: float = 1800,
    max_attempts: int = 3,
    retry_delay: float = 10,
) -> bool:
    """Run rclone and retry only when it exits or makes no byte progress."""
    cmd = list(command)
    for attempt in range(1, max_attempts + 1):
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines: queue.Queue[Optional[str]] = queue.Queue()

        def read_output() -> None:
            if process.stdout is not None:
                for raw in process.stdout:
                    for line in re.split(r"[\r\n]+", raw):
                        if line.strip():
                            lines.put(line.strip())
            lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        last_progress = time.monotonic()
        highest_transferred = -1
        output_finished = False
        idle_killed = False

        while True:
            try:
                line = lines.get(timeout=1)
                if line is None:
                    output_finished = True
                else:
                    on_output(line)
                    transferred = parse_transferred_bytes(line)
                    if transferred is not None and transferred > highest_transferred:
                        highest_transferred = transferred
                        last_progress = time.monotonic()
            except queue.Empty:
                pass

            if process.poll() is not None and output_finished:
                break
            if time.monotonic() - last_progress >= idle_timeout:
                idle_killed = True
                on_warning(
                    f"Rclone khong tang byte trong {int(idle_timeout)}s; "
                    f"kill attempt {attempt}/{max_attempts}."
                )
                _stop_process(process)
                break

        reader.join(timeout=5)
        return_code = process.poll()
        if return_code == 0:
            return True
        if attempt < max_attempts:
            reason = "idle timeout" if idle_killed else f"exit code {return_code}"
            on_warning(
                f"Rclone {reason}; retry {attempt + 1}/{max_attempts} sau {int(retry_delay)}s."
            )
            time.sleep(retry_delay)

    return False


def mark_remote_complete(target_remote_path: str, timeout: float = 60) -> bool:
    result = subprocess.run(
        ["rclone", "touch", f"{target_remote_path.rstrip('/')}/{COMPLETION_MARKER}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    return result.returncode == 0


def remote_has_completion_marker(target_remote_path: str, timeout: float = 30) -> bool:
    try:
        result = subprocess.run(
            ["rclone", "lsf", f"{target_remote_path.rstrip('/')}/{COMPLETION_MARKER}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0 and COMPLETION_MARKER in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def remote_folder_exists(target_remote_path: str, timeout: float = 30) -> bool:
    """Return True when rclone can list the remote course directory.

    Existing legacy course folders predate the completion marker.  The
    pipeline's contract treats the folder itself as authoritative, including
    an empty folder, so only rclone's exit status matters here.
    """
    try:
        result = subprocess.run(
            ["rclone", "lsf", target_remote_path.rstrip("/"), "--max-depth", "1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False
