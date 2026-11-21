# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Redacted JSON-lines event log for comms modules (no secrets, no message bodies by default)."""

import json
import os
import re
import time
from pathlib import Path

REDACT_KEYS = re.compile(r"(psk|token|session|secret|password|passwd|key)$", re.I)
_HEXKEY = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def redact(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if REDACT_KEYS.search(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _HEXKEY.sub("[redacted]", value)
    return value


class EventLog:
    def __init__(self, path: Path, clock=time.time, max_bytes=2_000_000):
        self.path, self.clock, self.max_bytes = Path(path), clock, max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

    def log(self, event: str, **fields):
        rec = {"ts": round(self.clock(), 3), "event": event, **redact(fields)}
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec
