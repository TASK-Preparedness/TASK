# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only position overlays from the T.A.S.K. geofeed files written by task-aprs / task-mesh
(``$XDG_DATA_HOME/task-comms/feeds/<producer>.sqlite``, schema task-geofeed/1). Maps never writes them and
never sends anything; a missing or corrupt feed only empties that overlay."""

import os
import sqlite3
import time
from pathlib import Path

FEEDS = {"aprs": "task-aprs", "mesh": "task-mesh", "gmrs": "task-aprs"}
LAYER_OF = {"aprs": "aprs", "mesh": "mesh", "gmrs": "gmrs"}


def feeds_dir() -> Path:
    v = os.environ.get("XDG_DATA_HOME", "")
    base = Path(v) if v.startswith("/") else Path.home() / ".local/share"
    return base / "task-comms" / "feeds"


def read(producer, layer, directory=None, clock=time.time, limit=5000):
    path = Path(directory or feeds_dir()) / f"{producer}.sqlite"
    if not path.is_file():
        return []
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.3)
        try:
            if dict(db.execute("SELECT key, value FROM meta").fetchall()).get("schema") != "1":
                return []
            rows = db.execute("SELECT id,label,lat,lon,observed_ts,source,kind,stale_after_s FROM entity "
                              "WHERE layer=? LIMIT ?", (layer, limit)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []
    now = clock()
    out = []
    for i, label, lat, lon, ts, src, kind, stale in rows:
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        out.append({"id": i, "label": label, "lat": lat, "lon": lon, "observed_ts": ts, "source": src,
                    "kind": kind, "stale": stale is not None and now - ts > stale})
    return out


def read_all(directory=None, clock=time.time):
    return {name: read(FEEDS[name], LAYER_OF[name], directory, clock) for name in FEEDS}
