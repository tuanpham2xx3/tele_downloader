#!/usr/bin/env python3
"""Interactive account setup and registry management for telegram-files."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import requests
from websockets.sync.client import connect as ws_connect


if hasattr(os.sys.stdout, "reconfigure"):
    os.sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
REGISTRY = RUNTIME / "tdlib-accounts.json"
PENDING = RUNTIME / "tdlib-login-pending.json"
WAIT_PHONE = 306402531
WAIT_CODE = 52643073
WAIT_PASSWORD = 112238030
READY = -1834871737


class AdminError(RuntimeError):
    pass


def as_list(value: Any) -> List[dict]:
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def authorized_accounts(base_url: str) -> List[dict]:
    response = requests.get(
        f"{base_url.rstrip('/')}/telegrams?authorized=true", timeout=10
    )
    response.raise_for_status()
    return as_list(response.json())


def write_registry(role: str, account: dict) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
        if not isinstance(registry, dict):
            registry = {}
    except (OSError, json.JSONDecodeError):
        registry = {}
    registry[role] = {
        "id": int(account["id"]),
        "name": str(account.get("name") or role),
    }
    REGISTRY.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_pending() -> Dict[str, dict]:
    try:
        value = json.loads(PENDING.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_pending(value: Dict[str, dict]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(value, indent=2), encoding="utf-8")


def pending_for(role: str) -> dict:
    value = read_pending().get(role)
    if not isinstance(value, dict) or not value.get("temporary_id"):
        raise AdminError(f"No pending login for {role}; run send-code first")
    return value


def clear_pending(role: str) -> None:
    pending = read_pending()
    pending.pop(role, None)
    if pending:
        write_pending(pending)
    else:
        PENDING.unlink(missing_ok=True)


class LoginTransport:
    def __init__(self, base_url: str, account_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.http = requests.Session()
        self.buffer: List[dict] = []
        self.http.get(f"{self.base_url}/", timeout=10).raise_for_status()
        self.http.post(
            f"{self.base_url}/telegrams/change?telegramId={account_id}", timeout=10
        ).raise_for_status()
        cookie = "; ".join(f"{item.name}={item.value}" for item in self.http.cookies)
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        self.ws = ws_connect(
            f"{scheme}://{parsed.netloc}/ws?telegramId={account_id}",
            additional_headers={"Cookie": cookie},
            open_timeout=10,
        )

    def close(self) -> None:
        self.ws.close()
        self.http.close()

    def _receive(self, timeout: float = 30) -> dict:
        return json.loads(self.ws.recv(timeout=timeout))

    def call(self, method: str, payload: Dict[str, Any]) -> Any:
        response = self.http.post(
            f"{self.base_url}/telegram/api/{method}", json=payload, timeout=15
        )
        response.raise_for_status()
        code = str(response.json()["code"])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            event = self._receive(max(1, deadline - time.monotonic()))
            if str(event.get("code") or "") != code:
                self.buffer.append(event)
                continue
            data = event.get("data")
            if int(event.get("type") or 0) == -1:
                message = data.get("message") if isinstance(data, dict) else data
                raise AdminError(str(message or "Unknown TDLib error"))
            return data
        raise AdminError(f"Timed out waiting for {method}")

    @staticmethod
    def _constructor(event: dict) -> int:
        data = event.get("data") or {}
        return int(data.get("constructor") or 0) if isinstance(data, dict) else 0

    def wait_authorization(self, expected: Iterable[int], timeout: float = 60) -> dict:
        expected_set = set(expected)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for index, event in enumerate(self.buffer):
                if self._constructor(event) in expected_set:
                    return self.buffer.pop(index)
            event = self._receive(max(1, deadline - time.monotonic()))
            if int(event.get("type") or 0) == -1:
                data = event.get("data") or {}
                raise AdminError(str(data.get("message") or "TDLib authorization error"))
            if self._constructor(event) in expected_set:
                return event
            self.buffer.append(event)
        raise AdminError("Timed out waiting for Telegram authorization state")


def login(role: str, base_url: str) -> int:
    before = {int(item["id"]) for item in authorized_accounts(base_url)}
    setup = requests.Session()
    setup.get(f"{base_url}/", timeout=10).raise_for_status()
    created = setup.post(
        f"{base_url}/telegram/create", json={"proxyName": None}, timeout=20
    )
    created.raise_for_status()
    temporary_id = str(created.json()["id"])
    setup.close()

    transport = LoginTransport(base_url, temporary_id)
    try:
        phone = input(f"Phone for {role} (example +849...): ").strip()
        transport.call(
            "SetAuthenticationPhoneNumber",
            {"phoneNumber": phone, "settings": None},
        )
        transport.wait_authorization({WAIT_CODE})
        code = input("Telegram login code: ").strip().replace(" ", "")
        transport.call("CheckAuthenticationCode", {"code": code})
        state = transport.wait_authorization({WAIT_PASSWORD, READY})
        if transport._constructor(state) == WAIT_PASSWORD:
            password = getpass.getpass("Telegram 2FA password: ")
            transport.call("CheckAuthenticationPassword", {"password": password})
            transport.wait_authorization({READY})
    finally:
        transport.close()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        accounts = authorized_accounts(base_url)
        new_accounts = [item for item in accounts if int(item["id"]) not in before]
        if new_accounts:
            account = new_accounts[0]
            write_registry(role, account)
            print(f"{role} ready: {account.get('name')} ({account['id']})")
            return 0
        time.sleep(1)
    raise AdminError("Authorization reached READY but the account was not persisted")


def send_code(role: str, phone: str, base_url: str) -> int:
    """Start a resumable login without persisting the phone number."""
    before = [int(item["id"]) for item in authorized_accounts(base_url)]
    setup = requests.Session()
    try:
        setup.get(f"{base_url}/", timeout=10).raise_for_status()
        created = setup.post(
            f"{base_url}/telegram/create", json={"proxyName": None}, timeout=20
        )
        created.raise_for_status()
        temporary_id = str(created.json()["id"])
    finally:
        setup.close()

    transport = LoginTransport(base_url, temporary_id)
    try:
        transport.call(
            "SetAuthenticationPhoneNumber",
            {"phoneNumber": phone, "settings": None},
        )
        transport.wait_authorization({WAIT_CODE})
    finally:
        transport.close()

    pending = read_pending()
    pending[role] = {
        "temporary_id": temporary_id,
        "before_ids": before,
        "stage": "code",
    }
    write_pending(pending)
    print(f"CODE_SENT role={role}")
    return 0


def finish_login(role: str, base_url: str) -> int:
    state = pending_for(role)
    before = {int(item) for item in state.get("before_ids", [])}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        accounts = authorized_accounts(base_url)
        new_accounts = [item for item in accounts if int(item["id"]) not in before]
        if new_accounts:
            account = new_accounts[0]
            write_registry(role, account)
            clear_pending(role)
            print(f"READY role={role} name={account.get('name')} id={account['id']}")
            return 0
        time.sleep(1)
    raise AdminError("Authorization reached READY but the account was not persisted")


def submit_code(role: str, code: str, base_url: str) -> int:
    state = pending_for(role)
    transport = LoginTransport(base_url, str(state["temporary_id"]))
    try:
        transport.call("CheckAuthenticationCode", {"code": code.replace(" ", "")})
        authorization = transport.wait_authorization({WAIT_PASSWORD, READY})
    finally:
        transport.close()
    if LoginTransport._constructor(authorization) == WAIT_PASSWORD:
        pending = read_pending()
        pending[role]["stage"] = "password"
        write_pending(pending)
        print(f"PASSWORD_REQUIRED role={role}")
        return 0
    return finish_login(role, base_url)


def submit_password(role: str, password: str, base_url: str) -> int:
    state = pending_for(role)
    if state.get("stage") != "password":
        raise AdminError(f"{role} is not waiting for a 2FA password")
    transport = LoginTransport(base_url, str(state["temporary_id"]))
    try:
        transport.call("CheckAuthenticationPassword", {"password": password})
        transport.wait_authorization({READY})
    finally:
        transport.close()
    return finish_login(role, base_url)


def list_accounts(base_url: str) -> int:
    accounts = authorized_accounts(base_url)
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        registry = {}
    roles = {
        int(value.get("id") if isinstance(value, dict) else value): role
        for role, value in registry.items()
        if value
    }
    for account in accounts:
        account_id = int(account["id"])
        print(
            f"{roles.get(account_id, '-'):<5} {account_id:<14} "
            f"{account.get('status', '-'):<8} {account.get('name', '')}"
        )
    return 0


def register(role: str, account_id: int, base_url: str) -> int:
    account = next(
        (item for item in authorized_accounts(base_url) if int(item["id"]) == account_id),
        None,
    )
    if not account:
        raise AdminError(f"Authorized account not found: {account_id}")
    write_registry(role, account)
    print(f"Registered {role} -> {account.get('name')} ({account_id})")
    return 0


def configured_data_root() -> Path:
    values: Dict[str, str] = {}
    env_path = Path(os.environ.get("TDLIB_ENV_FILE", RUNTIME / "tdlib.env"))
    try:
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                key, value = raw.split("=", 1)
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return Path(
        os.environ.get("TDLIB_DATA_ROOT")
        or values.get("TDLIB_DATA_ROOT")
        or RUNTIME / "tdlib" / "data"
    ).resolve()


def migrate_root(base_url: str) -> int:
    """Rewrite imported absolute account paths after an OS/host migration."""
    try:
        if requests.get(f"{base_url.rstrip('/')}/", timeout=2).ok:
            raise AdminError("Stop the TDLib backend before migrate-root")
    except requests.RequestException:
        pass

    data_root = configured_data_root()
    database = data_root / "data.db"
    if not database.is_file():
        raise AdminError(f"TDLib database not found: {database}")

    connection = sqlite3.connect(database)
    try:
        rows = list(connection.execute("select id, root_path from telegram_record"))
        updates = []
        for account_id, old_root in rows:
            old_text = str(old_root or "")
            leaf = (
                PureWindowsPath(old_text).name
                if "\\" in old_text
                else Path(old_text).name
            )
            new_root = data_root / "account" / leaf
            if not leaf or not new_root.is_dir():
                raise AdminError(
                    f"Account directory missing for {account_id}: {new_root}"
                )
            if Path(old_text) != new_root:
                updates.append((str(new_root), int(account_id)))

        if not updates:
            print("MIGRATE_ROOT no changes needed")
            return 0

        backup = data_root / "data.db.before-root-migration"
        if backup.exists():
            raise AdminError(f"Migration backup already exists: {backup}")
        backup_connection = sqlite3.connect(backup)
        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()

        connection.executemany(
            "update telegram_record set root_path=? where id=?", updates
        )
        removed = connection.execute(
            "delete from file_record where local_path is not null"
        ).rowcount
        connection.commit()
        connection.execute("pragma wal_checkpoint(TRUNCATE)")
        print(
            f"MIGRATE_ROOT updated={len(updates)} stale_files_removed={removed} "
            f"backup={backup}"
        )
        return 0
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TDLIB_BASE_URL", "http://127.0.0.1:8080"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    login_parser = sub.add_parser("login")
    login_parser.add_argument("role", choices=("acc1", "acc2", "acc3"))
    send_code_parser = sub.add_parser("send-code")
    send_code_parser.add_argument("role", choices=("acc1", "acc2", "acc3"))
    send_code_parser.add_argument("phone")
    submit_code_parser = sub.add_parser("submit-code")
    submit_code_parser.add_argument("role", choices=("acc1", "acc2", "acc3"))
    submit_code_parser.add_argument("code")
    password_parser = sub.add_parser("submit-password")
    password_parser.add_argument("role", choices=("acc1", "acc2", "acc3"))
    sub.add_parser("migrate-root")
    register_parser = sub.add_parser("register")
    register_parser.add_argument("role", choices=("acc1", "acc2", "acc3"))
    register_parser.add_argument("account_id", type=int)
    args = parser.parse_args()
    try:
        if args.command == "list":
            return list_accounts(args.base_url)
        if args.command == "login":
            return login(args.role, args.base_url)
        if args.command == "send-code":
            return send_code(args.role, args.phone, args.base_url)
        if args.command == "submit-code":
            return submit_code(args.role, args.code, args.base_url)
        if args.command == "submit-password":
            password = os.environ.pop("TDLIB_LOGIN_PASSWORD", "")
            if not password:
                raise AdminError("Set TDLIB_LOGIN_PASSWORD for this command")
            return submit_password(args.role, password, args.base_url)
        if args.command == "migrate-root":
            return migrate_root(args.base_url)
        return register(args.role, args.account_id, args.base_url)
    except (requests.RequestException, AdminError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
