# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-resources 0.2.3: non-mutating read-only index access (task_resources.rosnap) and consistent backup.
Proves: nothing is created/changed next to the index; safe with a concurrent writer (same process and a
separate process); repeated open/close leaks nothing (fds, snapshot dirs); failures leak nothing."""

import hashlib
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from task_resources import rosnap
from task_resources.index import Index


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def listing(d):
    return sorted((p.name, sha(p)) for p in Path(d).iterdir() if p.is_file())


def fds():
    return len(os.listdir("/proc/self/fd"))


def snapdirs(root):
    return sorted(Path(root).glob(rosnap.PREFIX + "*"))


@pytest.fixture
def rt(tmp_path, monkeypatch):
    d = tmp_path / "run"
    d.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(d))
    return d


@pytest.fixture
def quiet_index(tmp_path):
    """A closed (quiescent) index with 3 rows: no -wal/-shm, like Resources after a clean exit."""
    p = tmp_path / "data" / "index.sqlite"
    ix = Index(p)
    with ix.db:
        for i in range(3):
            ix.db.execute("INSERT INTO meta VALUES(?, ?)", (f"k{i}", str(i)))
    ix.close()
    assert not Path(str(p) + "-wal").exists() and not Path(str(p) + "-shm").exists()
    return p


def count(conn):
    return conn.execute("SELECT count(*) FROM meta WHERE key LIKE 'k%'").fetchone()[0]


def test_q01_quiescent_snapshot_creates_nothing(quiet_index, rt):
    before = listing(quiet_index.parent)
    ix = Index(quiet_index, read_only=True)
    assert ix.ro_mode == "snapshot" and count(ix.db) == 3
    assert listing(quiet_index.parent) == before                 # no -wal / -shm beside the index
    assert len(snapdirs(rt)) == 1
    with pytest.raises(sqlite3.OperationalError):
        ix.db.execute("INSERT INTO meta VALUES('x','y')")
    ix.close()
    ix.close()                                                   # idempotent
    assert snapdirs(rt) == [] and listing(quiet_index.parent) == before


def test_q02_live_writer_same_process_reader_joins_without_creating(quiet_index, rt):
    w = Index(quiet_index)                                       # Resources running: -wal/-shm exist
    names_before = sorted(p.name for p in quiet_index.parent.iterdir())
    r = Index(quiet_index, read_only=True)
    assert r.ro_mode == "live" and count(r.db) == 3
    with w.db:
        w.db.execute("INSERT INTO meta VALUES('k9','9')")
    assert count(r.db) == 4                                      # live: sees the writer's commit
    assert sorted(p.name for p in quiet_index.parent.iterdir()) == names_before
    r.close()
    with w.db:                                                   # the writer is never blocked by the reader
        w.db.execute("INSERT INTO meta VALUES('k10','10')")
    w.close()
    assert snapdirs(rt) == []


def test_q03_writer_starting_after_snapshot_is_not_disturbed(quiet_index, rt):
    r = Index(quiet_index, read_only=True)
    assert r.ro_mode == "snapshot"
    w = Index(quiet_index)
    with w.db:
        w.db.execute("INSERT INTO meta VALUES('k7','7')")
    assert count(r.db) == 3                                      # snapshot = as of open (Refresh re-opens)
    w.close()
    r.close()
    r2 = Index(quiet_index, read_only=True)
    assert count(r2.db) == 4
    r2.close()


def test_q04_crash_leftover_wal_without_shm_recovered_in_copy_only(tmp_path, rt):
    live = tmp_path / "live" / "index.sqlite"
    w = Index(live)
    w.db.execute("PRAGMA wal_autocheckpoint=0")
    with w.db:
        for i in range(5):
            w.db.execute("INSERT INTO meta VALUES(?, ?)", (f"k{i}", str(i)))
    crash = tmp_path / "crash"
    crash.mkdir()
    for s in ("", "-wal"):                                       # what a power cut leaves: db + wal, no shm
        (crash / ("index.sqlite" + s)).write_bytes(Path(str(live) + s).read_bytes())
    w.close()
    p = crash / "index.sqlite"
    before = listing(crash)
    r = Index(p, read_only=True)
    assert r.ro_mode == "snapshot" and count(r.db) == 5          # committed WAL rows recovered (in the copy)
    r.close()
    assert listing(crash) == before                              # original db + wal untouched, no -shm made


def test_q05_repeated_open_close_and_lock_cycles_leak_nothing(quiet_index, rt):
    f0 = fds()
    before = listing(quiet_index.parent)
    for _ in range(50):
        ix = Index(quiet_index, read_only=True)
        assert count(ix.db) == 3
        ix.close()
    assert fds() == f0 and snapdirs(rt) == [] and listing(quiet_index.parent) == before


def test_q06_failures_leak_nothing(tmp_path, rt):
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database" * 100)
    h = sha(bad)
    f0 = fds()
    for _ in range(5):
        with pytest.raises(RuntimeError, match="index unreadable"):
            Index(bad, read_only=True)
    with pytest.raises(FileNotFoundError):
        Index(tmp_path / "missing.sqlite", read_only=True)
    assert fds() == f0 and snapdirs(rt) == [] and sha(bad) == h
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("bad")] == ["bad.sqlite"]   # no -wal/-shm


def test_q07_copy_race_retries_and_stays_consistent(quiet_index, rt, monkeypatch):
    real = rosnap.shutil.copyfile
    calls = {"n": 0}

    def racing_copy(src, dst):
        calls["n"] += 1
        r = real(src, dst)
        if calls["n"] == 1:                                      # a writer touches the db mid-copy, once
            w = Index(quiet_index)
            with w.db:
                w.db.execute("INSERT INTO meta VALUES('k5','5')")
            w.close()
        return r
    monkeypatch.setattr(rosnap.shutil, "copyfile", racing_copy)
    ix = Index(quiet_index, read_only=True)
    assert ix.ro_mode == "snapshot" and calls["n"] >= 2 and count(ix.db) == 4
    ix.close()
    assert snapdirs(rt) == []


WRITER = r"""
import sys, sqlite3, time
sys.path.insert(0, sys.argv[2])
from task_resources.index import Index
ix = Index(sys.argv[1])
print("ready", flush=True)
for i in range(200):
    with ix.db:
        ix.db.execute("INSERT INTO meta VALUES(?, ?)", (f"p{i}", str(i)))
    time.sleep(0.005)
