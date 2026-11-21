# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Non-mutating read-only access to the Resources index (task-resources 0.2.3).

Why 0.2.2 left -wal/-shm files: the index is a WAL-mode database (PRAGMA journal_mode=WAL is persistent in the
file header). A WAL reader needs the -shm wal-index; SQLite (>= 3.22) can open a WAL database read-only only if
(1) -shm and -wal already exist, (2) it may create them (writable directory), or (3) the file is opened
`immutable=1`. With mode=ro and absent side files, SQLite takes route (2) and creates them; a read-only
connection cannot checkpoint, so it can never delete them again. The main database file is not changed.

Options considered:
* immutable=1 on the live file - creates nothing, but UNSAFE while Resources writes concurrently (SQLite then
  skips all locking and change detection; a reader can see torn pages).
* mode=ro on the live file - safe with a concurrent writer (normal WAL locking), but creates -wal/-shm when
  they are absent.
* private snapshot copy - creates nothing next to the index; verified consistent (the copy must hash equal to
  the source re-read after copying, and the side files must not appear/change), else retried / live;
  shows the index as of open time (Refresh re-snapshots); costs one copy of the index file per open.

Rule used here (a WAL database with ANY open connection always has its -wal file; an open connection in
NORMAL locking mode always has -shm):
* no -wal              -> nobody has the index open -> SNAPSHOT copy of the main file (verified stable).
* -wal and -shm        -> a writer may be live       -> LIVE mode=ro (both exist, so nothing is created).
* -wal without -shm    -> crash leftover, no live connection -> SNAPSHOT copy of db + wal (SQLite recovers
                          the COPY; the original files are untouched).
The snapshot is opened `immutable=1` (it is our private file; nobody else can write it) or, when a copied WAL
must be recovered, read-write inside the private directory. Side files are never deleted from the index
directory; only our own snapshot directory is removed on close."""

import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

PREFIX = "task-ro-snapshot-"
MAX_SNAPSHOT_BYTES = 1 << 30      # above this, fall back to LIVE mode=ro (documented)
RETRIES = 3


def _sig(p):
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _digest(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def _tmp_root():
    rt = os.environ.get("XDG_RUNTIME_DIR")
    return rt if rt and os.path.isdir(rt) and os.access(rt, os.W_OK) else tempfile.gettempdir()


def sweep_stale(root=None):
    """Remove OUR OWN abandoned snapshot dirs (owner = us, creating pid gone). Never touches anything else."""
    root = Path(root or _tmp_root())
    for d in root.glob(PREFIX + "*"):
        try:
            pid = int(d.name[len(PREFIX):].split("-", 1)[0])
            if d.is_dir() and d.stat().st_uid == os.getuid() and not Path(f"/proc/{pid}").exists():
                shutil.rmtree(d, ignore_errors=True)
        except (ValueError, OSError):
            continue


class ReadOnlyHandle:
    """.conn (sqlite3.Connection), .mode ('snapshot' | 'live'), .close() (idempotent)."""

    def __init__(self, path, check_same_thread=False, timeout=10):
        self.path = Path(path)
        self.mode = None
        self.snapdir = None
        self.conn = None
        self.closed = False
        if not self.path.is_file():
            raise FileNotFoundError(f"no T.A.S.K. Resources index at {self.path}")
        sweep_stale()
        kw = dict(uri=True, check_same_thread=check_same_thread, timeout=timeout)
        for _ in range(RETRIES):
            wal, shm = Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")
            if wal.exists() and shm.exists() or self.path.stat().st_size > MAX_SNAPSHOT_BYTES:
                self.mode = "live"
                self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", **kw)
                return
            if self._snapshot(wal, kw):
                return
            time.sleep(0.05)
        # a writer kept changing the files while we copied: join it live (both side files exist now)
        self.mode = "live"
        self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", **kw)

    def _snapshot(self, wal, kw):
        shm = Path(str(self.path) + "-shm")
        before = (_sig(self.path), _sig(wal), shm.exists())
        d = Path(tempfile.mkdtemp(prefix=f"{PREFIX}{os.getpid()}-", dir=_tmp_root()))
        os.chmod(d, 0o700)
        dst = d / "index.sqlite"
        try:
            shutil.copyfile(self.path, dst)
            has_wal = before[1] is not None
            if has_wal:
                shutil.copyfile(wal, str(dst) + "-wal")
            after = (_sig(self.path), _sig(wal), shm.exists())
            # Content check: the copy must equal the source as re-read AFTER the copy. A torn copy (writer
            # checkpointing mid-copy) can never match; stat alone is not enough (coarse mtimes, same size).
            same = after == before and _digest(self.path) == _digest(dst) and (
                not has_wal or _digest(wal) == _digest(str(dst) + "-wal"))
            if not same:                           # a writer opened/changed it while we copied: retry
                shutil.rmtree(d, ignore_errors=True)
                return False
            if has_wal:
                conn = sqlite3.connect(str(dst), **{k: v for k, v in kw.items() if k != "uri"})
            else:
                conn = sqlite3.connect(f"file:{dst}?immutable=1", **kw)
            conn.execute("PRAGMA query_only=ON")
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        self.snapdir, self.conn, self.mode = d, conn, "snapshot"
        self.source_sig = (before[0], before[1])
        return True

    def stale(self):
        """Snapshot only: has the index (or its WAL) changed since the copy? Live connections are never stale.
        Freshness hint for Refresh, not a consistency check (consistency is verified at copy time)."""
        if self.mode != "snapshot":
            return False
        return (_sig(self.path), _sig(Path(str(self.path) + "-wal"))) != self.source_sig

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.conn is not None:
                self.conn.close()
        finally:
            if self.snapdir is not None:
                shutil.rmtree(self.snapdir, ignore_errors=True)
                self.snapdir = None


def consistent_backup(src, dst):
    """Single-file, consistent copy of a WAL database for installers/backups (db+wal+shm treated as one set).
    Uses the same rule: quiescent -> snapshot copy (+ checkpoint inside the copy); live -> SQLite backup API
    through a mode=ro connection (both side files already exist, so nothing is created). dst gets no -wal."""
    h = ReadOnlyHandle(src)
    try:
        out = sqlite3.connect(str(dst))
        try:
            h.conn.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")
        finally:
            out.close()
        return h.mode
    finally:
        h.close()
