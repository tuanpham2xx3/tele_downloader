import unittest

from telegram_media_downloader.rclone_watchdog import parse_transferred_bytes


class ParseTransferredBytesTests(unittest.TestCase):
    def test_parses_binary_units(self):
        self.assertEqual(
            parse_transferred_bytes("Transferred: 2.997 GiB / 25.628 GiB, 12%"),
            int(2.997 * 1024**3),
        )

    def test_parses_bytes(self):
        self.assertEqual(parse_transferred_bytes("Transferred: 933 B / 4 KiB"), 933)

    def test_ignores_non_stats_output(self):
        self.assertIsNone(parse_transferred_bytes("Checks: 14 / 14, 100%"))


if __name__ == "__main__":
    unittest.main()