ix.close()
print("done", flush=True)
"""


def test_q08_separate_process_writer_and_reader_concurrently(quiet_index, rt):
    src = str(Path(rosnap.__file__).resolve().parents[1])
    proc = subprocess.Popen([sys.executable, "-c", WRITER, str(quiet_index), src], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        seen = []
        while proc.poll() is None:
            r = Index(quiet_index, read_only=True)
            seen.append((r.ro_mode, r.db.execute("SELECT count(*) FROM meta WHERE key LIKE 'p%'").fetchone()[0]))
            r.close()
            time.sleep(0.02)
        assert proc.wait(timeout=30) == 0 and proc.stdout.read().strip() == "done"
    finally:
        if proc.poll() is None:
            proc.kill()
    assert seen and all(m == "live" for m, _ in seen[:-1])        # writer open -> live reads
    counts = [c for _, c in seen]
    assert counts == sorted(counts)                              # monotonic: never a torn/backwards view
    final = Index(quiet_index, read_only=True)
    assert final.ro_mode == "snapshot" and final.db.execute(
        "SELECT count(*) FROM meta WHERE key LIKE 'p%'").fetchone()[0] == 200
    final.close()
    assert snapdirs(rt) == []
    assert not Path(str(quiet_index) + "-wal").exists()          # the WRITER cleaned up on close, as normal


def test_q09_consistent_backup_live_and_quiescent(quiet_index, tmp_path, rt):
    before = listing(quiet_index.parent)
    out1 = tmp_path / "b1.sqlite"
    assert rosnap.consistent_backup(quiet_index, out1) == "snapshot"
    assert listing(quiet_index.parent) == before
    w = Index(quiet_index)
    with w.db:
        w.db.execute("INSERT INTO meta VALUES('k8','8')")
    out2 = tmp_path / "b2.sqlite"
    assert rosnap.consistent_backup(quiet_index, out2) == "live"
    w.close()
    for out, n in ((out1, 3), (out2, 4)):
        assert not Path(str(out) + "-wal").exists()
        c = sqlite3.connect(out)
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete" and count(c) == n
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.close()


def test_q10_sweep_only_removes_own_dead_snapshots(rt):
    dead = rt / f"{rosnap.PREFIX}999999999-x"
    mine = rt / f"{rosnap.PREFIX}{os.getpid()}-y"
    other = rt / "task-something-else"
    for d in (dead, mine, other):
        d.mkdir()
    rosnap.sweep_stale()
    assert not dead.exists() and mine.exists() and other.exists()
