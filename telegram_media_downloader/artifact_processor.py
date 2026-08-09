"""Turn downloaded Telegram files into upload-ready course artifacts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
ARCHIVE_HEADERS = (".zip", ".rar", ".7z")
PROCESSING_MARKER = ".processing-complete"


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


def _archive_family(archive: Path, raw_files: list[Path]) -> list[Path]:
    """Return the header and every split volume consumed by one extraction."""
    name = archive.name.lower()
    if name.endswith(".7z.001"):
        prefix = name[:-4]
        return [path for path in raw_files if path.name.lower().startswith(prefix + ".")]
    part = re.match(r"^(.*)\.part0*1\.rar$", name)
    if part:
        pattern = re.compile(re.escape(part.group(1)) + r"\.part\d+\.rar$", re.I)
        return [path for path in raw_files if pattern.match(path.name)]
    if name.endswith(".zip"):
        prefix = name[:-4]
        volumes = re.compile(re.escape(prefix) + r"\.z\d+$", re.I)
        return [path for path in raw_files if path == archive or volumes.match(path.name)]
    return [archive]


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def prepare_course(course_dir: Path, log: Callable[[str], None] = print) -> Path:
    """Build upload artifacts and release each raw archive after extraction."""
    archives_dir = course_dir / "archives"
    extracted_dir = course_dir / "extracted"
    upload_dir = course_dir / "upload"
    marker = course_dir / PROCESSING_MARKER
    if marker.is_file() and upload_dir.is_dir() and any(upload_dir.iterdir()):
        shutil.rmtree(archives_dir, ignore_errors=True)
        shutil.rmtree(extracted_dir, ignore_errors=True)
        return upload_dir
    if not (
        (archives_dir.is_dir() and any(archives_dir.iterdir()))
        or (extracted_dir.is_dir() and any(extracted_dir.iterdir()))
    ):
        raise RuntimeError(f"No downloaded or extracted files found in {course_dir}")

    # Preserve extracted output across retries because successful source
    # archives are deleted immediately to keep disk usage bounded.
    shutil.rmtree(upload_dir, ignore_errors=True)
    marker.unlink(missing_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True)

    raw_files = [path for path in archives_dir.iterdir() if path.is_file()]
    archive_headers = [path for path in raw_files if is_archive_header(path)]
    for archive in archive_headers:
        log(f"Extracting {archive.name}")
        ok, error = _extract(archive, extracted_dir)
        if not ok:
            raise RuntimeError(f"Cannot extract {archive.name}: {error}")

        family = _archive_family(archive, raw_files)
        released = 0
        for member in family:
            if member.exists():
                released += member.stat().st_size
                member.unlink()
        log(
            f"Released {released / 1024**3:.2f} GB after extracting "
            f"{archive.name}"
        )

    remaining = [path for path in archives_dir.iterdir() if path.is_file()]
    archive_members = {
        path for path in remaining
        if is_archive_header(path)
        or re.search(r"(?:\.z\d+|\.7z\.\d+|\.part\d+\.rar)$", path.name, re.I)
    }
    for source in remaining:
        if source in archive_members:
            continue
        destination = _unique_destination(extracted_dir, source)
        if not destination.exists():
            shutil.move(source, destination)
        else:
            source.unlink()

    all_files = [path for path in extracted_dir.rglob("*") if path.is_file()]
    videos = [path for path in all_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    documents = [path for path in all_files if path not in videos]
    if not all_files:
        raise RuntimeError("Processing produced no uploadable files")

    for video in videos:
        destination = _unique_destination(upload_dir, video)
        if not destination.exists():
            _link_or_copy(video, destination)

    if documents:
        materials = upload_dir / "Class_Materials.zip"
        with zipfile.ZipFile(materials, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as handle:
            for document in documents:
                handle.write(document, document.relative_to(extracted_dir))

    if not any(upload_dir.iterdir()):
        raise RuntimeError("Upload directory is empty")

    marker.write_text("complete\n", encoding="utf-8")
    shutil.rmtree(archives_dir, ignore_errors=True)
    shutil.rmtree(extracted_dir, ignore_errors=True)
    return upload_dir
