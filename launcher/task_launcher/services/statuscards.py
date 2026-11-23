# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only launcher view of comms status cards ($XDG_RUNTIME_DIR/task/status/<module>.json, schema 1).

Same contract as task_comms.status (docs/COMMS-STATUS.md) but no import of it, so the launcher
works without python3-task-comms. Cards never contain message content.
"""

import json
import os
import tempfile
import time
from pathlib import Path

from task_launcher import paths

SCHEMA = 1
STALE_AFTER_S = 10
STATES = ("starting", "disconnected", "connecting", "connected", "rx-only", "tx-capable",
          "queued", "busy", "error", "stopped")
# readiness probe name -> module writing the card
CARD_FOR_PROBE = {"mesh": "task-mesh", "direwolf": "task-aprs", "rtl-sdr": "task-sdr"}


def status_dir() -> Path:
    v = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(v) if v and os.path.isabs(v) else (Path("/tmp") if os.name == "posix" else Path(tempfile.gettempdir())) / f"task-runtime-{paths.user_tag()}"
    return base / "task" / "status"


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_card(module, directory=None, clock=time.time, alive=_alive):
    path = Path(directory or status_dir()) / f"{module}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"state": "error", "summary": "status card unreadable", "_stale": True}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or doc.get("state") not in STATES:
        return {"state": "error", "summary": "status card has an unknown schema", "_stale": True}
    hb = doc.get("heartbeat_ts")
    doc["_stale"] = not isinstance(hb, (int, float)) or clock() - hb > STALE_AFTER_S or not alive(doc.get("pid"))
    return doc


def card_text(doc):
    """One line for a tile: '<STATE> · summary · indicators' or a not-responding note."""
    if doc is None:
        return None
    if doc.get("_stale"):
        return "not responding (status card stale)"
    bits = [str(doc.get("state", "")).upper()]
    if doc.get("summary"):
        bits.append(str(doc["summary"])[:80])
    bits += [str(i) for i in doc.get("indicators") or []][:3]
    if doc.get("last_error"):
        bits.append("error: " + str(doc["last_error"])[:60])
    return " · ".join(bits)


def collect(directory=None, clock=time.time):
    return {probe: read_card(mod, directory, clock) for probe, mod in CARD_FOR_PROBE.items()}
