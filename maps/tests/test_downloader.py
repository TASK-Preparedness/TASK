# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Downloader against the loopback tile server (never a public server)."""

import threading
import time

import pytest

from mapfix import user_source
from task_maps import mbtiles, net, sources
from task_maps import tilemath as tm
from task_maps.downloader import DownloadEngine, JobManager, RateLimiter, estimate
from task_maps.jobs import DuplicateJob, JobStore
from task_maps.tilemath import BBox

FAST = dict(backoff_base=0.02, backoff_cap=0.1, net_backoff_cap=0.3, checkpoint_s=0.05)
SMALL = BBox(-122.5, 47.5, -122.2, 47.7)


def catalog(*srcs):
    return sources.Catalog({s.id: s for s in srcs})


def manager(tmp_path, *srcs, **kw):
    kw.setdefault("engine_kwargs", dict(FAST))
    kw.setdefault("reserve_bytes", 1024)
    m = JobManager(tmp_path / "data", catalog(*srcs), **kw)
    events = {"states": [], "tiles": [], "full": []}
    m.on_state = lambda j, s, msg: events["states"].append((j, s, msg))
    m.on_tiles = lambda p, t: events["tiles"].extend(t)
    m.on_disk_full = events["full"].append
    return m, events


def wait_state(m, job_id, states, timeout=30):
    states = (states,) if isinstance(states, str) else states
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = m.store.get(job_id)
        if j.state in states:
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} stayed {m.store.get(job_id).state}, wanted {states}")


def tiles_in(path):
    r = mbtiles.Reader(path)
    try:
        return {(z, x, tm.tms_to_xyz(z, y)) for z, x, y in
                r.con.execute("SELECT zoom_level, tile_column, tile_row FROM tiles")}
    finally:
        r.close()


def expected(bbox, minz, maxz):
    return {(z, x, y) for _, z, x, y in tm.iter_tiles(bbox, minz, maxz)}


def test_full_download_live_tiles_and_metadata(tmp_path, tile_server):
    src = user_source(tile_server.url)
    m, ev = manager(tmp_path, src)
    job = m.create_job(src.id, "Seattle", SMALL, 8, 12)
    assert job.total == tm.count_tiles(SMALL, 8, 12)
    m.start(job.id)
    j = wait_state(m, job.id, "completed")
    path = m.map_path(src.id)
    m.writers[str(path)].flush()
    assert tiles_in(path) == expected(SMALL, 8, 12)
    assert set(ev["tiles"]) == expected(SMALL, 8, 12)          # on_tiles: live refresh notifications
    assert j.downloaded == j.total and j.failed == 0 and j.cursor == j.total
    ua = {r[2] for r in tile_server.tile_requests()}
    assert ua == {net.USER_AGENT} and "task-maps/" in net.USER_AGENT
    m.shutdown()
    md = mbtiles.Reader(path).metadata()
    assert md["format"] == "png" and md["attribution"] == "Test tiles" and md["bounds"].startswith("-122.5")
    assert md["minzoom"] == "8" and md["maxzoom"] == "12"
    assert mbtiles.check(path, quick=False)[0]


def test_existing_tiles_skipped_and_overlap_shares_file(tmp_path, tile_server):
    src = user_source(tile_server.url)
    m, _ = manager(tmp_path, src)
    a = m.create_job(src.id, "A", SMALL, 8, 11)
    m.start(a.id)
    wait_state(m, a.id, "completed")
    n_first = len(tile_server.tile_requests())
    bigger = BBox(-122.6, 47.4, -122.1, 47.8)
    b = m.create_job(src.id, "B", bigger, 8, 11)
    m.start(b.id)
    jb = wait_state(m, b.id, "completed")
    overlap = len(expected(SMALL, 8, 11) & expected(bigger, 8, 11))
    assert jb.skipped == overlap
    assert len(tile_server.tile_requests()) - n_first == jb.total - overlap
    m.shutdown()


def test_duplicate_job_protection(tmp_path, tile_server):
    tile_server.delay = 0.2
    src = user_source(tile_server.url, rate_limit=2.0)
    m, _ = manager(tmp_path, src)
    j = m.create_job(src.id, "A", SMALL, 8, 12)
    with pytest.raises(DuplicateJob):
        m.create_job(src.id, "A again", SMALL, 8, 12)
    m.start(j.id)
    other = m.create_job(src.id, "B", SMALL, 9, 12)
    with pytest.raises(RuntimeError):
        m.start(other.id)                                   # one engine at a time
    m.cancel(j.id)
    assert m.store.get(j.id).state == "cancelled"
    m.create_job(src.id, "A after cancel", SMALL, 8, 12)    # a cancelled job does not block
    m.shutdown()


