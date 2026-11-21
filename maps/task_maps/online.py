# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""0.1.1 automatic online tiles + cache.

Lookup order for the "online" layer of a source: manual-region file ``maps/<source>.mbtiles`` (read-only;
e.g. the existing Pennsylvania USGS downloads) → auto cache ``cache/<source>.mbtiles`` → network.
Only sources whose terms permit offline use (``sources.download_permission``) auto-load or cache; refused hosts
never do. Only the visible tiles (+ a one-tile margin) are fetched, newest view first; requests that left the
view are dropped before sending; 429/503 back off with Retry-After. A NetworkError switches to offline mode
(no requests) and a probe every ``probe_s`` switches back automatically. Eviction touches only the cache file.
Maps never sends a position anywhere: tile URLs contain only z/x/y."""

import collections
import os
import sqlite3
import threading
import time
from pathlib import Path

from task_maps import mbtiles, net, sources
from task_maps.downloader import RateLimiter
from task_maps.mbtiles import MBTilesError, validate_tile, xyz_to_tms

PREFIX = "online:"
DEFAULT_CACHE_BYTES = 1 << 30
CACHE_DDL = """CREATE TABLE IF NOT EXISTS task_cache (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
  atime REAL, bytes INTEGER, PRIMARY KEY (zoom_level, tile_column, tile_row))"""


def layer_path(source_id: str) -> str:
    return PREFIX + source_id


def is_online(path: str) -> bool:
    return isinstance(path, str) and path.startswith(PREFIX)


class TileCacheFile:
    """The auto cache (separate file; the only file this module ever writes or evicts from)."""

    def __init__(self, path: Path, source, limit_bytes=DEFAULT_CACHE_BYTES, clock=time.time):
        self.path, self.limit, self.clock = Path(path), int(limit_bytes), clock
        mbtiles.create(self.path, {"name": f"{source.name} (auto cache)", "format": "png", "type": "baselayer",
                                   "attribution": source.attribution, "task_maps_role": "auto-cache"})
        os.chmod(self.path, 0o600)
        self.con = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self.con.execute(CACHE_DDL)
        self.con.commit()
        self.lock = threading.Lock()

    def get(self, z, x, y):
        with self.lock:
            row = self.con.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                                   (z, x, xyz_to_tms(z, y))).fetchone()
            if row:
                self.con.execute("UPDATE task_cache SET atime=? WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                                 (self.clock(), z, x, xyz_to_tms(z, y)))
                self.con.commit()
            return bytes(row[0]) if row else None

    def put(self, z, x, y, data: bytes):
        with self.lock:
            r = xyz_to_tms(z, y)
            self.con.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)", (z, x, r, sqlite3.Binary(data)))
            self.con.execute("INSERT OR REPLACE INTO task_cache VALUES (?,?,?,?,?)", (z, x, r, self.clock(), len(data)))
            self.con.commit()
            self._evict_locked()

    def size(self):
        with self.lock:
            return self.con.execute("SELECT COALESCE(SUM(bytes),0) FROM task_cache").fetchone()[0]

    def count(self):
        with self.lock:
            return self.con.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]

    def _evict_locked(self):
        total = self.con.execute("SELECT COALESCE(SUM(bytes),0) FROM task_cache").fetchone()[0]
        if total <= self.limit:
            return 0
        n = 0
        for z, x, r, b in self.con.execute("SELECT zoom_level,tile_column,tile_row,bytes FROM task_cache "
                                           "ORDER BY atime ASC").fetchall():
            if total <= self.limit:
                break
            self.con.execute("DELETE FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?", (z, x, r))
            self.con.execute("DELETE FROM task_cache WHERE zoom_level=? AND tile_column=? AND tile_row=?", (z, x, r))
            total -= b
            n += 1
        self.con.commit()
        return n

    def set_limit(self, limit_bytes):
        with self.lock:
            self.limit = int(limit_bytes)
            self._evict_locked()

    def clear(self):
        with self.lock:
            self.con.execute("DELETE FROM tiles")
            self.con.execute("DELETE FROM task_cache")
            self.con.commit()
            self.con.execute("VACUUM")

    def close(self):
        with self.lock:
            self.con.close()


class OnlineSource:
    """Resolves tiles for the online layer. ``on_tile(z, x, y, data_or_None, error)`` is called from worker
    threads when a network fetch finishes; ``on_network(online: bool, message)`` when the state flips."""

    def __init__(self, source, data_dir, fetch=net.fetch, ua="",
                 cache_bytes=DEFAULT_CACHE_BYTES, on_tile=None, on_network=None, probe_s=30.0, clock=time.monotonic,
                 api_key=""):
        ok, why = sources.download_permission(source, api_key)
        if not ok:
            raise sources.SourceError(f"{source.name}: automatic loading not permitted — {why}")
        self.source, self.fetch, self.api_key = source, fetch, api_key
        from task_maps import USER_AGENT
        self.ua = ua or USER_AGENT
        self.data_dir = Path(data_dir)
        self.manual_path = self.data_dir / "maps" / f"{source.id}.mbtiles"
        self.cache = TileCacheFile(self.data_dir / "cache" / f"{source.id}.mbtiles", source, cache_bytes)
        self.on_tile = on_tile or (lambda *a: None)
        self.on_network = on_network or (lambda *a: None)
        self.limiter = RateLimiter(source.rate_limit, clock)
        self.clock, self.probe_s = clock, probe_s
        self.online = True
        self._offline_since = None
        self.wanted = None                    # set of (z,x,y) or None (= everything requested)
        self._q = collections.deque()
        self._queued = set()
        self._inflight = set()
        self._cv = threading.Condition()
        self._stop = False
        self._hold_until = 0.0
        self.requests = 0
        self.errors = collections.Counter()
        self._manual = {}
        self._threads = [threading.Thread(target=self._run, name=f"online-{source.id}-{i}", daemon=True)
                         for i in range(max(1, min(source.max_concurrency, 4)))]
        for t in self._threads:
            t.start()

    @property
    def path(self):
        return layer_path(self.source.id)

    # ------------------------------------------------------------ local lookup (called by the tile loader)
    def _manual_reader(self):
        tid = threading.get_ident()
        r = self._manual.get(tid)
        if r is None and self.manual_path.exists():
            try:
                r = self._manual[tid] = mbtiles.Reader(self.manual_path)
            except sqlite3.Error:
                r = None
        return r

    def local(self, z, x, y):
        """(data, origin) from manual region file or cache; (None, None) if neither has it."""
        r = self._manual_reader()
        if r is not None:
            try:
                d = r.get(z, x, y)
            except sqlite3.Error:
                d = None
            if d is not None:
                return d, "manual"
        d = self.cache.get(z, x, y)
        return (d, "cache") if d is not None else (None, None)

    # ------------------------------------------------------------ network
    def set_wanted(self, keys):
        with self._cv:
            self.wanted = set(keys)
            # drop queued requests that left the view (before they are sent)
            self._q = collections.deque(k for k in self._q if k in self.wanted)
            self._queued = set(self._q)

    def request(self, z, x, y):
        """Queue a network fetch; returns False when offline (caller shows 'No offline coverage')."""
        if not (self.source.min_zoom <= z <= self.source.max_zoom):
            return False
        if not self.online and not self._probe_due():
            return False
        key = (z, x, y)
        with self._cv:
            if key in self._queued or key in self._inflight:
                return True
            self._q.append(key)
            self._queued.add(key)
            self._cv.notify()
        return True

    def _probe_due(self):
        return self._offline_since is not None and self.clock() - self._offline_since >= self.probe_s

    def _set_online(self, on, msg=""):
        if on == self.online:
            return
        self.online = on
        self._offline_since = None if on else self.clock()
        self.on_network(on, msg)

    def _run(self):
        while True:
            with self._cv:
                while not self._q and not self._stop:
                    self._cv.wait(0.5)
                if self._stop:
                    return
                key = self._q.pop()                      # newest first
                self._queued.discard(key)
                if self.wanted is not None and key not in self.wanted:
                    continue
                self._inflight.add(key)
            try:
                self._handle(key)
            finally:
                with self._cv:
                    self._inflight.discard(key)

    def _handle(self, key):
        if True:
            if not self.online and not self._probe_due():
                self.on_tile(*key, None, "offline")
                return
            hold = self._hold_until - self.clock()
            if hold > 0:
                time.sleep(min(hold, 5))
            wait = self.limiter.reserve()
            if wait > 0:
                time.sleep(wait)
            with self._cv:
                if self._stop or (self.wanted is not None and key not in self.wanted):
                    return
            self._fetch(*key)

    def _fetch(self, z, x, y):
        url = self.source.tile_url(z, x, y, self.api_key)
        self.requests += 1
        try:
            resp = self.fetch(url, self.ua)
        except net.NetworkError as exc:
            self.errors["network"] += 1
            if self.online:
                self._set_online(False, f"offline: {self.source.redact(str(exc), self.api_key)[:120]}")
            else:
                self._offline_since = self.clock()      # probe failed: wait another period
            self.on_tile(z, x, y, None, "offline")
            return
        except Exception as exc:  # noqa: BLE001 — a fetch bug must never crash Maps
            self.errors["internal"] += 1
            self.on_tile(z, x, y, None, f"error: {str(exc)[:80]}")
            return
        self._set_online(True, "online")
        if resp.status == 200:
            try:
                validate_tile(resp.body)
            except MBTilesError as exc:
                self.errors["corrupt"] += 1
                self.on_tile(z, x, y, None, f"corrupt: {exc}")
                return
            try:
                self.cache.put(z, x, y, resp.body)
            except sqlite3.Error as exc:
                self.errors["cache"] += 1
                self.on_tile(z, x, y, resp.body, f"cache write failed: {exc}")
                return
            self.on_tile(z, x, y, resp.body, "")
            return
        if resp.status in (429, 503):
            self.errors[str(resp.status)] += 1
            self._hold_until = self.clock() + net.retry_after(resp.headers, default=10.0)
            self.on_tile(z, x, y, None, f"busy: HTTP {resp.status}")
            return
        self.errors[str(resp.status)] += 1
        self.on_tile(z, x, y, None, "missing" if resp.status in (204, 404) else f"HTTP {resp.status}")

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        for t in self._threads:
            t.join(2)
        for r in self._manual.values():
            r.close()
        self.cache.close()
