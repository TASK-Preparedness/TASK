# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Private APRS/GMRS message history (sqlite, dir 0700 / file 0600). Opened only after Core sign-in."""

import os
import sqlite3
from pathlib import Path

from task_comms import paths

DDL = """CREATE TABLE IF NOT EXISTS msg(id INTEGER PRIMARY KEY, ts REAL, service TEXT, direction TEXT,
  peer TEXT, text TEXT, msg_id TEXT, state TEXT, via TEXT)"""


class History:
    def __init__(self, path: Path = None):
        self.path = Path(path) if path else paths.data_dir("task-aprs") / "messages.sqlite3"
        paths.private_dir(self.path.parent)
        new = not self.path.exists()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        if new:
            os.chmod(self.path, 0o600)
        self.db.execute(DDL)
        self.db.commit()

    def add(self, ts, service, direction, peer, text, msg_id="", state="", via="RF"):
        cur = self.db.execute("INSERT INTO msg(ts,service,direction,peer,text,msg_id,state,via) VALUES(?,?,?,?,?,?,?,?)",
                              (ts, service, direction, peer, text, msg_id, state, via))
        self.db.commit()
        return cur.lastrowid

    def set_state(self, row, state):
        self.db.execute("UPDATE msg SET state=? WHERE id=?", (state, row))
        self.db.commit()

    def list(self, service, limit=500):
        return self.db.execute("SELECT id,ts,direction,peer,text,msg_id,state,via FROM msg WHERE service=? "
                               "ORDER BY ts DESC LIMIT ?", (service, limit)).fetchall()

    def close(self):
        self.db.close()