def test_interrupted_download_resumes_after_restart(tmp_path, tile_server):
    src = user_source(tile_server.url, rate_limit=10.0, max_concurrency=2)
    m, _ = manager(tmp_path, src)
    job = m.create_job(src.id, "R", SMALL, 8, 13)
    m.start(job.id)
    deadline = time.monotonic() + 20
    while m.store.get(job.id).cursor < 15 and time.monotonic() < deadline:
        time.sleep(0.02)
    m.shutdown()                                            # program closed mid-download
    j = m.store.get(job.id) if False else JobStore(tmp_path / "data" / "jobs.sqlite").get(job.id)
    assert j.state == "interrupted" and 0 < j.cursor < j.total
    before = len(tile_server.tile_requests())

    m2, _ = manager(tmp_path, src)
    rec = m2.store.recover_after_restart()
    assert [r.id for r in rec] == [job.id]
    m2.resume(job.id)
    j2 = wait_state(m2, job.id, "completed")
    path = m2.map_path(src.id)
    assert tiles_in(path) == expected(SMALL, 8, 13)
    refetched = len(tile_server.tile_requests()) - before
    # at most the in-flight window is fetched twice; the rest resume from the checkpoint
    assert refetched <= j2.total - j.cursor
    assert j2.downloaded + j2.skipped >= j2.total
    m2.shutdown()


def test_crash_recovery_marks_running_interrupted(tmp_path):
    st = JobStore(tmp_path / "jobs.sqlite")
    j = st.create("s", "x", SMALL, 1, 2, 10, tmp_path / "m.mbtiles")
    st.set_state(j.id, "running")
    st.close()
    st = JobStore(tmp_path / "jobs.sqlite")            # as after a power cut
    rec = st.recover_after_restart()
    assert rec[0].id == j.id and st.get(j.id).state == "interrupted"
    st.close()


def test_429_retry_after_honoured(tmp_path, tile_server):
    tile_server.global_429 = 1
    tile_server.retry_after = "1"
    src = user_source(tile_server.url, max_concurrency=1)
    m, _ = manager(tmp_path, src)
    job = m.create_job(src.id, "429", SMALL, 10, 10)
    t0 = time.monotonic()
    m.start(job.id)
    j = wait_state(m, job.id, "completed")
    reqs = tile_server.tile_requests()
    assert j.failed == 0
    gap = reqs[1][0] - reqs[0][0]
    assert gap >= 0.95, f"retried after {gap:.2f}s despite Retry-After: 1"
    assert time.monotonic() - t0 >= 1.0
    m.shutdown()


def test_retry_after_parsing():
    assert net.retry_after({"retry-after": "120"}) == 120
    assert net.retry_after({"retry-after": "99999"}) == net.MAX_RETRY_AFTER
    assert net.retry_after({}, default=7) == 7
    now = 1_800_000_000
    from email.utils import formatdate
    assert net.retry_after({"retry-after": formatdate(now + 30, usegmt=True)}, now=now) == pytest.approx(30, abs=1)
    assert net.retry_after({"retry-after": "garbage"}, default=5) == 5


def test_5xx_backoff_then_success_and_permanent_failure(tmp_path, tile_server):
    tiles = sorted(expected(SMALL, 11, 11))
    tile_server.script[tiles[0]] = [500, 502, 200]
    tile_server.script[tiles[1]] = [500] * 10
    tile_server.script[tiles[2]] = [404]
    tile_server.script[tiles[3]] = ["corrupt", "corrupt"]
    tile_server.script[tiles[4]] = ["corrupt", 200]
    src = user_source(tile_server.url)
    m, _ = manager(tmp_path, src)
    job = m.create_job(src.id, "errs", SMALL, 11, 11)
    m.start(job.id)
    j = wait_state(m, job.id, "completed-with-errors")
    failed = {(z, x, y): err for z, x, y, _, err in m.store.failed_tiles(job.id)}
    assert set(failed) == {tiles[1], tiles[2], tiles[3]}
    assert "after 5 attempts" in failed[tiles[1]]
    assert "not available" in failed[tiles[2]]
    assert "corrupt" in failed[tiles[3]]
    got = tiles_in(m.map_path(src.id))
    assert tiles[0] in got and tiles[4] in got and tiles[3] not in got
    assert m.failed_tiles_for(m.map_path(src.id)) == set(failed)
    # Retry failed: the server now answers
    tile_server.script.clear()
    m.retry_failed(job.id)
    j = wait_state(m, job.id, "completed")
    assert j.failed == 0 and tiles_in(m.map_path(src.id)) == expected(SMALL, 11, 11)
    m.shutdown()


