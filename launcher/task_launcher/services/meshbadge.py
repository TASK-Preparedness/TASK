# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Mesh tile badge (Phase 4F): combined unread count, per-protocol breakdown, priority marker. READ-ONLY.

Source 1: task-mesh-service (or a running task-mesh window's hub) over its private Unix socket
($XDG_RUNTIME_DIR/task/mesh.sock, 0600, same-uid only), method "unread" — a pure query.
Source 2 (fallback): the comms notification store, opened with SQLite ``mode=ro`` (no writes possible).
Nothing here marks anything read, and no message content or sender is ever read: counts only.
"""

import json
import os
import socket
import sqlite3
from pathlib import Path

LABELS = {"meshtastic": "Meshtastic", "meshcore": "MeshCore"}


def _runtime() -> Path:
    v = os.environ.get("XDG_RUNTIME_DIR")
    return Path(v) if v and os.path.isabs(v) else Path("/tmp") / f"task-runtime-{os.getuid()}"


def socket_path() -> Path:
    return _runtime() / "task" / "mesh.sock"


def comms_db() -> Path:
    v = os.environ.get("XDG_DATA_HOME")
    base = Path(v) if v and os.path.isabs(v) else Path.home() / ".local" / "share"
    return base / "task-comms" / "notifications.sqlite"


def from_service(path=None, timeout=0.5):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(path or socket_path()))
        s.sendall(b'{"id": 1, "method": "unread", "params": {}}\n')
        buf = b""
        while b"\n" not in buf and len(buf) < 65536:
            chunk = s.recv(4096)
            if not chunk:
                return None
            buf += chunk
        reply = json.loads(buf.split(b"\n", 1)[0])
    except (OSError, ValueError):
        return None
    finally:
        s.close()
    r = reply.get("result") if isinstance(reply, dict) and reply.get("ok") else None
    if not isinstance(r, dict):
        return None
    by = {p: int((r.get("by_protocol") or {}).get(p, {}).get("unread", 0)) for p in LABELS}
    pri = int(r.get("priority") or 0)
    return {"total": sum(by.values()), "priority": pri, "by_protocol": by, "source": "service"}


def from_store(path=None):
    p = Path(path or comms_db())
    if not p.exists():
        return None
    try:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=1)
        try:
            rows = db.execute("SELECT source, COUNT(*), SUM(priority IS NOT NULL) FROM notification "
                              "WHERE read=0 AND substr(source, 1, 5)='mesh.' GROUP BY source").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    by = {k: 0 for k in LABELS}
    pri = 0
    for src, n, pr in rows:
        proto = src[5:]
        if proto in by:
            by[proto] += int(n)
            pri += int(pr or 0)
    return {"total": sum(by.values()), "priority": pri, "by_protocol": by, "source": "store"}


def collect(sock=None, store=None):
    return from_service(sock) or from_store(store)


def badge_text(b):
    """'3 unread (Meshtastic 2 · MeshCore 1) · ! 1 priority' or None when nothing is unread."""
    if not b or not b.get("total"):
        return None
    parts = [f"{LABELS[p]} {n}" for p, n in b["by_protocol"].items() if n]
    text = f"{b['total']} unread ({' · '.join(parts)})"
    if b.get("priority"):
        text += f" · ! {b['priority']} priority"
    return text
