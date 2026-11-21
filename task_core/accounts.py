# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""accounts.json (PHASE-2.md section 6.1).

task-core only reads this file. task-core-admin is the only writer.
"""

import json
import logging
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from task_core.passwords import valid_hash_format

logger = logging.getLogger("task_core")

USERNAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
ACCOUNT_ROLES = ("operator", "administrator")


class AccountsError(ValueError):
    pass


def valid_username(name) -> bool:
    return isinstance(name, str) and USERNAME_RE.fullmatch(name) is not None


def parse_document(raw: bytes) -> dict:
    """Return {name: entry} or raise AccountsError for any shape problem."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise AccountsError("shape") from None
    if not isinstance(document, dict) or document.get("v") != 1 or isinstance(document.get("v"), bool):
        raise AccountsError("shape")
    accounts = document.get("accounts")
    if not isinstance(accounts, dict):
        raise AccountsError("shape")
    cleaned = {}
    for name, entry in accounts.items():
        if not valid_username(name) or not isinstance(entry, dict):
            raise AccountsError("shape")
        role = entry.get("role")
        if role not in ACCOUNT_ROLES:
            raise AccountsError("shape")
        if not valid_hash_format(entry.get("hash")):
            raise AccountsError("shape")
        disabled = entry.get("disabled", False)
        if not isinstance(disabled, bool):
            raise AccountsError("shape")
        created = entry.get("created")
        if created is not None and not isinstance(created, str):
            raise AccountsError("shape")
        cleaned[name] = {"role": role, "hash": entry["hash"], "disabled": disabled, "created": created}
    return cleaned


def render_document(accounts: dict) -> bytes:
    document = {"v": 1, "accounts": {name: accounts[name] for name in sorted(accounts)}}
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AccountStore:
    """Read-only view for task-core, reloaded when (inode, mtime_ns, size) changes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._key = None
        self._accounts: dict = {}
        self.reload_if_changed()

    def _stat_key(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return ("missing",)
        except OSError:
            return ("unreadable",)
        return (st.st_ino, st.st_mtime_ns, st.st_size, stat.S_IMODE(st.st_mode))

    def reload_if_changed(self) -> None:
        key = self._stat_key()
        if key == self._key:
            return
        self._key = key
        self._accounts = self._load(key)

    def _load(self, key) -> dict:
        if key == ("missing",):
            return {}
        if key == ("unreadable",):
            logger.error("accounts file unreadable")
            return {}
        mode = key[3]
        if mode & 0o077:
            logger.error("accounts file permissions rejected")
            return {}
        try:
            raw = self.path.read_bytes()
        except OSError:
            logger.error("accounts file unreadable")
            return {}
        try:
            return parse_document(raw)
        except AccountsError:
            self._preserve_corrupt(raw)
            return {}

    def _preserve_corrupt(self, original: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        evidence = self.path.parent / f"accounts.json.corrupt.{stamp}"
        suffix = 0
        while evidence.exists():
            suffix += 1
            evidence = self.path.parent / f"accounts.json.corrupt.{stamp}-{suffix}"
        try:
            fd = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(original)
        except OSError:
            logger.warning("evidence copy failed")
            logger.error("corrupt accounts file; no accounts loaded")
            return
        logger.warning("corrupt accounts preserved at %s", evidence.name)

    def get(self, name: str):
        return self._accounts.get(name)

    def names(self) -> list:
        return sorted(self._accounts)
