# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-geofeed/1: per-producer SQLite position feeds read by task-maps (docs/GEOFEED.md).

Writer: one per producer, $XDG_DATA_HOME/task-comms/feeds/<producer>.sqlite, WAL, mode 0600.
Reader: opens read-only (mode=ro URI); a missing or corrupt feed is an empty layer.
Positions are only what was received/observed; nothing is invented (unknown -> NULL).
"""

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from task_comms import paths

SCHEMA = 1
KINDS = ("observed", "inferred")
_PRODUCER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS entity(id TEXT PRIMARY KEY, layer TEXT NOT NULL, label TEXT, lat REAL NOT NULL,
  lon REAL NOT NULL, alt_m REAL, accuracy_m REAL, observed_ts INTEGER NOT NULL, source TEXT NOT NULL,
  kind TEXT NOT NULL, stale_after_s INTEGER, attrs_json TEXT);
"""


@dataclass
class Entity:
    id: str
    layer: str
    label: str
    lat: float
    lon: float
    observed_ts: int
    source: str
    kind: str = "observed"
    alt_m: float = None
    accuracy_m: float = None
    stale_after_s: int = 3600
    attrs: dict = None


def feed_path(producer: str, directory: Path = None) -> Path:
    if not _PRODUCER.match(producer):
        raise ValueError("bad producer id")
    return (Path(directory) if directory else paths.feeds_dir()) / f"{producer}.sqlite"


class FeedWriter:
    def __init__(self, producer: str, directory: Path = None, clock=time.time):
        self.path = feed_path(producer, directory)
        self.producer, self.clock = producer, clock
        paths.private_dir(self.path.parent)
        new = not self.path.exists()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)  # callers serialise writes
        if new:
            os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(DDL)
        self.db.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)",
                            [("schema", str(SCHEMA)), ("producer", producer)])
        self._touch()

    def _touch(self):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('updated_ts', ?)", (str(int(self.clock())),))
        self.db.commit()

    def upsert(self, e: Entity):
        if e.kind not in KINDS:
            raise ValueError("kind must be observed or inferred")
        if not (-90 <= e.lat <= 90 and -180 <= e.lon <= 180):
            raise ValueError("position out of range")
        self.db.execute("INSERT OR REPLACE INTO entity VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (e.id, e.layer, e.label, e.lat, e.lon, e.alt_m, e.accuracy_m, int(e.observed_ts),
                         e.source, e.kind, e.stale_after_s, json.dumps(e.attrs or {}, sort_keys=True)))
        self._touch()

    def remove(self, entity_id: str):
        self.db.execute("DELETE FROM entity WHERE id=?", (entity_id,))
        self._touch()

    def clear(self):
        self.db.execute("DELETE FROM entity")
        self._touch()

    def close(self):
        self.db.close()


def read_feed(path: Path, clock=time.time):
    """(updated_ts or None, [dict]) — never raises for missing/corrupt files."""
    path = Path(path)
    if not path.is_file():
        return None, []
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.5)
        try:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
            if meta.get("schema") != str(SCHEMA):
                return None, []
            rows = db.execute("SELECT id, layer, label, lat, lon, alt_m, accuracy_m, observed_ts, source, kind,"
                              " stale_after_s, attrs_json FROM entity").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None, []
    now = clock()
    out = []
    for r in rows:
        d = dict(zip(("id", "layer", "label", "lat", "lon", "alt_m", "accuracy_m", "observed_ts", "source",
                      "kind", "stale_after_s"), r[:11]))
        try:
            d["attrs"] = json.loads(r[11] or "{}")
        except ValueError:
            d["attrs"] = {}
        d["stale"] = d["stale_after_s"] is not None and now - d["observed_ts"] > d["stale_after_s"]
        out.append(d)
    try:
        updated = int(meta.get("updated_ts"))
    except (TypeError, ValueError):
        updated = None
    return updated, out


def list_feeds(directory: Path = None):
    d = Path(directory) if directory else paths.feeds_dir()
    return sorted(d.glob("*.sqlite")) if d.is_dir() else []
