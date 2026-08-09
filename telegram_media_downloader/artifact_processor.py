"""Turn downloaded Telegram files into upload-ready course artifacts."""

from __future__ import annotations

import os
import hashlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
ARCHIVE_HEADERS = (".zip", ".rar", ".7z")
PROCESSING_MARKER = ".processing-complete"
RAM_SCRATCH_ROOT = Path(os.environ.get("GETURL_RAM_SCRATCH_ROOT", "/mnt/geturl-ram"))
RAM_SCRATCH_LIMIT = int(float(os.environ.get("GETURL_RAM_SCRATCH_GB", "4")) * 1024**3)
RAM_SCRATCH_RESERVE = 256 * 1024**2


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


def _choose_extraction_work_dir(
    course_dir: Path, archive: Path, family: list[Path]
) -> tuple[Path, bool]:
    """Choose bounded tmpfs per archive, allowing large courses to stream."""
    key = hashlib.sha256(
        f"{course_dir.resolve()}::{archive.name}".encode("utf-8")
    ).hexdigest()[:16]
    disk_dir = course_dir / "extract_work" / key
    if not RAM_SCRATCH_ROOT.is_dir():
        return disk_dir, False
    archive_bytes = sum(path.stat().st_size for path in family if path.is_file())
    estimated_working_set = max(archive_bytes * 2, RAM_SCRATCH_RESERVE)
    free = shutil.disk_usage(RAM_SCRATCH_ROOT).free
    if estimated_working_set > RAM_SCRATCH_LIMIT or estimated_working_set + RAM_SCRATCH_RESERVE > free:
        return disk_dir, False
    scratch_dir = RAM_SCRATCH_ROOT / "extract" / key
    return scratch_dir, True


def _move_unique(source: Path, destination_dir: Path) -> None:
    destination = _unique_destination(destination_dir, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        source.unlink(missing_ok=True)
    else:
        shutil.move(source, destination)


def _ingest_tree(source_root: Path, upload_dir: Path, materials_dir: Path) -> None:
    """Move extracted output into its durable upload/materials staging trees."""
    for source in [path for path in source_root.rglob("*") if path.is_file()]:
        if source.suffix.lower() in VIDEO_EXTENSIONS:
            _move_unique(source, upload_dir)
            continue
        relative = source.relative_to(source_root)
        destination = materials_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size != source.stat().st_size:
            destination = _unique_destination(destination.parent, source)
        if destination.exists():
            source.unlink(missing_ok=True)
        else:
            shutil.move(source, destination)


def prepare_course(course_dir: Path, log: Callable[[str], None] = print) -> Path:
    """Build upload artifacts and release each raw archive after extraction."""
    archives_dir = course_dir / "archives"
    extracted_dir = course_dir / "extracted"
    extract_work_dir = course_dir / "extract_work"
    materials_dir = course_dir / "materials_staging"
    upload_dir = course_dir / "upload"
    marker = course_dir / PROCESSING_MARKER
    if marker.is_file() and upload_dir.is_dir() and any(upload_dir.iterdir()):
        shutil.rmtree(archives_dir, ignore_errors=True)
        shutil.rmtree(extracted_dir, ignore_errors=True)
        shutil.rmtree(extract_work_dir, ignore_errors=True)
        shutil.rmtree(materials_dir, ignore_errors=True)
        return upload_dir
    if not (
        (archives_dir.is_dir() and any(archives_dir.iterdir()))
        or (extracted_dir.is_dir() and any(extracted_dir.iterdir()))
        or (materials_dir.is_dir() and any(materials_dir.iterdir()))
        or (upload_dir.is_dir() and any(upload_dir.iterdir()))
    ):
        raise RuntimeError(f"No downloaded or extracted files found in {course_dir}")

    # Durable upload/material staging is preserved across retries because each
    # successful archive family is deleted immediately after being ingested.
    marker.unlink(missing_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    materials_dir.mkdir(parents=True, exist_ok=True)

    # Migrate output left by the previous whole-course extraction strategy.
    if extracted_dir.is_dir() and any(extracted_dir.iterdir()):
        _ingest_tree(extracted_dir, upload_dir, materials_dir)
    shutil.rmtree(extracted_dir, ignore_errors=True)

    raw_files = [path for path in archives_dir.iterdir() if path.is_file()]
    archive_headers = [path for path in raw_files if is_archive_header(path)]
    for archive in archive_headers:
        family = _archive_family(archive, raw_files)
        work_dir, using_ram = _choose_extraction_work_dir(course_dir, archive, family)
        shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        location = "RAM" if using_ram else "disk"
        log(f"Extracting {archive.name} via {location} scratch")
        ok, error = _extract(archive, work_dir)
        if not ok and using_ram:
            log(f"RAM scratch failed for {archive.name}; retrying on disk")
            shutil.rmtree(work_dir, ignore_errors=True)
            work_dir = course_dir / "extract_work" / work_dir.name
            shutil.rmtree(work_dir, ignore_errors=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            ok, error = _extract(archive, work_dir)
        if not ok:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise RuntimeError(f"Cannot extract {archive.name}: {error}")

        _ingest_tree(work_dir, upload_dir, materials_dir)
        shutil.rmtree(work_dir, ignore_errors=True)
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
        if source.suffix.lower() in VIDEO_EXTENSIONS:
            _move_unique(source, upload_dir)
        else:
            destination = materials_dir / source.name
            if destination.exists() and destination.stat().st_size != source.stat().st_size:
                destination = _unique_destination(materials_dir, source)
            if destination.exists():
                source.unlink(missing_ok=True)
            else:
                shutil.move(source, destination)

    documents = [path for path in materials_dir.rglob("*") if path.is_file()]
    if documents:
        materials = upload_dir / "Class_Materials.zip"
        materials.unlink(missing_ok=True)
        with zipfile.ZipFile(materials, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as handle:
            for document in documents:
                handle.write(document, document.relative_to(materials_dir))

    if not any(upload_dir.iterdir()):
        raise RuntimeError("Upload directory is empty")

    marker.write_text("complete\n", encoding="utf-8")
    shutil.rmtree(archives_dir, ignore_errors=True)
    shutil.rmtree(extracted_dir, ignore_errors=True)
    shutil.rmtree(extract_work_dir, ignore_errors=True)
    shutil.rmtree(materials_dir, ignore_errors=True)
    return upload_dir
