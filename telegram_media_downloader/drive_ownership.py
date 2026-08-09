"""Transfer rclone-uploaded My Drive trees to one canonical Drive owner."""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote

import requests


DRIVE_API = "https://www.googleapis.com/drive/v3"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRANSFER_LOCK = PROJECT_ROOT / ".runtime" / "ownership-transfer.lock"


class OwnershipTransferError(RuntimeError):
    pass


class DriveApiError(OwnershipTransferError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Drive API {status}: {message[:1000]}")
        self.status = status
        self.message = message


def remote_name(remote_path: str) -> str:
    head = remote_path.split(":", 1)[0]
    return head.split(",", 1)[0].strip()


def replace_remote_name(remote_path: str, replacement: str) -> str:
    current = remote_name(remote_path)
    if not current:
        raise OwnershipTransferError(f"Invalid rclone remote path: {remote_path}")
    return f"{replacement}{remote_path[len(current):]}"


def _run_json(command: list[str], timeout: float = 120) -> object:
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OwnershipTransferError(f"{' '.join(command[:3])} failed: {detail[-1000:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OwnershipTransferError(f"Invalid JSON from {' '.join(command[:3])}") from exc


def rclone_access_token(remote: str) -> str:
    """Ask rclone to refresh its token, then read only the access token in memory."""
    name = remote_name(remote)
    _run_json(["rclone", "about", f"{name}:", "--json"])
    config = _run_json(["rclone", "config", "dump"])
    if not isinstance(config, dict) or name not in config:
        raise OwnershipTransferError(f"Rclone remote is not configured: {name}")
    token = config[name].get("token", "")
    if isinstance(token, str):
        try:
            token = json.loads(token)
        except json.JSONDecodeError as exc:
            raise OwnershipTransferError(f"Invalid OAuth token for rclone remote: {name}") from exc
    access_token = token.get("access_token", "") if isinstance(token, dict) else ""
    if not access_token:
        raise OwnershipTransferError(f"Missing OAuth access token for rclone remote: {name}")
    return str(access_token)


class DriveClient:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    def request(
        self, method: str, path: str, *, params: dict | None = None,
        body: dict | None = None, attempts: int = 6,
    ) -> dict:
        url = f"{DRIVE_API}/{path.lstrip('/')}"
        for attempt in range(attempts):
            response = self.session.request(
                method, url, params=params, json=body, timeout=(15, 90),
            )
            if response.ok:
                return response.json() if response.content else {}
            message = response.text
            retryable = response.status_code in {429, 500, 502, 503, 504}
            if response.status_code == 403:
                retryable = any(
                    reason in message
                    for reason in ("rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED")
                )
            if retryable and attempt + 1 < attempts:
                time.sleep(min(32, 2**attempt))
                continue
            raise DriveApiError(response.status_code, message)
        raise OwnershipTransferError("Drive API retry loop exhausted")

    def identity(self) -> tuple[str, str]:
        about = self.request("GET", "about", params={"fields": "user(emailAddress,permissionId)"})
        user = about.get("user", {})
        email = str(user.get("emailAddress", ""))
        permission_id = str(user.get("permissionId", ""))
        if not email or not permission_id:
            raise OwnershipTransferError("Cannot determine Drive account email/permissionId")
        return email, permission_id

    def owner_emails(self, file_id: str) -> set[str]:
        item = self.request(
            "GET", f"files/{quote(file_id, safe='')}",
            params={"fields": "owners(emailAddress)", "supportsAllDrives": "true"},
        )
        return {
            str(owner.get("emailAddress", "")).lower()
            for owner in item.get("owners", []) if owner.get("emailAddress")
        }


@dataclass(frozen=True)
class RemoteItem:
    file_id: str
    path: str
    is_dir: bool


def list_remote_tree(remote_path: str) -> list[RemoteItem]:
    raw_children = _run_json(["rclone", "lsjson", remote_path, "--recursive"])
    rows = list(raw_children) if isinstance(raw_children, list) else []
    if ":" not in remote_path:
        raise OwnershipTransferError(f"Invalid rclone remote path: {remote_path}")
    head, raw_path = remote_path.split(":", 1)
    path = raw_path.strip("/")
    if not path:
        raise OwnershipTransferError("Ownership transfer requires a folder below the remote root")
    parent, leaf = path.rsplit("/", 1) if "/" in path else ("", path)
    parent_remote = f"{head}:{parent}"
    raw_siblings = _run_json(["rclone", "lsjson", parent_remote, "--dirs-only"])
    siblings = list(raw_siblings) if isinstance(raw_siblings, list) else []
    root = next(
        (
            row for row in siblings
            if str(row.get("Name", "")) == leaf or str(row.get("Path", "")).rstrip("/") == leaf
        ),
        None,
    )
    if not root or not root.get("ID"):
        raise OwnershipTransferError(f"Cannot resolve Drive folder ID for {remote_path}")
    root = dict(root)
    root["Path"] = ""
    root["IsDir"] = True
    rows.append(root)
    items = [
        RemoteItem(str(row.get("ID", "")), str(row.get("Path", "")), bool(row.get("IsDir")))
        for row in rows if row.get("ID")
    ]
    if not items:
        raise OwnershipTransferError(f"No Drive file IDs found under {remote_path}")
    return sorted(
        items,
        key=lambda item: (item.path.count("/"), not item.is_dir),
        reverse=True,
    )


@contextmanager
def ownership_transfer_lock() -> Iterator[None]:
    TRANSFER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with TRANSFER_LOCK.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _initiate_consumer_transfer(
    source: DriveClient, file_id: str, owner_email: str, owner_permission_id: str,
) -> str:
    path = f"files/{quote(file_id, safe='')}/permissions"
    body = {
        "type": "user", "role": "writer", "emailAddress": owner_email,
        "pendingOwner": True,
    }
    try:
        created = source.request(
            "POST", path,
            params={
                "supportsAllDrives": "true", "sendNotificationEmail": "true",
                "fields": "id,pendingOwner",
            },
            body=body,
        )
        permission_id = str(created.get("id") or owner_permission_id)
        if created.get("pendingOwner"):
            return permission_id
        # A permission inherited from the destination folder can make create
        # return success without promoting it to pending owner. Explicitly
        # update that stable user permission before the owner accepts.
        source.request(
            "PATCH", f"{path}/{quote(permission_id, safe='')}",
            params={"supportsAllDrives": "true", "fields": "id,pendingOwner"},
            body={"role": "writer", "pendingOwner": True},
        )
        return permission_id
    except DriveApiError as create_error:
        try:
            source.request(
                "PATCH", f"{path}/{quote(owner_permission_id, safe='')}",
                params={"supportsAllDrives": "true"},
                body={"role": "writer", "pendingOwner": True},
            )
            return owner_permission_id
        except DriveApiError:
            raise create_error


def _transfer_one(
    source: DriveClient, owner: DriveClient, file_id: str,
    owner_email: str, owner_permission_id: str,
) -> bool:
    if owner_email.lower() in owner.owner_emails(file_id):
        return False
    permissions_path = f"files/{quote(file_id, safe='')}/permissions"
    try:
        permission_id = _initiate_consumer_transfer(
            source, file_id, owner_email, owner_permission_id,
        )
        owner.request(
            "PATCH", f"{permissions_path}/{quote(permission_id, safe='')}",
            params={"supportsAllDrives": "true", "transferOwnership": "true"},
            body={"role": "owner"},
        )
    except DriveApiError as consumer_error:
        try:
            source.request(
                "PATCH", f"{permissions_path}/{quote(owner_permission_id, safe='')}",
                params={"supportsAllDrives": "true", "transferOwnership": "true"},
                body={"role": "owner"},
            )
        except DriveApiError:
            raise consumer_error

    for _ in range(6):
        if owner_email.lower() in owner.owner_emails(file_id):
            return True
        time.sleep(2)
    raise OwnershipTransferError(f"Ownership did not propagate for Drive file {file_id}")


def transfer_remote_tree(
    source_remote_path: str, owner_remote: str,
    *, on_progress: Callable[[str], None] | None = None,
) -> int:
    """Transfer every object, including folders, then verify the canonical owner."""
    if remote_name(source_remote_path) == remote_name(owner_remote):
        return 0
    progress = on_progress or (lambda _message: None)
    with ownership_transfer_lock():
        source = DriveClient(rclone_access_token(source_remote_path))
        owner = DriveClient(rclone_access_token(owner_remote))
        owner_email, owner_permission_id = owner.identity()
        items = list_remote_tree(source_remote_path)
        changed = 0
        for index, item in enumerate(items, start=1):
            if _transfer_one(source, owner, item.file_id, owner_email, owner_permission_id):
                changed += 1
            progress(f"Ownership {index}/{len(items)} -> {owner_email}: {item.path or '[course folder]'}")
        return changed
