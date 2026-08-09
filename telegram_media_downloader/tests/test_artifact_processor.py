import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from telegram_media_downloader.artifact_processor import (
    PROCESSING_MARKER,
    _archive_family,
    _choose_extraction_work_dir,
    prepare_course,
)


class ArtifactProcessorTests(unittest.TestCase):
    def test_releases_raw_and_builds_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            course = Path(temporary) / "course"
            archives = course / "archives"
            archives.mkdir(parents=True)
            source_zip = archives / "lesson.zip"
            with zipfile.ZipFile(source_zip, "w") as handle:
                handle.writestr("lesson/video.mp4", b"video")
                handle.writestr("lesson/notes.pdf", b"notes")
            upload = prepare_course(course, lambda _: None)
            self.assertFalse(source_zip.exists())
            self.assertFalse(archives.exists())
            self.assertFalse((course / "extracted").exists())
            self.assertTrue((course / PROCESSING_MARKER).exists())
            self.assertTrue((upload / "video.mp4").exists())
            with zipfile.ZipFile(upload / "Class_Materials.zip") as handle:
                self.assertIn("lesson/notes.pdf", handle.namelist())

            # A restart after processing must reuse the complete upload tree.
            self.assertEqual(prepare_course(course, lambda _: None), upload)

    def test_zip_family_includes_split_volumes(self):
        root = Path("course")
        files = [root / "lesson.z01", root / "lesson.z02", root / "lesson.zip"]
        self.assertEqual(set(_archive_family(files[-1], files)), set(files))

    def test_resume_preserves_existing_upload_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            course = Path(temporary) / "course"
            archives = course / "archives"
            upload = course / "upload"
            archives.mkdir(parents=True)
            upload.mkdir()
            (upload / "already.mp4").write_bytes(b"already")
            with zipfile.ZipFile(archives / "next.zip", "w") as handle:
                handle.writestr("next.mp4", b"next")

            result = prepare_course(course, lambda _: None)

            self.assertTrue((result / "already.mp4").is_file())
            self.assertTrue((result / "next.mp4").is_file())

    @patch("telegram_media_downloader.artifact_processor.RAM_SCRATCH_LIMIT", 4 * 1024**3)
    @patch("telegram_media_downloader.artifact_processor.shutil.disk_usage")
    def test_small_course_uses_bounded_ram_scratch(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=4 * 1024**3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            course = root / "course"
            archives = course / "archives"
            scratch = root / "ram"
            archives.mkdir(parents=True)
            scratch.mkdir()
            (archives / "lesson.zip").write_bytes(b"x" * 1024)
            with patch("telegram_media_downloader.artifact_processor.RAM_SCRATCH_ROOT", scratch):
                extracted, using_ram = _choose_extraction_work_dir(
                    course, archives / "lesson.zip", [archives / "lesson.zip"]
                )
            self.assertTrue(using_ram)
            self.assertTrue(str(extracted).startswith(str(scratch)))

    @patch("telegram_media_downloader.artifact_processor.RAM_SCRATCH_LIMIT", 4 * 1024**3)
    @patch("telegram_media_downloader.artifact_processor.shutil.disk_usage")
    def test_prepare_streams_each_archive_through_ram(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=4 * 1024**3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            course = root / "course"
            archives = course / "archives"
            scratch = root / "ram"
            archives.mkdir(parents=True)
            scratch.mkdir()
            with zipfile.ZipFile(archives / "lesson.zip", "w") as handle:
                handle.writestr("lesson/video.mp4", b"video")
            logs = []
            with patch("telegram_media_downloader.artifact_processor.RAM_SCRATCH_ROOT", scratch):
                upload = prepare_course(course, logs.append)
            self.assertTrue((upload / "video.mp4").is_file())
            self.assertTrue(any("via RAM scratch" in line for line in logs))
            self.assertFalse(any((scratch / "extract").iterdir()))


if __name__ == "__main__":
    unittest.main()