def test_backoff_has_jitter():
    e = DownloadEngine.__new__(DownloadEngine)
    e.backoff_base, e.backoff_cap = 1.0, 60.0
    vals = set()
    import random
    rng = random.Random(1)
    e.rng = rng.random
    for _ in range(20):
        vals.add(round(e._backoff(3), 4))
    assert len(vals) > 10 and all(2.0 <= v <= 4.0 for v in vals)
    e.rng = lambda: 1.0
    assert e._backoff(30) == 60.0


def test_rate_and_concurrency_limits(tmp_path, tile_server):
    tile_server.delay = 0.25
    src = user_source(tile_server.url, rate_limit=5.0, max_concurrency=2)
    m, _ = manager(tmp_path, src)
    job = m.create_job(src.id, "rate", SMALL, 10, 11)
    m.start(job.id)
    wait_state(m, job.id, "completed", timeout=60)
    times = sorted(r[0] for r in tile_server.tile_requests())
    assert len(times) == job.total
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert min(gaps) >= 0.2 * 0.9, f"requests closer than 1/rate: {min(gaps):.3f}s"
    span = times[-1] - times[0]
    assert len(times) / span <= 5.0 * 1.1 + 1 / max(span, 1)
    assert tile_server.max_conc <= 2
    m.shutdown()


def test_rate_limiter_unit():
    t = [0.0]
    lim = RateLimiter(4.0, clock=lambda: t[0])
    waits = [lim.reserve() for _ in range(4)]
    assert waits == pytest.approx([0.0, 0.25, 0.5, 0.75])


def test_network_loss_auto_pause_and_resume(tmp_path, tile_server):
    src = user_source(tile_server.url, max_concurrency=1)
    m, ev = manager(tmp_path, src)
    job = m.create_job(src.id, "net", SMALL, 9, 12)
    tile_server.down = True
    m.start(job.id)
    wait_state(m, job.id, "waiting-network", timeout=20)
    assert m.store.get(job.id).downloaded == 0
    tile_server.down = False
    j = wait_state(m, job.id, "completed", timeout=60)
    assert j.failed == 0
    states = [s for _, s, _ in ev["states"]]
    assert "waiting-network" in states and states[-1] == "completed"
    assert any(msg == "network is back" for _, s, msg in ev["states"])
    m.shutdown()


def test_unreachable_host_is_network_error():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                        # nothing listens there now
    import mapfix
    mapfix.LOCAL_ALLOWED_PORTS.add(port)
    try:
        with pytest.raises(net.NetworkError):
            net.fetch(f"http://127.0.0.1:{port}/tiles/0/0/0.png", timeout=2)
    finally:
        mapfix.LOCAL_ALLOWED_PORTS.discard(port)


def test_low_storage_pauses_before_writing(tmp_path, tile_server):
    free = [10 ** 12]
    src = user_source(tile_server.url)
    m, _ = manager(tmp_path, src, free_space=lambda: free[0], reserve_bytes=10 ** 6,
                   engine_kwargs=dict(FAST, capacity_every=5))
    job = m.create_job(src.id, "cap", SMALL, 9, 12)
    free[0] = 1000                                   # the disk fills up after the job was accepted
    m.start(job.id)
    j = wait_state(m, job.id, "paused-disk")
    assert "storage low" in j.message
    free[0] = 10 ** 12
    m.resume(job.id)
    wait_state(m, job.id, "completed")
    m.shutdown()


def test_capacity_check_refuses_job(tmp_path, tile_server):
    src = user_source(tile_server.url)
    m, _ = manager(tmp_path, src, free_space=lambda: 5000, reserve_bytes=10 ** 6)
    with pytest.raises(OSError, match="not enough free space"):
        m.create_job(src.id, "big", SMALL, 8, 14)
    big = BBox(-125, 30, -70, 49)
    src2 = user_source(tile_server.url, sid="limited", max_tiles_per_job=100)
    m2, _ = manager(tmp_path / "b", src2)
    with pytest.raises(ValueError, match="limit of 100"):
        m2.create_job("limited", "x", big, 5, 9)
    m.shutdown()
    m2.shutdown()


