"""Async client for the local telegram-files TDLib gateway.

The gateway exposes commands over HTTP and delivers generic TDLib method
results over a session-bound WebSocket.  This module hides that transport and
provides the small, cross-platform interface used by the course pipelines.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests
import websockets


TYPE_ERROR = -1
TYPE_METHOD_RESULT = 2
TYPE_FILE_UPDATE = 3

INPUT_MESSAGE_TEXT = -212805484
FORMATTED_TEXT = -252624564


class TdlibError(RuntimeError):
    """A request was rejected by telegram-files or TDLib."""


@dataclass(frozen=True)
class TdlibFile:
    id: int
    size: int
    name: str
    mime_type: str = ""
    unique_id: str = ""


@dataclass(frozen=True)
class TdlibMessage:
    id: int
    chat_id: int
    date: int
    text: str
    file: Optional[TdlibFile]
    raw: Dict[str, Any]

    @property
    def media(self) -> Optional[Dict[str, Any]]:
        return self.raw.get("content") if self.file else None


def _nested_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
        if isinstance(text, dict):
            return _nested_text(text)
    return ""


def _file_size(file_obj: Dict[str, Any]) -> int:
    return int(file_obj.get("size") or file_obj.get("expectedSize") or 0)


def parse_message(raw: Dict[str, Any]) -> TdlibMessage:
    """Convert a raw TDLib Message object into the pipeline representation."""

    content = raw.get("content") or {}
    text = _nested_text(content.get("text")) or _nested_text(content.get("caption"))
    file_info: Optional[TdlibFile] = None

    candidates = (
        ("document", "document"),
        ("video", "video"),
        ("audio", "audio"),
        ("animation", "animation"),
        ("voiceNote", "voice"),
        ("videoNote", "video"),
    )
    for metadata_key, file_key in candidates:
        metadata = content.get(metadata_key)
        if not isinstance(metadata, dict):
            continue
        file_obj = metadata.get(file_key)
        if not isinstance(file_obj, dict):
            continue
        remote = file_obj.get("remote") or {}
        file_info = TdlibFile(
            id=int(file_obj.get("id") or 0),
            size=_file_size(file_obj),
            name=str(metadata.get("fileName") or f"telegram_{raw.get('id', 0)}"),
            mime_type=str(metadata.get("mimeType") or ""),
            unique_id=str(remote.get("uniqueId") or ""),
        )
        break

    if file_info is None and isinstance(content.get("photo"), dict):
        sizes = content["photo"].get("sizes") or []
        if sizes:
            largest = max(
                (item for item in sizes if isinstance(item, dict)),
                key=lambda item: _file_size(item.get("photo") or {}),
                default=None,
            )
            if largest:
                file_obj = largest.get("photo") or {}
                remote = file_obj.get("remote") or {}
                file_info = TdlibFile(
                    id=int(file_obj.get("id") or 0),
                    size=_file_size(file_obj),
                    name=f"photo_{raw.get('id', 0)}.jpg",
                    mime_type="image/jpeg",
                    unique_id=str(remote.get("uniqueId") or ""),
                )

    return TdlibMessage(
        id=int(raw.get("id") or 0),
        chat_id=int(raw.get("chatId") or 0),
        date=int(raw.get("date") or 0),
        text=text,
        file=file_info,
        raw=raw,
    )


def load_account_id(role: str, project_root: Path) -> int:
    """Load an authorized TDLib user id from env or the ignored registry."""

    env_name = f"TDLIB_ACCOUNT_{role.upper()}"
    env_value = os.environ.get(env_name)
    if env_value:
        return int(env_value)

    registry_path = Path(
        os.environ.get(
            "TDLIB_ACCOUNT_REGISTRY",
            str(project_root / ".runtime" / "tdlib-accounts.json"),
        )
    )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        value = registry.get(role.lower())
        if isinstance(value, dict):
            value = value.get("id")
        if value:
            return int(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    raise TdlibError(
        f"TDLib account for {role} is not configured. Set {env_name} or "
        f"add it to {registry_path}."
    )


class TdlibClient:
    """Session-bound async facade over telegram-files 0.1.x."""

    def __init__(
        self,
        account_id: int,
        base_url: str = "http://127.0.0.1:8080",
        request_timeout: float = 30.0,
    ) -> None:
        self.account_id = int(account_id)
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self._http = requests.Session()
        self._ws: Any = None
        self._receiver: Optional[asyncio.Task] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._early_results: Dict[str, tuple[int, Any]] = {}
        self._file_updates: Dict[int, Dict[str, Any]] = {}
        self._http_lock = asyncio.Lock()
        self._closed = False

    async def __aenter__(self) -> "TdlibClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        async with self._http_lock:
            response = await asyncio.to_thread(
                self._http.request,
                method,
                f"{self.base_url}{path}",
                json=json_body,
                timeout=self.request_timeout,
            )
        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            raise TdlibError(f"{method} {path} failed ({response.status_code}): {detail}")
        return response

    async def connect(self) -> None:
        if self._ws is not None and not self._closed:
            return
        self._closed = False
        await self._request("GET", "/")
        await self._request("POST", f"/telegrams/change?telegramId={self.account_id}")
        cookie = "; ".join(f"{item.name}={item.value}" for item in self._http.cookies)
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = f"{scheme}://{parsed.netloc}/ws?telegramId={self.account_id}"
        self._ws = await websockets.connect(
            ws_url,
            additional_headers={"Cookie": cookie},
            open_timeout=self.request_timeout,
            ping_interval=20,
            ping_timeout=20,
        )
        self._receiver = asyncio.create_task(
            self._receive_loop(), name=f"tdlib-ws-{self.account_id}"
        )

    async def close(self) -> None:
        self._closed = True
        if self._receiver:
            self._receiver.cancel()
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._receiver:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._receiver
        self._receiver = None
        self._ws = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(TdlibError("TDLib client closed"))
        self._pending.clear()
        await asyncio.to_thread(self._http.close)

    async def reconnect(self) -> None:
        await self.close()
        self._http = requests.Session()
        self._early_results.clear()
        await self.connect()

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                event = json.loads(raw)
                event_type = int(event.get("type") or 0)
                code = event.get("code")
                data = event.get("data")
                if event_type == TYPE_FILE_UPDATE and isinstance(data, dict):
                    file_obj = data.get("file") or data
                    if isinstance(file_obj, dict) and file_obj.get("id") is not None:
                        self._file_updates[int(file_obj["id"])] = file_obj
                if not code:
                    continue
                future = self._pending.pop(str(code), None)
                if future is None:
                    self._early_results[str(code)] = (event_type, data)
                    continue
                self._finish_future(future, event_type, data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                error = TdlibError(f"TDLib WebSocket disconnected: {exc}")
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                self._pending.clear()

    @staticmethod
    def _finish_future(future: asyncio.Future, event_type: int, data: Any) -> None:
        if future.done():
            return
        if event_type == TYPE_ERROR:
            message = data.get("message") if isinstance(data, dict) else str(data)
            future.set_exception(TdlibError(message or "Unknown TDLib error"))
        else:
            future.set_result(data)

    async def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        await self.connect()
        response = await self._request(
            "POST", f"/telegram/api/{method}", json_body=params or {}
        )
        code = str(response.json()["code"])
        early = self._early_results.pop(code, None)
        if early is not None:
            future = asyncio.get_running_loop().create_future()
            self._finish_future(future, early[0], early[1])
            return await future
        future = asyncio.get_running_loop().create_future()
        self._pending[code] = future
        try:
            return await asyncio.wait_for(
                future, timeout=timeout or self.request_timeout
            )
        finally:
            self._pending.pop(code, None)

    async def get_chats(self) -> List[Dict[str, Any]]:
        response = await self._request(
            "GET", f"/telegram/{self.account_id}/chats"
        )
        value = response.json()
        return value if isinstance(value, list) else [value]

    async def resolve_chat(self, value: str | int) -> int:
        text = str(value).strip()
        if text.lstrip("-").isdigit():
            return int(text)
        wanted = text.lstrip("@").casefold()
        if text.startswith("@"):
            chat = await self.call("SearchPublicChat", {"username": wanted})
            return int(chat["id"])
        for chat in await self.get_chats():
            if str(chat.get("name") or "").casefold() == wanted:
                return int(chat["id"])
        try:
            chat = await self.call("SearchPublicChat", {"username": wanted})
            return int(chat["id"])
        except TdlibError as exc:
            raise TdlibError(
                f"Chat not found for account {self.account_id}: {value}"
            ) from exc

    async def get_history(
        self,
        chat_id: int,
        limit: int = 3000,
        *,
        reverse: bool = True,
    ) -> List[TdlibMessage]:
        messages: Dict[int, TdlibMessage] = {}
        from_message_id = 0
        while len(messages) < limit:
            page_size = min(100, limit - len(messages))
            result = await self.call(
                "GetChatHistory",
                {
                    "chatId": int(chat_id),
                    "fromMessageId": int(from_message_id),
                    "offset": 0,
                    "limit": page_size,
                    "onlyLocal": False,
                },
            )
            raw_messages = (result or {}).get("messages") or []
            if not raw_messages:
                break
            for raw in raw_messages:
                message = parse_message(raw)
                messages[message.id] = message
            next_from = int(raw_messages[-1].get("id") or 0)
            if not next_from or next_from == from_message_id:
                break
            from_message_id = next_from
        ordered = sorted(messages.values(), key=lambda item: (item.date, item.id))
        return ordered if reverse else list(reversed(ordered))

    async def get_message(self, chat_id: int, message_id: int) -> TdlibMessage:
        raw = await self.call(
            "GetMessage", {"chatId": int(chat_id), "messageId": int(message_id)}
        )
        return parse_message(raw)

    async def iter_new_messages(
        self,
        chat_id: int,
        *,
        after_message_id: int = 0,
        poll_interval: float = 2.0,
    ) -> AsyncIterator[TdlibMessage]:
        cursor = int(after_message_id)
        while not self._closed:
            recent = await self.get_history(chat_id, limit=100, reverse=True)
            fresh = [message for message in recent if message.id > cursor]
            for message in fresh:
                cursor = max(cursor, message.id)
                yield message
            await asyncio.sleep(poll_interval)

    async def send_text(self, chat_id: int, text: str) -> TdlibMessage:
        result = await self.call(
            "SendMessage",
            {
                "chatId": int(chat_id),
                "messageThreadId": 0,
                "replyTo": None,
                "options": None,
                "replyMarkup": None,
                "inputMessageContent": {
                    "@type": INPUT_MESSAGE_TEXT,
                    "text": {
                        "@type": FORMATTED_TEXT,
                        "text": text,
                        "entities": [],
                    },
                    "linkPreviewOptions": None,
                    "clearDraft": False,
                },
            },
        )
        return parse_message(result)

    async def forward_messages(
        self,
        destination_chat_id: int,
        source_chat_id: int,
        message_ids: Iterable[int],
    ) -> List[TdlibMessage]:
        ids = [int(value) for value in message_ids]
        if not ids:
            return []
        result = await self.call(
            "ForwardMessages",
            {
                "chatId": int(destination_chat_id),
                "messageThreadId": 0,
                "fromChatId": int(source_chat_id),
                "messageIds": ids,
                "options": None,
                "sendCopy": False,
                "removeCaption": False,
            },
        )
        return [parse_message(item) for item in (result or {}).get("messages") or []]

    async def get_file(self, file_id: int) -> Dict[str, Any]:
        update = self._file_updates.get(int(file_id))
        if update:
            local = update.get("local") or {}
            if local.get("isDownloadingCompleted"):
                return update
        return await self.call("GetFile", {"fileId": int(file_id)})

    async def remove_file(self, file_id: int) -> None:
        await self._request(
            "POST",
            f"/{self.account_id}/file/remove",
            json_body={"fileId": int(file_id)},
        )
        self._file_updates.pop(int(file_id), None)

    async def download_message(
        self,
        message: TdlibMessage,
        destination: Path,
        *,
        timeout: float,
        stall_timeout: float = 300.0,
        progress: Optional[Callable[[int, int, float], None]] = None,
    ) -> Path:
        if message.file is None or not message.file.id:
            raise TdlibError(f"Message {message.id} has no downloadable file")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = int(message.file.size)
        if destination.exists() and (not expected or destination.stat().st_size == expected):
            return destination

        # A previous materialization attempt may have failed after TDLib already
        # completed the network download. Reuse that cache instead of asking the
        # gateway to start the same completed download again.
        file_obj = await self.get_file(message.file.id)
        local = file_obj.get("local") or {}
        if not local.get("isDownloadingCompleted"):
            await self._request(
                "POST",
                f"/{self.account_id}/file/start-download",
                json_body={
                    "chatId": int(message.chat_id),
                    "messageId": int(message.id),
                    "fileId": int(message.file.id),
                },
            )

        started = time.monotonic()
        last_progress = started
        last_size = -1
        local_path: Optional[Path] = None
        while True:
            now = time.monotonic()
            if now - started > timeout:
                raise asyncio.TimeoutError(
                    f"TDLib download timeout after {int(timeout)}s: {message.file.name}"
                )
            file_obj = await self.get_file(message.file.id)
            local = file_obj.get("local") or {}
            downloaded = int(local.get("downloadedSize") or 0)
            total = int(file_obj.get("size") or file_obj.get("expectedSize") or expected)
            if downloaded > last_size:
                elapsed = max(now - started, 0.001)
                last_size = downloaded
                last_progress = now
                if progress:
                    progress(downloaded, total, downloaded / elapsed)
            elif now - last_progress > stall_timeout:
                raise asyncio.TimeoutError(
                    f"TDLib download stalled for {int(stall_timeout)}s: {message.file.name}"
                )
            if local.get("isDownloadingCompleted"):
                local_path = Path(str(local.get("path") or ""))
                break
            await asyncio.sleep(2)

        if not local_path or not local_path.is_file():
            raise TdlibError(f"TDLib completed without a local file: {message.file.name}")
        if destination.exists():
            destination.unlink()
        try:
            os.link(local_path, destination)
        except OSError:
            await asyncio.to_thread(shutil.copy2, local_path, destination)
        if expected and destination.stat().st_size != expected:
            destination.unlink(missing_ok=True)
            raise TdlibError(
                f"Size mismatch for {message.file.name}: "
                f"{destination.stat().st_size if destination.exists() else 0}/{expected}"
            )
        await self.remove_file(message.file.id)
        return destination
