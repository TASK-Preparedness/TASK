# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Private message history: $XDG_DATA_HOME/task-mesh/messages.sqlite3 (dir 0700, file 0600).

Opened only after a successful Core sign-in and closed when the session ends. Protection is
Unix permissions only (same-uid processes can read it) — documented limitation (r2 §9).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

DDL = """
CREATE TABLE IF NOT EXISTS message(
  local_id INTEGER PRIMARY KEY AUTOINCREMENT,
  direction TEXT NOT NULL CHECK(direction IN ('in','out')),
  channel INTEGER NOT NULL,
  peer TEXT NOT NULL,            -- '!xxxxxxxx' for DMs, '^all' for channel broadcasts
  from_id TEXT NOT NULL,
  text TEXT NOT NULL,
  ts INTEGER NOT NULL,
  packet_id INTEGER,
  state TEXT NOT NULL,
  detail TEXT,
  via_mqtt INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS message_peer ON message(channel, peer, ts);
CREATE INDEX IF NOT EXISTS message_packet ON message(packet_id);
"""
COLUMNS = ("local_id", "direction", "channel", "peer", "from_id", "text", "ts", "packet_id", "state", "detail", "via_mqtt")


class MessageStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._db: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._db is not None

    def open(self) -> None:
        with self._lock:
            if self._db is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
            db = sqlite3.connect(str(self.path), check_same_thread=False)
            db.executescript(DDL)
            self._db = db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def _need(self) -> sqlite3.Connection:
        if self._db is None:
            raise PermissionError("message history is locked (sign in)")
        return self._db

    def add(self, **row) -> int:
        with self._lock:
            db = self._need()
            cols = [c for c in COLUMNS if c != "local_id" and c in row]
            cur = db.execute(f"INSERT INTO message({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                             [row[c] for c in cols])
            db.commit()
            return cur.lastrowid

    def update(self, local_id: int, **fields) -> None:
        with self._lock:
            db = self._need()
            sets = ",".join(f"{k}=?" for k in fields)
            db.execute(f"UPDATE message SET {sets} WHERE local_id=?", [*fields.values(), local_id])
            db.commit()

    def get(self, local_id: int) -> Optional[dict]:
        with self._lock:
            r = self._need().execute(f"SELECT {','.join(COLUMNS)} FROM message WHERE local_id=?", (local_id,)).fetchone()
        return dict(zip(COLUMNS, r)) if r else None

    def conversation(self, channel: int, peer: str, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._need().execute(
                f"SELECT {','.join(COLUMNS)} FROM message WHERE channel=? AND peer=? ORDER BY ts, local_id LIMIT ?",
                (channel, peer, limit)).fetchall()
        return [dict(zip(COLUMNS, r)) for r in rows]

    def conversations(self) -> list[dict]:
        with self._lock:
            rows = self._need().execute(
                "SELECT channel, peer, COUNT(*), MAX(ts) FROM message GROUP BY channel, peer ORDER BY MAX(ts) DESC"
            ).fetchall()
        return [{"channel": c, "peer": p, "count": n, "last_ts": t} for c, p, n, t in rows]

    def pending(self) -> list[dict]:
        with self._lock:
            rows = self._need().execute(
                f"SELECT {','.join(COLUMNS)} FROM message WHERE direction='out' AND state IN ('queued','sent','relayed')"
            ).fetchall()
        return [dict(zip(COLUMNS, r)) for r in rows]
