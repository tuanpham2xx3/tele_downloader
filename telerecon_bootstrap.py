"""Run unmodified Telerecon with credentials supplied by the parent process."""

from __future__ import annotations

import os
import runpy
import sys
import types
from pathlib import Path


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


project_root = Path(__file__).resolve().parent
telerecon_root = project_root / "Telerecon"
launcher = telerecon_root / "launcher.py"

if not launcher.is_file():
    raise SystemExit("Telerecon is missing. Run: git submodule update --init")

details = types.ModuleType("details")
try:
    details.apiID = int(required_environment("TELERECON_API_ID"))
except ValueError as error:
    raise SystemExit("Telegram API ID must be a number.") from error
details.apiHash = required_environment("TELERECON_API_HASH")
details.number = required_environment("TELERECON_PHONE")
sys.modules["details"] = details

os.chdir(telerecon_root)
sys.path.insert(0, str(telerecon_root))
runpy.run_path(str(launcher), run_name="__main__")
