# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Launcher status cards: $XDG_RUNTIME_DIR/task/status/<module>.json (schema 1, docs/COMMS-STATUS.md).

Never contains message content, callsign lists, PSKs or tokens: only state, a device label,
a short summary and counters. Written atomically (tmp + rename).
"""

import json
import os
import threading
import re
import time
from pathlib import Path

from task_comms import paths

SCHEMA = 1
STATES = ("starting", "disconnected", "connecting", "connected", "rx-only", "tx-capable",
          "queued", "busy", "error", "stopped")
STALE_AFTER_S = 10
_MODULE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_FORBIDDEN_KEYS = ("text", "message", "psk", "token", "session", "secret", "password")


class StatusWriter:
    def __init__(self, module: str, directory: Path = None, clock=time.time):
        if not _MODULE.match(module):
            raise ValueError("bad module id")
        self.module = module
        self.dir = Path(directory) if directory else paths.status_dir()
        self.clock = clock
        self.path = self.dir / f"{module}.json"

    def write(self, state: str, *, device=None, summary="", counts=None, last_error=None, indicators=None):
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        counts = dict(counts or {})
        for k, v in counts.items():
            if not isinstance(v, int) or any(f in k.lower() for f in _FORBIDDEN_KEYS):
                raise ValueError(f"counts must be integers without content keys ({k})")
        doc = {"schema": SCHEMA, "module": self.module, "state": state, "device": device,
               "summary": str(summary)[:120], "counts": counts,
               "last_error": None if last_error is None else str(last_error)[:200],
               "indicators": list(indicators or []), "pid": os.getpid(), "heartbeat_ts": self.clock()}
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        tmp = self.path.with_name(f".{self.module}.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        return doc

    def heartbeat(self):
        doc = read_status(self.path, clock=self.clock)
        if doc and not doc.get("_invalid"):
            doc = {k: v for k, v in doc.items() if not k.startswith("_")}
            return self.write(doc["state"], device=doc.get("device"), summary=doc.get("summary", ""),
                              counts=doc.get("counts"), last_error=doc.get("last_error"),
                              indicators=doc.get("indicators"))
        return None

    def remove(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_status(path: Path, clock=time.time, pid_alive=_pid_alive):
    """Parsed card plus derived '_stale' / '_dead'; None if absent; {'_invalid': reason} if unreadable."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {"_invalid": f"unreadable ({exc.strerror})"}
    try:
        doc = json.loads(raw)
    except ValueError:
        return {"_invalid": "not JSON"}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or doc.get("state") not in STATES:
        return {"_invalid": "unknown schema"}
    hb = doc.get("heartbeat_ts")
    doc["_stale"] = not isinstance(hb, (int, float)) or clock() - hb > STALE_AFTER_S
    doc["_dead"] = not pid_alive(doc.get("pid"))
    return doc


def read_all(directory: Path = None, **kw) -> dict:
    d = Path(directory) if directory else paths.status_dir()
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            out[p.stem] = read_status(p, **kw)
    return out
