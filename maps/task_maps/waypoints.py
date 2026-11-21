# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Waypoint and track store (``<data dir>/waypoints.sqlite``).

Field set follows docs/MISSION-PLANNER-INTERFACE.md §1 (rain:id UUIDv4, rain:source, created,
modified, accuracy, mission, status). GPX import/export lives in ``gpx.py``. This store is the
local, single-user implementation; the IPC socket of the interface document is not part of
task-maps 0.1.0.
"""

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field

from task_maps.tilemath import haversine_m

DDL = """
CREATE TABLE IF NOT EXISTS waypoints (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, ele REAL, time TEXT,
  desc TEXT DEFAULT '', sym TEXT DEFAULT '', type TEXT DEFAULT '', source TEXT DEFAULT 'manual',
  accuracy_m REAL, mission TEXT DEFAULT '', status TEXT DEFAULT '', created REAL, modified REAL);
CREATE TABLE IF NOT EXISTS tracks (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT DEFAULT 'gps', created REAL, modified REAL,
  recording INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS track_points (
  track_id TEXT, seq INTEGER, lat REAL, lon REAL, ele REAL, time TEXT, speed REAL, accuracy_m REAL,
  PRIMARY KEY (track_id, seq));
CREATE TABLE IF NOT EXISTS info (k TEXT PRIMARY KEY, v TEXT);
"""
SOURCES = ("manual", "gps", "map")
MAX_NAME = 40


def _valid(lat, lon):
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        raise ValueError("coordinates must be numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("latitude must be -90..90 and longitude -180..180")


def _name(name):
    name = "".join(c for c in str(name) if c.isprintable()).strip()[:MAX_NAME]
    if not name:
        raise ValueError("name is empty")
    return name


@dataclass
class Waypoint:
    id: str
    name: str
    lat: float
    lon: float
    ele: float = None
    time: str = ""
    desc: str = ""
    sym: str = ""
    type: str = ""
    source: str = "manual"
    accuracy_m: float = None
    mission: str = ""
    status: str = ""
    created: float = 0.0
    modified: float = 0.0


@dataclass
class TrackPoint:
    lat: float
    lon: float
    ele: float = None
    time: str = ""
    speed: float = None
    accuracy_m: float = None


@dataclass
class Track:
    id: str
    name: str
    source: str = "gps"
    created: float = 0.0
    modified: float = 0.0
    recording: bool = False
    points: list = field(default_factory=list)

    def length_m(self):
        return sum(haversine_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(self.points, self.points[1:]))


WP_COLS = "id, name, lat, lon, ele, time, desc, sym, type, source, accuracy_m, mission, status, created, modified"


class Store:
    def __init__(self, path, clock=time.time):
        self.path = str(path)
        self.clock = clock
        self._lock = threading.RLock()
        self.con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(DDL)
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO info VALUES ('revision', '0')")

    def close(self):
        with self._lock:
            self.con.close()

    def revision(self) -> int:
        with self._lock:
            return int(self.con.execute("SELECT v FROM info WHERE k='revision'").fetchone()[0])

    def _bump(self):
        self.con.execute("UPDATE info SET v = CAST(v AS INTEGER) + 1 WHERE k='revision'")

    # ------------------------------------------------------------ waypoints
    def add_waypoint(self, name, lat, lon, ele=None, source="manual", accuracy_m=None, desc="", sym="",
                     time_iso="", wid=None) -> Waypoint:
        _valid(lat, lon)
        now = self.clock()
        wp = Waypoint(wid or str(uuid.uuid4()), _name(name), float(lat), float(lon), ele, time_iso, desc[:500], sym[:40],
                      "", source if source in SOURCES or source.startswith("import:") else "manual", accuracy_m,
                      created=now, modified=now)
        with self._lock, self.con:
            self.con.execute(f"INSERT OR REPLACE INTO waypoints ({WP_COLS}) VALUES ({','.join('?' * 15)})",
                             (wp.id, wp.name, wp.lat, wp.lon, wp.ele, wp.time, wp.desc, wp.sym, wp.type, wp.source,
                              wp.accuracy_m, wp.mission, wp.status, wp.created, wp.modified))
            self._bump()
        return wp

    def waypoints(self):
        with self._lock:
            rows = self.con.execute(f"SELECT {WP_COLS} FROM waypoints ORDER BY created").fetchall()
        return [Waypoint(*r) for r in rows]

    def get_waypoint(self, wid):
        with self._lock:
            r = self.con.execute(f"SELECT {WP_COLS} FROM waypoints WHERE id=?", (wid,)).fetchone()
        return Waypoint(*r) if r else None

    def update_waypoint(self, wid, name=None, lat=None, lon=None, desc=None):
        wp = self.get_waypoint(wid)
        if wp is None:
            raise KeyError(wid)
        nlat = wp.lat if lat is None else lat
        nlon = wp.lon if lon is None else lon
        _valid(nlat, nlon)
        with self._lock, self.con:
            self.con.execute("UPDATE waypoints SET name=?, lat=?, lon=?, desc=?, modified=? WHERE id=?",
                             (_name(name) if name is not None else wp.name, float(nlat), float(nlon),
                              (desc if desc is not None else wp.desc)[:500], self.clock(), wid))
            self._bump()
        return self.get_waypoint(wid)

    def delete_waypoint(self, wid):
        with self._lock, self.con:
            self.con.execute("DELETE FROM waypoints WHERE id=?", (wid,))
            self._bump()

    # ------------------------------------------------------------ tracks
    def start_track(self, name) -> Track:
        now = self.clock()
        t = Track(str(uuid.uuid4()), _name(name), "gps", now, now, True)
        with self._lock, self.con:
            self.con.execute("UPDATE tracks SET recording=0 WHERE recording=1")
            self.con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,1)", (t.id, t.name, t.source, now, now))
            self._bump()
        return t

    def stop_track(self, tid):
        with self._lock, self.con:
            self.con.execute("UPDATE tracks SET recording=0, modified=? WHERE id=?", (self.clock(), tid))
            self._bump()

    def add_track(self, name, points, source="import") -> Track:
        now = self.clock()
        t = Track(str(uuid.uuid4()), _name(name), source[:60], now, now, False)
        with self._lock, self.con:
            self.con.execute("INSERT INTO tracks VALUES (?,?,?,?,?,0)", (t.id, t.name, t.source, now, now))
            for i, p in enumerate(points):
                _valid(p.lat, p.lon)
                self.con.execute("INSERT INTO track_points VALUES (?,?,?,?,?,?,?,?)",
                                 (t.id, i, p.lat, p.lon, p.ele, p.time, p.speed, p.accuracy_m))
            self._bump()
        return t

    def append_point(self, tid, p: TrackPoint):
        _valid(p.lat, p.lon)
        with self._lock, self.con:
            seq = self.con.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM track_points WHERE track_id=?",
                                   (tid,)).fetchone()[0]
            self.con.execute("INSERT INTO track_points VALUES (?,?,?,?,?,?,?,?)",
                             (tid, seq, p.lat, p.lon, p.ele, p.time, p.speed, p.accuracy_m))
            self.con.execute("UPDATE tracks SET modified=? WHERE id=?", (self.clock(), tid))

    def tracks(self, with_points=True):
        with self._lock:
            rows = self.con.execute("SELECT id, name, source, created, modified, recording FROM tracks "
                                    "ORDER BY created").fetchall()
            out = []
            for r in rows:
                t = Track(r[0], r[1], r[2], r[3], r[4], bool(r[5]))
                if with_points:
                    t.points = [TrackPoint(*p) for p in self.con.execute(
                        "SELECT lat, lon, ele, time, speed, accuracy_m FROM track_points WHERE track_id=? ORDER BY seq",
                        (t.id,))]
                out.append(t)
        return out

    def recording_track(self):
        return next((t for t in self.tracks(with_points=False) if t.recording), None)

    def rename_track(self, tid, name):
        with self._lock, self.con:
            self.con.execute("UPDATE tracks SET name=?, modified=? WHERE id=?", (_name(name), self.clock(), tid))
            self._bump()

    def delete_track(self, tid):
        with self._lock, self.con:
            self.con.execute("DELETE FROM track_points WHERE track_id=?", (tid,))
            self.con.execute("DELETE FROM tracks WHERE id=?", (tid,))
            self._bump()


class TrackFilter:
    """Decides whether a GPS fix becomes a track point: needs a 2D/3D fix, accuracy better than
    ``max_accuracy_m`` (when reported), and either ``min_distance_m`` moved or ``max_interval_s``
    elapsed with at least ``min_moved_m`` movement (so a parked receiver does not fill the track
    with jitter)."""

    def __init__(self, min_distance_m=10.0, max_interval_s=30.0, min_moved_m=3.0, max_accuracy_m=50.0):
        self.min_distance_m, self.max_interval_s = min_distance_m, max_interval_s
        self.min_moved_m, self.max_accuracy_m = min_moved_m, max_accuracy_m
        self.last = None          # (lat, lon, t)

    def reset(self):
        self.last = None

    def accept(self, lat, lon, t, mode=3, accuracy_m=None) -> bool:
        if mode < 2 or lat is None or lon is None:
            return False
        if accuracy_m is not None and accuracy_m > self.max_accuracy_m:
            return False
        if self.last is None:
            self.last = (lat, lon, t)
            return True
        d = haversine_m(self.last[0], self.last[1], lat, lon)
        if d >= self.min_distance_m or (t - self.last[2] >= self.max_interval_s and d >= self.min_moved_m):
            self.last = (lat, lon, t)
            return True
        return False
