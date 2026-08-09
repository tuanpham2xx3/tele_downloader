import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_media_downloader.drive_uploader import refresh_upload_mtimes, upload_job
from telegram_media_downloader.upload_queue import UploadJob


class DriveUploaderTests(unittest.TestCase):
    def make_job(self, root: Path) -> UploadJob:
        upload = root / "upload"
        upload.mkdir()
        (upload / "video.mp4").write_bytes(b"video")
        return UploadJob(1, "Course", "Course", "acc1", root, "gdrive:",
                         "READY_UPLOAD", 0, 0, "")

    @patch("telegram_media_downloader.drive_uploader.mark_remote_complete", return_value=True)
    @patch("telegram_media_downloader.drive_uploader._verify", return_value=(True, ""))
    @patch("telegram_media_downloader.drive_uploader.run_rclone_with_watchdog", return_value=True)
    def test_upload_uses_configured_chunk_and_marks_only_after_verify(self, run_rclone, verify, marker):
        with tempfile.TemporaryDirectory() as temporary:
            ok, error = upload_job(self.make_job(Path(temporary)))
        self.assertTrue(ok, error)
        command = run_rclone.call_args.args[0]
        self.assertIn("128M", command)
        verify.assert_called_once()
        marker.assert_called_once()

    @patch("telegram_media_downloader.drive_uploader.time.time", return_value=2_000_000_000)
    def test_refresh_upload_mtimes_replaces_old_file_and_directory_dates(self, _time):
        with tempfile.TemporaryDirectory() as temporary:
            upload = Path(temporary) / "upload"
            nested = upload / "section"
            nested.mkdir(parents=True)
            video = nested / "video.mp4"
            video.write_bytes(b"video")

            refresh_upload_mtimes(upload)

            self.assertEqual(video.stat().st_mtime, 2_000_000_000)
            self.assertEqual(nested.stat().st_mtime, 2_000_000_000)
            self.assertEqual(upload.stat().st_mtime, 2_000_000_000)

    @patch("telegram_media_downloader.drive_uploader.mark_remote_complete")
    @patch("telegram_media_downloader.drive_uploader._verify", return_value=(False, "mismatch"))
    @patch("telegram_media_downloader.drive_uploader.run_rclone_with_watchdog", return_value=True)
    def test_failed_verify_does_not_mark_complete(self, _run_rclone, _verify, marker):
        with tempfile.TemporaryDirectory() as temporary:
            ok, error = upload_job(self.make_job(Path(temporary)))
        self.assertFalse(ok)
        self.assertIn("mismatch", error)
        marker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
