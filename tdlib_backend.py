#!/usr/bin/env python3
"""Cross-platform process manager for the local telegram-files backend."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
INSTALL = RUNTIME / "tdlib"
STATE_PATH = RUNTIME / "tdlib-backend.json"
ENV_PATH = RUNTIME / "tdlib.env"
DEFAULT_DATA = INSTALL / "data"


def load_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def health(base_url: str = "http://127.0.0.1:8080") -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_state() -> dict:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def find_java(environment: Optional[Dict[str, str]] = None) -> Optional[Path]:
    values = environment or os.environ
    explicit = values.get("TDLIB_JAVA")
    candidates = [
        Path(explicit) if explicit else None,
        INSTALL / "jdk" / ("bin/java.exe" if os.name == "nt" else "bin/java"),
    ]
    system_java = shutil.which("java")
    if system_java:
        candidates.append(Path(system_java))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    return None


def stop_pid(pid: int) -> None:
    if not process_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        if not process_alive(pid):
            return
        time.sleep(0.25)
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)


def start() -> int:
    base_url = os.environ.get("TDLIB_BASE_URL", "http://127.0.0.1:8080")
    state = read_state()
    if health(base_url):
        pid = int(state.get("pid") or 0)
        owner = f"PID={pid}" if process_alive(pid) else "external process"
        print(f"TDLib backend is already healthy ({owner}).")
        return 0

    values = load_env_file(Path(os.environ.get("TDLIB_ENV_FILE", ENV_PATH)))
    env = os.environ.copy()
    env.update(values)
    api_id = env.get("TELEGRAM_API_ID")
    api_hash = env.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        print(
            f"Missing TELEGRAM_API_ID/TELEGRAM_API_HASH. Configure {ENV_PATH} first.",
            file=sys.stderr,
        )
        return 2

    java = find_java(env)
    jar = Path(env.get("TDLIB_JAR_PATH", INSTALL / "telegram-files.jar"))
    library = Path(env.get("TDLIB_LIBRARY_PATH", INSTALL / "lib"))
    data = Path(env.get("TDLIB_DATA_ROOT", DEFAULT_DATA))
    if not java or not jar.is_file() or not library.is_dir():
        print(
            "TDLib artifacts are missing. Run setup-tdlib.ps1 (Windows) or "
            "setup-tdlib.sh (Ubuntu).",
            file=sys.stderr,
        )
        return 2


    RUNTIME.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    env["APP_ROOT"] = str(data.resolve())
    env.setdefault("APP_ENV", "prod")
    env.setdefault("LOG_LEVEL", "INFO")
    env.setdefault("TELEGRAM_LOG_LEVEL", "0")
    if os.name == "nt":
        env["PATH"] = f"{library.resolve()}{os.pathsep}{env.get('PATH', '')}"
    else:
        env["LD_LIBRARY_PATH"] = (
            f"{library.resolve()}{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"
        )

    stdout_path = RUNTIME / "tdlib-backend.stdout.log"
    stderr_path = RUNTIME / "tdlib-backend.stderr.log"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(stdout_path, "ab", buffering=0) as stdout, open(
        stderr_path, "ab", buffering=0
    ) as stderr:
        process = subprocess.Popen(
            [
                str(java),
                f"-Djava.library.path={library.resolve()}",
                "-jar",
                str(jar.resolve()),
            ],
            cwd=data,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    STATE_PATH.write_text(
        json.dumps(
            {
                "pid": process.pid,
                "jar": str(jar.resolve()),
                "data": str(data.resolve()),
                "startedAt": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for _ in range(30):
        if health(base_url):
            print(f"TDLib backend started (PID={process.pid}, {base_url}).")
            return 0
        if process.poll() is not None:
            break
        time.sleep(1)
    print(f"TDLib backend failed to start. Check {stderr_path}.", file=sys.stderr)
    return 1


def status() -> int:
    state = read_state()
    pid = int(state.get("pid") or 0)
    base_url = os.environ.get("TDLIB_BASE_URL", "http://127.0.0.1:8080")
    print(
        json.dumps(
            {
                "healthy": health(base_url),
                "managedPid": pid or None,
                "managedProcessAlive": process_alive(pid),
                "baseUrl": base_url,
                "data": state.get("data"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if health(base_url) else 1


def stop() -> int:
    state = read_state()
    pid = int(state.get("pid") or 0)
    if pid:
        stop_pid(pid)
        print(f"Stopped managed TDLib backend PID={pid}.")
    else:
        print("No managed TDLib backend is recorded; external processes were not touched.")
    STATE_PATH.unlink(missing_ok=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "status", "stop"), nargs="?", default="start")
    args = parser.parse_args()
    return {"start": start, "status": status, "stop": stop}[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
