import tempfile
import unittest
import zipfile
from pathlib import Path

from telegram_media_downloader.artifact_processor import (
    PROCESSING_MARKER,
    _archive_family,
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


if __name__ == "__main__":
    unittest.main()
