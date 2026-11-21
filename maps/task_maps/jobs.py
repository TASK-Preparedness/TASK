# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Persistent download-job queue (``<data dir>/jobs.sqlite``).

A job is a region (bbox + zoom range) of one source. Tiles go to the source's single MBTiles
file (``maps/<source id>.mbtiles``), so overlapping regions never duplicate tiles; the job row
is the region metadata. Progress is a **range cursor** over the deterministic tile order of
``tilemath.iter_tiles``: every tile before ``cursor`` is finished (stored, already present, or
recorded in ``failed_tiles``). Tiles that were in flight when the program stopped are simply
fetched again on resume; the existence check and ``INSERT OR IGNORE`` make that harmless.
"""

import sqlite3
import threading
import time
from dataclasses import dataclass

from task_maps.tilemath import BBox

ACTIVE = ("queued", "running", "paused", "waiting-network", "paused-disk", "interrupted")
FINISHED = ("completed", "completed-with-errors", "cancelled")
STATE_TEXT = {
    "queued": "Queued", "running": "Downloading", "paused": "Paused", "waiting-network": "Waiting for network",
    "paused-disk": "Paused — storage", "interrupted": "Interrupted (resume?)", "completed": "Completed",
    "completed-with-errors": "Completed with failed tiles", "cancelled": "Cancelled",
}

DDL = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, name TEXT NOT NULL,
  west REAL, south REAL, east REAL, north REAL, minz INTEGER, maxz INTEGER,
  total INTEGER, cursor INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0, state TEXT NOT NULL, message TEXT DEFAULT '',
  map_path TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS failed_tiles (
  job_id INTEGER, z INTEGER, x INTEGER, y INTEGER, attempts INTEGER, error TEXT, at REAL,
  PRIMARY KEY (job_id, z, x, y));
CREATE TABLE IF NOT EXISTS info (k TEXT PRIMARY KEY, v TEXT);
"""


class DuplicateJob(ValueError):
    pass


@dataclass
class Job:
    id: int
    source_id: str
    name: str
    bbox: BBox
    minz: int
    maxz: int
    total: int
    cursor: int
    downloaded: int
    skipped: int
    failed: int
    bytes: int
    state: str
    message: str
    map_path: str
    created: float
    updated: float

    @property
    def active(self):
        return self.state in ACTIVE

    @property
    def finished_count(self):
        return self.cursor

    def state_text(self):
        return STATE_TEXT.get(self.state, self.state)


def _job(row) -> Job:
    (i, sid, name, w, s, e, n, minz, maxz, total, cursor, dl, sk, fl, by, st, msg, mp, cr, up) = row
    return Job(i, sid, name, BBox(w, s, e, n), minz, maxz, total, cursor, dl, sk, fl, by, st, msg, mp, cr, up)


COLS = ("id, source_id, name, west, south, east, north, minz, maxz, total, cursor, downloaded, skipped, failed, "
        "bytes, state, message, map_path, created, updated")


class JobStore:
    def __init__(self, path, clock=time.time):
        self.path = str(path)
        self.clock = clock
        self._lock = threading.RLock()
        self.con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        with self._lock:
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.executescript(DDL)

    def close(self):
        with self._lock:
            self.con.close()

    def _one(self, sql, args=()):
        with self._lock:
            return self.con.execute(sql, args).fetchone()

    def create(self, source_id, name, bbox: BBox, minz, maxz, total, map_path) -> Job:
        b = bbox.normalized()
        with self._lock:
            dup = self.con.execute(
                f"SELECT {COLS} FROM jobs WHERE source_id=? AND minz=? AND maxz=? AND abs(west-?)<1e-9 AND "
                "abs(south-?)<1e-9 AND abs(east-?)<1e-9 AND abs(north-?)<1e-9 AND state IN (%s)"
                % ",".join("?" * len(ACTIVE)), (source_id, minz, maxz, *b.as_tuple(), *ACTIVE)).fetchone()
            if dup:
                raise DuplicateJob(f"the same download already exists (job {dup[0]}, {STATE_TEXT.get(dup[15], dup[15])})")
            now = self.clock()
            with self.con:
                cur = self.con.execute(
                    "INSERT INTO jobs (source_id, name, west, south, east, north, minz, maxz, total, state, map_path, "
                    "created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (source_id, name, *b.as_tuple(), minz, maxz, total, "queued", str(map_path), now, now))
            return self.get(cur.lastrowid)

    def get(self, job_id) -> Job:
        r = self._one(f"SELECT {COLS} FROM jobs WHERE id=?", (job_id,))
        return _job(r) if r else None

    def list(self, include_finished=True):
        with self._lock:
            rows = self.con.execute(f"SELECT {COLS} FROM jobs ORDER BY id DESC").fetchall()
        jobs = [_job(r) for r in rows]
        return jobs if include_finished else [j for j in jobs if j.active]

    def set_state(self, job_id, state, message=""):
        with self._lock, self.con:
            self.con.execute("UPDATE jobs SET state=?, message=?, updated=? WHERE id=?",
                             (state, message, self.clock(), job_id))

    def checkpoint(self, job_id, cursor, downloaded, skipped, failed, nbytes):
        with self._lock, self.con:
            self.con.execute("UPDATE jobs SET cursor=?, downloaded=?, skipped=?, failed=?, bytes=?, updated=? WHERE id=?",
                             (cursor, downloaded, skipped, failed, nbytes, self.clock(), job_id))

    def record_failed(self, job_id, z, x, y, attempts, error):
        with self._lock, self.con:
            self.con.execute("INSERT OR REPLACE INTO failed_tiles VALUES (?,?,?,?,?,?,?)",
                             (job_id, z, x, y, attempts, error[:300], self.clock()))

    def clear_failed(self, job_id, z, x, y):
        with self._lock, self.con:
            self.con.execute("DELETE FROM failed_tiles WHERE job_id=? AND z=? AND x=? AND y=?", (job_id, z, x, y))

    def failed_tiles(self, job_id=None, source_id=None, limit=100000):
        with self._lock:
            if job_id is not None:
                return self.con.execute("SELECT z, x, y, attempts, error FROM failed_tiles WHERE job_id=? LIMIT ?",
                                        (job_id, limit)).fetchall()
            return self.con.execute("SELECT f.z, f.x, f.y, f.attempts, f.error FROM failed_tiles f JOIN jobs j "
                                    "ON j.id=f.job_id WHERE j.source_id=? LIMIT ?", (source_id, limit)).fetchall()

    def recover_after_restart(self):
        """Jobs that were running when the program stopped become 'interrupted' (resume prompt)."""
        with self._lock, self.con:
            self.con.execute("UPDATE jobs SET state='interrupted', message='the program stopped during this download' "
                             "WHERE state IN ('running', 'waiting-network')")
        return [j for j in self.list() if j.state == "interrupted"]

    def delete(self, job_id):
        with self._lock, self.con:
            self.con.execute("DELETE FROM failed_tiles WHERE job_id=?", (job_id,))
            self.con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
