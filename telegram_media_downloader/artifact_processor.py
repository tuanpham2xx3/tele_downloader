"""Turn downloaded Telegram files into upload-ready course artifacts."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
ARCHIVE_HEADERS = (".zip", ".rar", ".7z")


def is_archive_header(path: Path) -> bool:
    name = path.name.lower()
    if re.search(r"\.z\d+$", name):
        return False
    if re.search(r"\.part\d+\.rar$", name):
        return bool(re.search(r"\.part0*1\.rar$", name))
    if re.search(r"\.7z\.\d+$", name):
        return name.endswith(".7z.001")
    return name.endswith(ARCHIVE_HEADERS)


def _extract(archive: Path, destination: Path) -> tuple[bool, str]:
    seven_zip = shutil.which("7z") or shutil.which("7za")
    if seven_zip:
        result = subprocess.run(
            [seven_zip, "x", "-y", "-aoa", "-p-", "-mmt=on",
             f"-o{destination}", str(archive)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1800,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stdout[-1000:]
    if archive.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(archive) as handle:
                handle.extractall(destination)
            return True, ""
        except Exception as exc:
            return False, str(exc)
    return False, "7z/7za is required for this archive format"


def _unique_destination(directory: Path, source: Path) -> Path:
    destination = directory / source.name
    if not destination.exists():
        return destination
    if destination.stat().st_size == source.stat().st_size:
        return destination
    return directory / f"{source.stem}_{source.stat().st_size}{source.suffix}"


def prepare_course(course_dir: Path, log: Callable[[str], None] = print) -> Path:
    """Rebuild upload artifacts while preserving every raw Telegram download."""
    archives_dir = course_dir / "archives"
    extracted_dir = course_dir / "extracted"
    upload_dir = course_dir / "upload"
    if not archives_dir.is_dir() or not any(archives_dir.iterdir()):
        raise RuntimeError(f"No downloaded files found in {archives_dir}")
    shutil.rmtree(extracted_dir, ignore_errors=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    extracted_dir.mkdir(parents=True)
    upload_dir.mkdir(parents=True)

    raw_files = [path for path in archives_dir.iterdir() if path.is_file()]
    archive_headers = [path for path in raw_files if is_archive_header(path)]
    archive_members = {
        path for path in raw_files
        if is_archive_header(path)
        or re.search(r"(?:\.z\d+|\.7z\.\d+|\.part\d+\.rar)$", path.name, re.I)
    }
    for archive in archive_headers:
        log(f"Extracting {archive.name}")
        ok, error = _extract(archive, extracted_dir)
        if not ok:
            raise RuntimeError(f"Cannot extract {archive.name}: {error}")

    for source in raw_files:
        if source in archive_members:
            continue
        destination = _unique_destination(extracted_dir, source)
        if not destination.exists():
            shutil.copy2(source, destination)

    all_files = [path for path in extracted_dir.rglob("*") if path.is_file()]
    videos = [path for path in all_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    documents = [path for path in all_files if path not in videos]
    if not all_files:
        raise RuntimeError("Processing produced no uploadable files")

    for video in videos:
        destination = _unique_destination(upload_dir, video)
        if not destination.exists():
            shutil.copy2(video, destination)

    if documents:
        materials = upload_dir / "Class_Materials.zip"
        with zipfile.ZipFile(materials, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as handle:
            for document in documents:
                handle.write(document, document.relative_to(extracted_dir))

    if not any(upload_dir.iterdir()):
        raise RuntimeError("Upload directory is empty")
    return upload_dir