def test_disk_full_during_write_pauses_without_corruption(tmp_path, tile_server):
    """A real SQLITE_FULL from the writer pauses the job (paused-disk); after resume every tile arrives."""
    import sqlite3
    src = user_source(tile_server.url, max_concurrency=2)
    m, ev = manager(tmp_path, src)
    job = m.create_job(src.id, "full", SMALL, 9, 12)
    path = m.map_path(src.id)
    m.writers[str(path)].stop()
    limit = {"on": True}

    def limited(*a, **k):
        con = sqlite3.connect(*a, **k)
        if limit["on"]:
            pages = con.execute("PRAGMA page_count").fetchone()[0]
            con.execute(f"PRAGMA max_page_count={pages}")
        return con

    w = mbtiles.TileWriter(path, batch=4, on_commit=lambda t: ev["tiles"].extend(t), on_disk_full=ev["full"].append,
                           connect=limited)
    w.start()
    m.writers[str(path)] = w
    m.start(job.id)
    j = wait_state(m, job.id, "paused-disk", timeout=30)
    assert "disk full" in j.message and ev["full"]
    assert mbtiles.check(path, quick=False)[0]
    # "free space": restart the writer without the page limit, then resume
    w.stop()
    limit["on"] = False
    w2 = mbtiles.TileWriter(path, on_commit=lambda t: ev["tiles"].extend(t), on_disk_full=ev["full"].append)
    w2.start()
    m.writers[str(path)] = w2
    m.engine.writer = w2
    m.resume(job.id)
    wait_state(m, job.id, "completed", timeout=60)
    w2.flush()
    assert tiles_in(path) == expected(SMALL, 9, 12)
    assert mbtiles.check(path, quick=False)[0]
    m.shutdown()


def test_non_approved_source_cannot_bulk_download(tmp_path, tile_server):
    not_ok = user_source(tile_server.url, sid="noperm", user_attests_permission=False)
    osm = user_source("https://tile.openstreetmap.org/{z}/{x}/{y}.png", sid="osm-copy")
    m, _ = manager(tmp_path, not_ok, osm)
    for sid in ("noperm", "osm-copy"):
        with pytest.raises(PermissionError):
            m.create_job(sid, "x", SMALL, 8, 10)
    # even a job row forged directly into the store is refused by the engine
    j = m.store.create("osm-copy", "forged", SMALL, 8, 9, 4, m.map_path("osm-copy"))
    eng = m.start(j.id)
    eng.wait(5)
    assert m.store.get(j.id).state == "paused" and "refused" in m.store.get(j.id).message
    assert tile_server.tile_requests() == []
    m.shutdown()


def test_shipped_osm_source_refused_by_manager(tmp_path):
    cat = sources.load()
    m = JobManager(tmp_path / "d", cat)
    with pytest.raises(PermissionError, match="osmfoundation"):
        m.create_job("osm-standard", "x", SMALL, 8, 10)
    m.shutdown()


def test_estimate_and_pause_cancel(tmp_path, tile_server):
    e = estimate(SMALL, 8, 12, 20000, 10 ** 9, reserve=10 ** 6)
    assert e["tiles"] == tm.count_tiles(SMALL, 8, 12) and e["bytes"] == e["tiles"] * 20000
    assert e["required"] > e["bytes"] and e["fits"]
    assert not estimate(SMALL, 8, 12, 20000, 1000)["fits"]
    tile_server.delay = 0.1
    src = user_source(tile_server.url, rate_limit=3.0, max_concurrency=1)
    m, _ = manager(tmp_path, src)
    job = m.create_job(src.id, "pc", SMALL, 8, 13)
    m.start(job.id)
    time.sleep(0.5)
    m.pause()
    j = wait_state(m, job.id, "paused")
    time.sleep(0.6)
    n = len(tile_server.tile_requests())
    time.sleep(0.6)
    assert len(tile_server.tile_requests()) <= n + 1        # no new requests while paused
    snap = m.engine.snapshot()
    assert snap["state"] == "paused" and snap["total"] == job.total
    m.resume(job.id)
    wait_state(m, job.id, "running")
    m.cancel(job.id)
    assert m.store.get(job.id).state == "cancelled"
    m.shutdown()


def test_api_key_never_stored_in_failures(tmp_path, tile_server):
    tiles = sorted(expected(SMALL, 10, 10))
    tile_server.script[tiles[0]] = [403]
    src = user_source(tile_server.url.replace(".png", ".png?k={api_key}"), sid="keyed", api_key_required=True)
    m, _ = manager(tmp_path, src, keys={"keyed": "TOPSECRET"})
    job = m.create_job("keyed", "k", SMALL, 10, 10)
    m.start(job.id)
    wait_state(m, job.id, "completed-with-errors")
    assert all("k=TOPSECRET" in r[1] for r in tile_server.tile_requests())
    dump = (tmp_path / "data" / "jobs.sqlite").read_bytes()
    m.shutdown()
    for f in (tmp_path / "data").glob("jobs.sqlite*"):
        assert b"TOPSECRET" not in f.read_bytes()
    assert b"TOPSECRET" not in dump
