import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock
from pathlib import Path
from unittest.mock import patch

import requests

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


class AdminAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_401_logs_in_retries_and_adds_csrf_header(self):
        client = TdlibClient(1, admin_username="pipeline", admin_password="secret")
        unauthorized = requests.Response()
        unauthorized.status_code = 401
        unauthorized._content = b'{"error":"AUTHENTICATION_REQUIRED"}'
        login = requests.Response()
        login.status_code = 200
        login._content = b'{}'
        success = requests.Response()
        success.status_code = 200
        success._content = b'{}'

        def request(method, url, **kwargs):
            if url.endswith("/auth/login"):
                client._http.cookies.set("tf_admin", "admin-token")
                client._http.cookies.set("tf_csrf", "csrf-token")
                self.assertNotIn("secret", repr(kwargs.get("headers", {})))
                return login
            if not client._http.cookies.get("tf_admin"):
                return unauthorized
            self.assertEqual(kwargs["headers"]["X-CSRF-Token"], "csrf-token")
            return success

        with patch.object(client._http, "request", side_effect=request) as mocked:
            response = await client._request("POST", "/telegrams/change")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked.call_count, 3)


class DownloadMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_file_download_cancels_then_resumes(self):
        client = TdlibClient(1)
        message = parse_message(
            {
                "id": 148,
                "chatId": -1001,
                "date": 10,
                "content": {
                    "document": {
                        "fileName": "restart.zip",
                        "document": {"id": 48, "size": 1024, "remote": {}},
                    }
                },
            }
        )
        client._request = AsyncMock()
        client._file_updates[48] = {"id": 48}

        with patch("asyncio.sleep", new=AsyncMock()):
            await client.restart_file_download(message)

        self.assertNotIn(48, client._file_updates)
        self.assertEqual(
            client._request.await_args_list[0].args,
            ("POST", "/1/file/cancel-download"),
        )
        self.assertEqual(
            client._request.await_args_list[1].args,
            ("POST", "/1/file/start-download"),
        )
        self.assertEqual(
            client._request.await_args_list[2].args,
            ("POST", "/1/file/toggle-pause-download"),
        )

    async def test_reuses_complete_destination_without_touching_tdlib(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "already-complete.zip"
            destination.write_bytes(b"complete-on-nvme")
            message = parse_message(
                {
                    "id": 122,
                    "chatId": -1001,
                    "date": 10,
                    "content": {
                        "document": {
                            "fileName": destination.name,
                            "document": {
                                "id": 43,
                                "size": destination.stat().st_size,
                                "remote": {},
                            },
                        }
                    },
                }
            )
            client = TdlibClient(1)
            client.get_file = AsyncMock()
            client._request = AsyncMock()
            client.remove_file = AsyncMock()

            result = await client.download_message(message, destination, timeout=10)

            self.assertEqual(result.read_bytes(), b"complete-on-nvme")
            client.get_file.assert_not_awaited()
            client._request.assert_not_awaited()
            client.remove_file.assert_not_awaited()

    async def test_reuses_completed_tdlib_cache_without_starting_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "cached.zip"
            destination = root / "output" / "cached.zip"
            cached.write_bytes(b"cached-content")
            message = parse_message(
                {
                    "id": 123,
                    "chatId": -1001,
                    "date": 10,
                    "content": {
                        "document": {
                            "fileName": "cached.zip",
                            "document": {
                                "id": 44,
                                "size": cached.stat().st_size,
                                "remote": {},
                            },
                        }
                    },
                }
            )
            completed = {
                "id": 44,
                "size": cached.stat().st_size,
                "local": {
                    "isDownloadingCompleted": True,
                    "downloadedSize": cached.stat().st_size,
                    "path": str(cached),
                },
            }
            client = TdlibClient(1)
            client.get_file = AsyncMock(return_value=completed)
            client._request = AsyncMock()
            client.remove_file = AsyncMock()

            result = await client.download_message(message, destination, timeout=10)

            self.assertEqual(result.read_bytes(), b"cached-content")
            client._request.assert_not_awaited()
            client.remove_file.assert_awaited_once_with(44)

    async def test_resumes_active_tdlib_download_without_start_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "active.zip"
            destination = root / "output" / "active.zip"
            cached.write_bytes(b"resumed-content")
            message = parse_message(
                {
                    "id": 124,
                    "chatId": -1001,
                    "date": 10,
                    "content": {
                        "document": {
                            "fileName": "active.zip",
                            "document": {
                                "id": 45,
                                "size": cached.stat().st_size,
                                "remote": {},
                            },
                        }
                    },
                }
            )
            active = {
                "id": 45,
                "size": cached.stat().st_size,
                "local": {
                    "isDownloadingActive": True,
                    "isDownloadingCompleted": False,
                    "downloadedSize": 1,
                    "path": "",
                },
            }
            completed = {
                "id": 45,
                "size": cached.stat().st_size,
                "local": {
                    "isDownloadingActive": False,
                    "isDownloadingCompleted": True,
                    "downloadedSize": cached.stat().st_size,
                    "path": str(cached),
                },
            }
            client = TdlibClient(1)
            client.get_file = AsyncMock(side_effect=[active, completed, completed])
            client._request = AsyncMock()
            client.remove_file = AsyncMock()

            result = await client.download_message(message, destination, timeout=10)

            self.assertEqual(result.read_bytes(), b"resumed-content")
            self.assertEqual(client._request.await_count, 3)
            client.remove_file.assert_awaited_once_with(45)

    async def test_handles_download_completing_during_start_race(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "raced.zip"
            destination = root / "output" / "raced.zip"
            cached.write_bytes(b"race-content")
            message = parse_message(
                {
                    "id": 125,
                    "chatId": -1001,
                    "date": 10,
                    "content": {
                        "document": {
                            "fileName": "raced.zip",
                            "document": {
                                "id": 46,
                                "size": cached.stat().st_size,
                                "remote": {},
                            },
                        }
                    },
                }
            )
            pending = {
                "id": 46,
                "size": cached.stat().st_size,
                "local": {
                    "isDownloadingActive": False,
                    "isDownloadingCompleted": False,
                    "downloadedSize": 0,
                    "path": "",
                },
            }
            completed = {
                "id": 46,
                "size": cached.stat().st_size,
                "local": {
                    "isDownloadingActive": False,
                    "isDownloadingCompleted": True,
                    "downloadedSize": cached.stat().st_size,
                    "path": str(cached),
                },
            }
            client = TdlibClient(1)
            client.get_file = AsyncMock(side_effect=[pending, completed])
            client._request = AsyncMock(
                side_effect=TdlibError(
                    'POST /1/file/start-download failed (500): '
                    '{"error":"File is already downloaded successfully"}'
                )
            )
            client.remove_file = AsyncMock()

            result = await client.download_message(message, destination, timeout=10)

            self.assertEqual(result.read_bytes(), b"race-content")
            client._request.assert_awaited_once()
            client.remove_file.assert_awaited_once_with(46)

    async def test_cache_cleanup_failure_keeps_completed_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cached = root / "cleanup.zip"
            destination = root / "output" / "cleanup.zip"
            cached.write_bytes(b"keep-destination")
            message = parse_message(
                {
                    "id": 126,
                    "chatId": -1001,
                    "date": 10,
                    "content": {
                        "document": {
                            "fileName": "cleanup.zip",
                            "document": {
                                "id": 47,
                                "size": cached.stat().st_size,
                                "remote": {},
                            },
                        }
                    },
                }
            )
            completed = {
                "id": 47,
                "size": cached.stat().st_size,
                "local": {
                    "isDownloadingCompleted": True,
                    "downloadedSize": cached.stat().st_size,
                    "path": str(cached),
                },
            }
            client = TdlibClient(1)
            client.get_file = AsyncMock(return_value=completed)
            client._request = AsyncMock()
            client.remove_file = AsyncMock(
                side_effect=TdlibError("temporary cache cleanup failure")
            )

            result = await client.download_message(message, destination, timeout=10)

            self.assertEqual(result.read_bytes(), b"keep-destination")
            client.remove_file.assert_awaited_once_with(47)


if __name__ == "__main__":
    unittest.main()
