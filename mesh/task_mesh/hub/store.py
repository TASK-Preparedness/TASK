# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Hub message store: $XDG_DATA_HOME/task-mesh/hub.sqlite3 (directory 0700, file 0600, WAL).

One writer (the radio owner: task-mesh-service or the GUI in direct mode). Unread = read=0 AND origin='live'
AND direction='in': history-sync rows are kept and shown but never counted as new. Reading never marks read;
only mark_read(protocol, conversation) does. Nothing is deleted except by explicit retention (not enabled).
Protection is Unix permissions only (same-uid processes can read it), as in 0.2.0."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from task_mesh.hub.model import LIVE, PROTOCOLS, HubMessage, HubNode, check_protocol

SCHEMA = 1
DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS message(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  protocol TEXT NOT NULL, device TEXT NOT NULL, key TEXT NOT NULL,
  direction TEXT NOT NULL, kind TEXT NOT NULL, conversation TEXT NOT NULL,
  sender TEXT NOT NULL, sender_label TEXT NOT NULL, text TEXT NOT NULL,
  ts REAL NOT NULL, sender_ts INTEGER, origin TEXT NOT NULL,
  priority TEXT, priority_source TEXT, snr REAL, rssi INTEGER, hops INTEGER,
  state TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0,
  UNIQUE(protocol, key));
CREATE INDEX IF NOT EXISTS message_conv ON message(protocol, conversation, ts);
CREATE INDEX IF NOT EXISTS message_unread ON message(read, origin, direction);
CREATE TABLE IF NOT EXISTS node(
  protocol TEXT NOT NULL, key TEXT NOT NULL, name TEXT, role TEXT, last_heard REAL, snr REAL, rssi INTEGER,
  hops INTEGER, lat REAL, lon REAL, device TEXT, PRIMARY KEY(protocol, key));
"""
MSG_COLS = ("id", "protocol", "device", "key", "direction", "kind", "conversation", "sender", "sender_label", "text",
            "ts", "sender_ts", "origin", "priority", "priority_source", "snr", "rssi", "hops", "state", "read")
NODE_COLS = ("protocol", "key", "name", "role", "last_heard", "snr", "rssi", "hops", "lat", "lon", "device")


def private_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    os.close(os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600))
    os.chmod(path, 0o600)


class HubStore:
    def __init__(self, path: Path, readonly: bool = False) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        if readonly:
            self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False, timeout=5)
        else:
            private_file(self.path)
            self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
            with self.db:
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.executescript(DDL)
                self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema', ?)", (str(SCHEMA),))
            for suffix in ("-wal", "-shm"):
                p = Path(str(self.path) + suffix)
                if p.exists():
                    os.chmod(p, 0o600)

    def close(self) -> None:
        self.db.close()

    # --- messages -----------------------------------------------------------------------------------
    def add(self, m: HubMessage) -> Optional[int]:
        """-> new row id, or None for a duplicate (same protocol + dedupe key)."""
        d = m.to_dict()
        d["read"] = int(bool(d["read"]))
        cols = [c for c in MSG_COLS if c != "id"]
        with self._lock, self.db:
            cur = self.db.execute(f"INSERT OR IGNORE INTO message({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                  [d[c] for c in cols])
        if cur.rowcount != 1:
            return None
        m.id = cur.lastrowid
        return m.id

    def update_state(self, row_id: int, state: str) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE message SET state=? WHERE id=?", (state, row_id))

    def get(self, row_id: int) -> Optional[dict]:
        with self._lock:
            r = self.db.execute(f"SELECT {','.join(MSG_COLS)} FROM message WHERE id=?", (row_id,)).fetchone()
        return dict(zip(MSG_COLS, r)) if r else None

    def messages(self, protocol: Optional[str] = None, conversation: Optional[str] = None, limit: int = 500) -> list:
        q, a = f"SELECT {','.join(MSG_COLS)} FROM message WHERE 1=1", []
        if protocol:
            q += " AND protocol=?"
            a.append(check_protocol(protocol))
        if conversation:
            q += " AND conversation=?"
            a.append(conversation)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"
        a.append(int(limit))
        with self._lock:
            rows = self.db.execute(q, a).fetchall()
        return [dict(zip(MSG_COLS, r)) for r in reversed(rows)]

    def conversations(self, protocol: Optional[str] = None) -> list:
        q = ("SELECT protocol, conversation, kind, COUNT(*), MAX(ts), "
             "SUM(read=0 AND origin='live' AND direction='in'), "
             "SUM(read=0 AND origin='live' AND direction='in' AND priority IS NOT NULL) FROM message")
        a = []
        if protocol:
            q += " WHERE protocol=?"
            a.append(check_protocol(protocol))
        q += " GROUP BY protocol, conversation ORDER BY MAX(ts) DESC"
        with self._lock:
            rows = self.db.execute(q, a).fetchall()
        return [{"protocol": p, "conversation": c, "kind": k, "count": n, "last_ts": t, "unread": int(u or 0),
                 "priority": int(pr or 0)} for p, c, k, n, t, u, pr in rows]

    def unread(self) -> dict:
        """{"total", "priority", "by_protocol": {p: {"unread", "priority"}}} — read-only."""
        with self._lock:
            rows = self.db.execute(
                "SELECT protocol, COUNT(*), SUM(priority IS NOT NULL) FROM message "
                "WHERE read=0 AND origin='live' AND direction='in' GROUP BY protocol").fetchall()
        by = {p: {"unread": 0, "priority": 0} for p in PROTOCOLS}
        for p, n, pr in rows:
            by[p] = {"unread": n, "priority": int(pr or 0)}
        return {"total": sum(v["unread"] for v in by.values()), "priority": sum(v["priority"] for v in by.values()),
                "by_protocol": by}

    def mark_read(self, protocol: str, conversation: str) -> int:
        with self._lock, self.db:
            return self.db.execute("UPDATE message SET read=1 WHERE protocol=? AND conversation=? AND read=0",
                                   (check_protocol(protocol), conversation)).rowcount

    # --- nodes ----------------------------------------------------------------------------------------
    def prune(self, older_than_days: int, clock=None) -> int:
        """History retention: delete messages older than N days (0 = keep). Unread live messages are kept."""
        if older_than_days <= 0:
            return 0
        cutoff = (clock or now)() - older_than_days * 86400
        with self._lock, self.db:
            return self.db.execute("DELETE FROM message WHERE ts < ? AND NOT (read=0 AND origin='live' AND "
                                   "direction='in')", (cutoff,)).rowcount

    def upsert_node(self, n: HubNode) -> None:
        check_protocol(n.protocol)
        vals = [getattr(n, c) for c in NODE_COLS]
        upd = ",".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in NODE_COLS[2:])
        with self._lock, self.db:
            self.db.execute(f"INSERT INTO node({','.join(NODE_COLS)}) VALUES({','.join('?' * len(NODE_COLS))}) "
                            f"ON CONFLICT(protocol, key) DO UPDATE SET {upd}", vals)

    def nodes(self, protocol: Optional[str] = None) -> list:
        q, a = f"SELECT {','.join(NODE_COLS)} FROM node", []
        if protocol:
            q += " WHERE protocol=?"
            a.append(check_protocol(protocol))
        with self._lock:
            rows = self.db.execute(q + " ORDER BY last_heard DESC", a).fetchall()
        return [dict(zip(NODE_COLS, r)) for r in rows]

    def node_names(self, protocol: str) -> dict:
        with self._lock:
            rows = self.db.execute("SELECT key, name FROM node WHERE protocol=? AND name<>''", (protocol,)).fetchall()
        return dict(rows)


def now() -> float:
    return time.time()
