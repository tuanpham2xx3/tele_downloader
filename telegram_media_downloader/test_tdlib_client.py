import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock
from pathlib import Path
from unittest.mock import patch

try:
    from .tdlib_client import TdlibClient, TdlibError, load_account_id, parse_message
except ImportError:
    from tdlib_client import TdlibClient, TdlibError, load_account_id, parse_message


class ParseMessageTests(unittest.TestCase):
    def test_document_message(self):
        message = parse_message(
            {
                "id": 123,
                "chatId": -1001,
                "date": 10,
                "content": {
                    "document": {
                        "fileName": "pack.zip.001",
                        "mimeType": "application/octet-stream",
                        "document": {
                            "id": 44,
                            "size": 1024,
                            "remote": {"uniqueId": "unique"},
                        },
                    },
                    "caption": {"text": "caption"},
                },
            }
        )
        self.assertEqual(message.text, "caption")
        self.assertEqual(message.file.name, "pack.zip.001")
        self.assertEqual(message.file.id, 44)
        self.assertEqual(message.file.size, 1024)
        self.assertIsNotNone(message.media)

    def test_video_message(self):
        message = parse_message(
            {
                "id": 124,
                "chatId": 2,
                "date": 11,
                "content": {
                    "video": {
                        "fileName": "lesson.mp4",
                        "mimeType": "video/mp4",
                        "video": {"id": 45, "expectedSize": 2048, "remote": {}},
                    },
                    "caption": {"text": "lesson"},
                },
            }
        )
        self.assertEqual(message.file.name, "lesson.mp4")
        self.assertEqual(message.file.size, 2048)
        self.assertEqual(message.text, "lesson")

    def test_photo_uses_largest_size(self):
        message = parse_message(
            {
                "id": 125,
                "chatId": 3,
                "date": 12,
                "content": {
                    "photo": {
                        "sizes": [
                            {"photo": {"id": 1, "size": 10, "remote": {}}},
                            {"photo": {"id": 2, "size": 20, "remote": {}}},
                        ]
                    }
                },
            }
        )
        self.assertEqual(message.file.id, 2)
        self.assertEqual(message.file.name, "photo_125.jpg")


class AccountRegistryTests(unittest.TestCase):
    def test_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"TDLIB_ACCOUNT_ACC2": "222"}, clear=False
        ):
            self.assertEqual(load_account_id("acc2", Path(directory)), 222)

    def test_registry_object_and_scalar(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"TDLIB_ACCOUNT_REGISTRY": str(Path(directory) / "accounts.json")},
            clear=False,
        ):
            path = Path(os.environ["TDLIB_ACCOUNT_REGISTRY"])
            path.write_text(
                json.dumps({"acc1": {"id": 111}, "acc3": 333}), encoding="utf-8"
            )
            self.assertEqual(load_account_id("acc1", Path(directory)), 111)
            self.assertEqual(load_account_id("acc3", Path(directory)), 333)

    def test_missing_account_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"TDLIB_ACCOUNT_REGISTRY": str(Path(directory) / "missing.json")},
            clear=False,
        ):
            with self.assertRaisesRegex(TdlibError, "TDLIB_ACCOUNT_ACC2"):
                load_account_id("acc2", Path(directory))


class HistoryPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_page_does_not_end_remote_history(self):
        client = TdlibClient(1)
        pages = [
            {"messages": [self.message(30), self.message(20)]},
            {"messages": [self.message(10)]},
            {"messages": []},
        ]
        client.call = AsyncMock(side_effect=pages)
        history = await client.get_history(-1001, limit=10)
        self.assertEqual([message.id for message in history], [10, 20, 30])
        self.assertEqual(client.call.await_count, 3)

    @staticmethod
    def message(message_id):
        return {
            "id": message_id,
            "chatId": -1001,
            "date": message_id,
            "content": {"text": {"text": str(message_id)}},
        }


if __name__ == "__main__":
    unittest.main()
