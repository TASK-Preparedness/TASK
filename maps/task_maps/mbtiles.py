# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""MBTiles 1.3 storage (https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md).

* ``tiles(zoom_level, tile_column, tile_row, tile_data)`` with the **TMS** row (y flipped); the
  public API of this module always takes XYZ ``(z, x, y)`` and flips internally.
* ``metadata(name, value)``: name, format, bounds, center, minzoom, maxzoom, attribution,
  description, type, version, plus ``task_maps_source`` (source id) and ``task_maps_schema``.
* WAL journal; one writer (``TileWriter`` thread, batched transactions, periodic
  ``wal_checkpoint(PASSIVE)``), any number of read-only readers (one connection per thread).
* Tiles are validated (PNG / JPEG / WebP magic, size bounds) before they are stored; invalid
  bytes are rejected, never written.
* ``SQLITE_FULL`` (disk full) rolls the batch back and reports ``DiskFull``; the database stays
  consistent (SQLite's journal guarantees atomic commits).
"""

import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from task_maps.tilemath import xyz_to_tms

MIN_TILE_BYTES = 67           # smallest valid PNG is ~67 bytes
MAX_TILE_BYTES = 4 * 1024 * 1024
SCHEMA = "1"

PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff"


class MBTilesError(Exception):
    pass


class DiskFull(MBTilesError):
    pass


def sniff_format(data: bytes) -> str:
    if data[:8] == PNG:
        return "png"
    if data[:3] == JPEG:
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def validate_tile(data) -> str:
    """Return the image format or raise MBTilesError with the reason."""
    if not isinstance(data, (bytes, bytearray)):
        raise MBTilesError("tile is not bytes")
    if len(data) < MIN_TILE_BYTES:
        raise MBTilesError(f"tile too small ({len(data)} bytes)")
    if len(data) > MAX_TILE_BYTES:
        raise MBTilesError(f"tile too large ({len(data)} bytes)")
    fmt = sniff_format(bytes(data[:16]))
    if not fmt:
        raise MBTilesError("not a PNG, JPEG or WebP image")
    if fmt == "png" and b"IEND" not in bytes(data[-16:]):
        raise MBTilesError("truncated PNG (no IEND)")
    if fmt == "jpg" and not bytes(data).rstrip(b"\x00").endswith(b"\xff\xd9"):
        raise MBTilesError("truncated JPEG (no EOI)")
    return fmt


def is_disk_full(exc: Exception) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code == 13:   # SQLITE_FULL
        return True
    return "database or disk is full" in str(exc)


DDL = """
CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS name ON metadata (name);
CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);
CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row);
"""


def create(path, metadata: dict):
    """Create (or open) a writable MBTiles file and merge metadata. Returns nothing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    con = sqlite3.connect(str(path), timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(DDL)
        with con:
            md = dict(metadata)
            md.setdefault("task_maps_schema", SCHEMA)
            for k, v in md.items():
                con.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", (k, str(v)))
    finally:
        con.close()


def check(path, quick=True):
    """Open read-only and verify the MBTiles structure. Returns (ok, message, metadata)."""
    path = Path(path)
    if not path.is_file():
        return False, "file not found", {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        return False, f"cannot open: {exc}", {}
    try:
        try:
            res = con.execute("PRAGMA quick_check" if quick else "PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            return False, f"not an SQLite database: {exc}", {}
        if not res or res[0] != "ok":
            return False, f"integrity check failed: {res[0] if res else '?'}", {}
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "tiles" not in names or "metadata" not in names:
            return False, "not an MBTiles file (tables 'tiles' and 'metadata' required)", {}
        md = {k: v for k, v in con.execute("SELECT name, value FROM metadata") if isinstance(k, str)}
        fmt = (md.get("format") or "").lower()
        if fmt and fmt not in ("png", "jpg", "jpeg", "webp"):
            return False, f"unsupported tile format {fmt!r} (raster png/jpg/webp only)", md
        row = con.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()
        if row is None:
            return True, "valid, but contains no tiles", md
        if not sniff_format(bytes(row[0][:16]) if row[0] else b""):
            return False, "tiles are not PNG/JPEG/WebP images (vector MBTiles are not supported)", md
        return True, "ok", md
    except sqlite3.Error as exc:
        return False, f"error: {exc}", {}
    finally:
        con.close()


class Reader:
    """Read-only access. Create one per thread (sqlite connections are not shared)."""

    def __init__(self, path):
        self.path = Path(path)
        self.con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=10, check_same_thread=False)

    def close(self):
        try:
            self.con.close()
        except sqlite3.Error:
            pass

    def get(self, z, x, y):
        row = self.con.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                               (z, x, xyz_to_tms(z, y))).fetchone()
        return bytes(row[0]) if row else None

    def has(self, z, x, y) -> bool:
        return self.con.execute("SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                                (z, x, xyz_to_tms(z, y))).fetchone() is not None

    def metadata(self) -> dict:
        return {k: v for k, v in self.con.execute("SELECT name, value FROM metadata")}

    def zoom_range(self):
        r = self.con.execute("SELECT MIN(zoom_level), MAX(zoom_level) FROM tiles").fetchone()
        return (r[0], r[1]) if r and r[0] is not None else (None, None)

    def count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]

    def stats(self):
        r = self.con.execute("SELECT COUNT(*), COALESCE(AVG(LENGTH(tile_data)), 0) FROM tiles").fetchone()
        return int(r[0]), float(r[1])


@dataclass
class Write:
    z: int
    x: int
    y: int
    data: bytes
    on_done: object = None        # callable(ok: bool, error: str) called from the writer thread


@dataclass
class WriterStats:
    written: int = 0
    duplicates: int = 0
    rejected: int = 0
    commits: int = 0
    checkpoints: int = 0
    errors: list = field(default_factory=list)


class TileWriter(threading.Thread):
    """The only writer of one MBTiles file. ``put()`` queues tiles; they are committed in batches
    (``batch`` tiles or ``interval`` seconds). ``on_commit(list[(z, x, y)])`` is called after each
    commit with the tiles that became readable. On disk full the batch is rolled back, every
    queued write fails with "disk full" and ``on_disk_full(message)`` is called; the writer then
    refuses further writes until ``reset_full()``."""

    def __init__(self, path, batch=64, interval=0.5, checkpoint_every=20, on_commit=None, on_disk_full=None,
                 connect=sqlite3.connect):
        super().__init__(name=f"mbtiles-writer:{Path(path).name}", daemon=True)
        self.path = Path(path)
        self.batch, self.interval, self.checkpoint_every = batch, interval, checkpoint_every
        self.on_commit, self.on_disk_full = on_commit, on_disk_full
        self._connect = connect
        self.q = queue.Queue()
        self.stats = WriterStats()
        self.full = False
        self._stop_evt = threading.Event()
        self._idle = threading.Event()
        self._idle.set()

    def put(self, w: Write):
        self._idle.clear()
        self.q.put(w)

    def set_metadata(self, md: dict):
        """Queue a metadata update (written in order with the tiles)."""
        self._idle.clear()
        self.q.put(dict(md))

    def stop(self, timeout=10):
        self._stop_evt.set()
        self.q.put(None)
        self.join(timeout)

    def flush(self, timeout=10) -> bool:
        """Wait until everything queued so far is committed (tests and shutdown)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.q.empty() and self._idle.is_set():
                return True
            time.sleep(0.01)
        return False

    def reset_full(self):
        self.full = False

    def run(self):
        con = self._connect(str(self.path), timeout=30, check_same_thread=False)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            pending, deadline = [], None
            while True:
                timeout = None if not pending else max(0.0, deadline - time.monotonic())
                try:
                    item = self.q.get(timeout=timeout)
                except queue.Empty:
                    item = "tick"
                if item is None:
                    self._commit(con, pending)
                    pending = []
                    break
                if isinstance(item, dict):
                    self._commit(con, pending)
                    pending = []
                    self._write_meta(con, item)
                    if self.q.empty():
                        self._idle.set()
                    continue
                if item != "tick":
                    if not pending:
                        deadline = time.monotonic() + self.interval
                    pending.append(item)
                if pending and (len(pending) >= self.batch or item == "tick" or time.monotonic() >= deadline):
                    self._commit(con, pending)
                    pending = []
                if not pending and self.q.empty():
                    self._idle.set()
            try:
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass
        finally:
            con.close()
            self._idle.set()

    def _write_meta(self, con, md):
        try:
            with con:
                for k, v in md.items():
                    con.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)", (k, str(v)))
        except sqlite3.Error as exc:
            self.stats.errors.append(f"metadata: {exc}")
            if is_disk_full(exc):
                self.full = True
                if self.on_disk_full:
                    self.on_disk_full("disk full — the map file was not changed; free space and resume")

    def _commit(self, con, items):
        if not items:
            return
        if self.full:
            for w in items:
                self._done(w, False, "disk full")
            return
        accepted, done = [], []
        for w in items:
            try:
                validate_tile(w.data)
            except MBTilesError as exc:
                self.stats.rejected += 1
                done.append((w, False, f"invalid tile: {exc}"))
                continue
            accepted.append(w)
        committed = []
        try:
            con.execute("BEGIN IMMEDIATE")
            for w in accepted:
                cur = con.execute("INSERT OR IGNORE INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                                  "VALUES (?, ?, ?, ?)", (w.z, w.x, xyz_to_tms(w.z, w.y), sqlite3.Binary(w.data)))
                if cur.rowcount:
                    committed.append((w.z, w.x, w.y))
                    done.append((w, True, ""))
                else:
                    self.stats.duplicates += 1
                    done.append((w, True, "duplicate"))
            con.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            full = is_disk_full(exc)
            msg = "disk full — the map file was not changed; free space and resume" if full else f"database error: {exc}"
            self.stats.errors.append(msg)
            done = [(w, ok, err) for (w, ok, err) in done if not ok] + [(w, False, msg) for w in accepted]
            committed = []
            if full:
                self.full = True
                if self.on_disk_full:
                    self.on_disk_full(msg)
            for w, ok, err in done:
                self._done(w, ok, err)
            return
        self.stats.written += len(committed)
        self.stats.commits += 1
        if self.stats.commits % self.checkpoint_every == 0:
            try:
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                self.stats.checkpoints += 1
            except sqlite3.Error:
                pass
        for w, ok, err in done:
            self._done(w, ok, err)
        if committed and self.on_commit:
            self.on_commit(committed)

    @staticmethod
    def _done(w, ok, err):
        if w.on_done:
            try:
                w.on_done(ok, err)
            except Exception:   # noqa: BLE001 - a callback must not kill the writer
                pass
