import unittest
from unittest.mock import patch

from telegram_media_downloader.rclone_watchdog import (
    parse_transferred_bytes,
    remote_folder_exists,
    remote_has_completion_marker,
)


class ParseTransferredBytesTests(unittest.TestCase):
    def test_parses_binary_units(self):
        self.assertEqual(
            parse_transferred_bytes("Transferred: 2.997 GiB / 25.628 GiB, 12%"),
            int(2.997 * 1024**3),
        )

    def test_parses_bytes(self):
        self.assertEqual(parse_transferred_bytes("Transferred: 933 B / 4 KiB"), 933)

    def test_parses_one_line_date_stats(self):
        line = (
            "2026/08/09 11:10:18 NOTICE: 2026/08/09 11:10:18 - "
            "1.248 GiB / 1.519 GiB, 82%, 19.028 MiB/s"
        )
        self.assertEqual(parse_transferred_bytes(line), int(1.248 * 1024**3))

    def test_ignores_non_stats_output(self):
        self.assertIsNone(parse_transferred_bytes("Checks: 14 / 14, 100%"))

    @patch("telegram_media_downloader.rclone_watchdog.subprocess.run")
    def test_marker_timeout_is_incomplete_not_fatal(self, run):
        import subprocess

        run.side_effect = subprocess.TimeoutExpired(["rclone", "lsf"], 30)
        self.assertFalse(remote_has_completion_marker("gdrive:/course"))

    @patch("telegram_media_downloader.rclone_watchdog.subprocess.run")
    def test_existing_remote_folder_is_complete_even_without_marker(self, run):
        import subprocess

        run.return_value = subprocess.CompletedProcess(
            ["rclone", "lsf"], returncode=0, stdout="", stderr=""
        )
        self.assertTrue(remote_folder_exists("gdrive:/course"))

    @patch("telegram_media_downloader.rclone_watchdog.subprocess.run")
    def test_missing_remote_folder_is_not_complete(self, run):
        import subprocess

        run.return_value = subprocess.CompletedProcess(
            ["rclone", "lsf"], returncode=3, stdout="", stderr="not found"
        )
        self.assertFalse(remote_folder_exists("gdrive:/course"))


if __name__ == "__main__":
    unittest.main()
