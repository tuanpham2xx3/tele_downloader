import unittest
from unittest.mock import AsyncMock

from telegram_media_downloader.tdlib_client import TdlibClient, TdlibFile, TdlibMessage


class TdlibRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_clears_gateway_record_before_starting_again(self):
        client = TdlibClient(123)
        client._request = AsyncMock()
        message = TdlibMessage(
            id=456,
            chat_id=-789,
            date=0,
            text="",
            file=TdlibFile(id=42, size=100, name="file.zip"),
            raw={},
        )

        await client.restart_file_download(message)

        first, second, third = client._request.await_args_list
        self.assertEqual(first.args[:2], ("POST", "/123/file/cancel-download"))
        self.assertEqual(first.kwargs["json_body"], {"fileId": 42})
        self.assertEqual(second.args[:2], ("POST", "/123/file/start-download"))
        self.assertEqual(
            second.kwargs["json_body"],
            {"chatId": -789, "messageId": 456, "fileId": 42},
        )
        self.assertEqual(
            third.args[:2], ("POST", "/123/file/toggle-pause-download")
        )
        self.assertEqual(
            third.kwargs["json_body"], {"fileId": 42, "isPaused": False}
        )


if __name__ == "__main__":
    unittest.main()
