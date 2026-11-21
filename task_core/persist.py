# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import errno
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from task_core.errors import PersistError

logger = logging.getLogger("task_core")

_dir_fsync_warned = False


def reset_directory_fsync_warning() -> None:
    global _dir_fsync_warned
    _dir_fsync_warned = False


def fsync_directory(directory: Path) -> None:
    """Fsync a directory after rename.

    EINVAL, ENOTSUP, and EOPNOTSUPP mean the filesystem does not support
    directory fsync. That is logged once and is not a failure.

    Any other I/O error means the rename may already be visible, but the
    assignment was not durably persisted. Raise PersistError and do not
    report success. The log line is fixed and includes no path or OS text.
    """
    global _dir_fsync_warned
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
                if not _dir_fsync_warned:
                    logger.warning("directory fsync not supported")
                    _dir_fsync_warned = True
                return
            logger.error("directory fsync failed")
            raise PersistError("persist failed") from None
    finally:
        os.close(fd)


class Store:
    """Crash-safe JSON replace. Steps are recorded so tests can see the order."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.steps: list[str] = []
        self._replaced = False

    def load_assignments(self) -> tuple[dict, bool]:
        """Return (assignments, ok). A corrupt file is preserved as evidence."""
        if not self.path.exists():
            return {}, True
        original = self.path.read_bytes()
        try:
            document = json.loads(original.decode("utf-8"))
            assignments = _valid_assignments(document)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            self._preserve_corrupt(original)
            return {}, False
        return assignments, True

    def save_assignments(self, assignments: dict) -> None:
        document = {"v": 1, "assignments": assignments}
        payload = (json.dumps(document, indent=2) + "\n").encode("utf-8")
        self.replace(payload)

    def replace(self, payload: bytes) -> None:
        directory = self.path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        renamed = False
        self.steps = []
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                self.steps.append("write")
                handle.flush()
                self.steps.append("flush")
                os.fsync(handle.fileno())
                self.steps.append("fsync-file")
            os.replace(tmp_name, self.path)
            renamed = True
            self.steps.append("rename")
            fsync_directory(directory)
            self.steps.append("fsync-dir")
            self._replaced = True
        except Exception as exc:
            if not renamed and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            logger.error("persist failed")
            if isinstance(exc, PersistError):
                raise
            raise PersistError("persist failed") from None
        finally:
            if not renamed and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _preserve_corrupt(self, original: bytes) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        evidence = self.path.parent / f"devices.json.corrupt.{stamp}"
        suffix = 0
        while evidence.exists():
            suffix += 1
            evidence = self.path.parent / f"devices.json.corrupt.{stamp}-{suffix}"
        try:
            evidence.write_bytes(original)
        except OSError:
            logger.warning("evidence copy failed")
            return
        if self.path.read_bytes() != original:
            logger.warning("evidence copy failed")
            return
        logger.warning("corrupt assignments preserved at %s", evidence.name)


def _valid_assignments(document) -> dict:
    if not isinstance(document, dict) or document.get("v") != 1:
        raise ValueError("shape")
    raw = document.get("assignments")
    if not isinstance(raw, dict):
        raise ValueError("shape")
    cleaned = {}
    for logical, entry in raw.items():
        if not isinstance(logical, str) or not isinstance(entry, dict):
            raise ValueError("shape")
        device_id = entry.get("device_id")
        if not isinstance(device_id, str) or not _device_id_ok(device_id):
            raise ValueError("shape")
        alias = entry.get("alias", None)
        if alias is not None and not isinstance(alias, str):
            raise ValueError("shape")
        cleaned[logical] = {"device_id": device_id, "alias": alias}
    from task_core.devices import LOGICAL

    for logical in cleaned:
        if logical not in LOGICAL:
            raise ValueError("shape")
    return cleaned


def _device_id_ok(value: str) -> bool:
    if not value.startswith("dev_") or len(value) != 4 + 16:
        return False
    hexpart = value[4:]
    return all(ch in "0123456789abcdef" for ch in hexpart)
