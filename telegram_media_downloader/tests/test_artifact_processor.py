import tempfile
import unittest
import zipfile
from pathlib import Path

from telegram_media_downloader.artifact_processor import prepare_course


class ArtifactProcessorTests(unittest.TestCase):
    def test_preserves_raw_and_builds_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            course = Path(temporary) / "course"
            archives = course / "archives"
            archives.mkdir(parents=True)
            source_zip = archives / "lesson.zip"
            with zipfile.ZipFile(source_zip, "w") as handle:
                handle.writestr("lesson/video.mp4", b"video")
                handle.writestr("lesson/notes.pdf", b"notes")
            upload = prepare_course(course, lambda _: None)
            self.assertTrue(source_zip.exists())
            self.assertTrue((upload / "video.mp4").exists())
            with zipfile.ZipFile(upload / "Class_Materials.zip") as handle:
                self.assertIn("lesson/notes.pdf", handle.namelist())


if __name__ == "__main__":
    unittest.main()
