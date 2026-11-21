# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Atomic small-file writes: temp file in the same directory, fsync, rename, fsync dir."""

import json
import os
import tempfile
from pathlib import Path


def write_bytes(path, data: bytes, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def write_json(path, document, mode: int = 0o600) -> None:
    write_bytes(path, (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"), mode)


def read_json(path, max_bytes: int = 256 * 1024):
    """Return the parsed document, or None if missing/unreadable/invalid/oversized."""
    try:
        path = Path(path)
        if path.stat().st_size > max_bytes:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
