# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Append-only, hash-chained transmit audit log (every request, allowed or refused).

Each line: {"seq", "ts", "prev", ..., "hash"} where hash = sha256(prev + canonical JSON
without "hash"). Content is never stored: only its SHA-256 and length.
verify() detects edits, deletions and reordering (not a deletion of the whole tail;
that limitation is documented).
"""

import hashlib
import json
import os
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(prev: str, rec: dict) -> str:
    body = json.dumps({k: v for k, v in rec.items() if k != "hash"}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev + body).encode()).hexdigest()


def payload_digest(payload) -> dict:
    data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    return {"payload_sha256": hashlib.sha256(data).hexdigest(), "payload_len": len(data)}


class AuditLog:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

    def _tail(self):
        if not self.path.exists():
            return 0, GENESIS
        last = None
        with open(self.path, "rb") as f:
            for line in f:
                if line.strip():
                    last = line
        if last is None:
            return 0, GENESIS
        rec = json.loads(last)
        return rec["seq"], rec["hash"]

    def append(self, **fields) -> dict:
        for banned in ("text", "message", "payload", "session", "token"):
            if banned in fields:
                raise ValueError(f"audit records must not contain {banned!r}")
        seq, prev = self._tail()
        rec = {"seq": seq + 1, "ts": round(self.clock(), 3), "prev": prev, **fields}
        rec["hash"] = _digest(prev, rec)
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return rec

    def verify(self):
        """(ok, count, problem)."""
        prev, n = GENESIS, 0
        if not self.path.exists():
            return True, 0, None
        with open(self.path, "rb") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    return False, n, f"line {i}: not JSON"
                if rec.get("prev") != prev or rec.get("seq") != n + 1 or _digest(prev, rec) != rec.get("hash"):
                    return False, n, f"line {i}: chain broken"
                prev, n = rec["hash"], n + 1
        return True, n, None
