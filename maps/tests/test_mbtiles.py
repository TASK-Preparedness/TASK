# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import sqlite3

import pytest

from mapfix import make_mbtiles, make_png
from task_maps import mbtiles


def _writer(path, **kw):
    w = mbtiles.TileWriter(path, **kw)
    w.start()
    return w


def test_create_metadata_wal(tmp_path):
    p = tmp_path / "a.mbtiles"
    mbtiles.create(p, {"name": "A", "format": "png", "attribution": "x"})
    con = sqlite3.connect(p)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    assert {"tiles", "metadata"} <= names
    con.close()
    r = mbtiles.Reader(p)
    md = r.metadata()
    assert md["name"] == "A" and md["format"] == "png"
    r.close()
    ok, msg, md = mbtiles.check(p)
    assert ok and "no tiles" in msg


def test_write_read_tms_flip(tmp_path):
    p = tmp_path / "b.mbtiles"
    mbtiles.create(p, {"name": "B", "format": "png"})
    commits = []
    w = _writer(p, on_commit=commits.extend)
    data = make_png((1, 2, 3), 16)
    w.put(mbtiles.Write(3, 2, 1, data))
    assert w.flush()
    w.stop()
    con = sqlite3.connect(p)
    assert con.execute("SELECT zoom_level, tile_column, tile_row FROM tiles").fetchall() == [(3, 2, 6)]  # TMS row
    con.close()
    r = mbtiles.Reader(p)
    assert r.get(3, 2, 1) == data and r.has(3, 2, 1) and not r.has(3, 2, 6)
    assert r.zoom_range() == (3, 3) and r.count() == 1
    r.close()
    assert commits == [(3, 2, 1)]


def test_duplicates_skipped(tmp_path):
    p = tmp_path / "c.mbtiles"
    mbtiles.create(p, {"name": "C", "format": "png"})
    w = _writer(p)
    first, second = make_png((9, 9, 9), 16), make_png((200, 0, 0), 16)
    results = []
    w.put(mbtiles.Write(1, 0, 0, first, lambda ok, e: results.append((ok, e))))
    w.flush()
    w.put(mbtiles.Write(1, 0, 0, second, lambda ok, e: results.append((ok, e))))
    w.flush()
    w.stop()
    assert w.stats.duplicates == 1 and w.stats.written == 1
    assert results == [(True, ""), (True, "duplicate")]
    r = mbtiles.Reader(p)
    assert r.get(1, 0, 0) == first          # the original tile is kept
    r.close()


@pytest.mark.parametrize("bad", [b"", b"hello world" * 10, b"\x89PNG\r\n\x1a\n" + b"x" * 100,
                                 b"\xff\xd8\xff" + b"x" * 100, b"<html>error</html>" * 10])
def test_invalid_tiles_rejected(tmp_path, bad):
    with pytest.raises(mbtiles.MBTilesError):
        mbtiles.validate_tile(bad)
    p = tmp_path / "d.mbtiles"
    mbtiles.create(p, {"name": "D", "format": "png"})
    w = _writer(p)
    res = []
    w.put(mbtiles.Write(0, 0, 0, bad, lambda ok, e: res.append((ok, e))))
    w.flush()
    w.stop()
    assert res and res[0][0] is False and "invalid tile" in res[0][1]
    r = mbtiles.Reader(p)
    assert r.count() == 0
    r.close()


def test_valid_formats():
    assert mbtiles.validate_tile(make_png()) == "png"
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
    assert mbtiles.validate_tile(jpg) == "jpg"
    webp = b"RIFF" + (100).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 100
    assert mbtiles.validate_tile(webp) == "webp"
    with pytest.raises(mbtiles.MBTilesError):
        mbtiles.validate_tile(b"\x89PNG\r\n\x1a\n" + b"\x00" * (mbtiles.MAX_TILE_BYTES + 10))


def test_integrity_check(tmp_path):
    p = make_mbtiles(tmp_path / "ok.mbtiles", zooms=(0, 1))
    assert mbtiles.check(p, quick=False)[0]
    junk = tmp_path / "junk.mbtiles"
    junk.write_bytes(b"not sqlite" * 1000)
    ok, msg, _ = mbtiles.check(junk)
    assert not ok and "SQLite" in msg
    other = tmp_path / "other.mbtiles"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE foo (a)")
    con.commit()
    con.close()
    ok, msg, _ = mbtiles.check(other)
    assert not ok and "not an MBTiles" in msg
    vec = tmp_path / "vec.mbtiles"
    mbtiles.create(vec, {"name": "v", "format": "pbf"})
    assert not mbtiles.check(vec)[0]
    assert not mbtiles.check(tmp_path / "missing.mbtiles")[0]


def test_integrity_detects_damage(tmp_path):
    p = make_mbtiles(tmp_path / "dmg.mbtiles", zooms=(0, 1, 2, 3))
    con = sqlite3.connect(p)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()
    data = bytearray(p.read_bytes())
    for off in range(4096 + 100, len(data), 4096):    # scribble over every page after the first
        data[off:off + 64] = b"\xa5" * 64
    p.write_bytes(bytes(data))
    ok, msg, _ = mbtiles.check(p, quick=False)
    assert not ok


def test_disk_full_rollback_no_corruption(tmp_path):
    """SQLITE_FULL (simulated with max_page_count) rolls the batch back, flags full, keeps the file valid."""
    p = tmp_path / "full.mbtiles"
    mbtiles.create(p, {"name": "F", "format": "png"})
    w = _writer(p, batch=8)
    for i in range(8):
        w.put(mbtiles.Write(4, i, 0, make_png((i, 1, 1), 32)))
    assert w.flush()
    w.stop()

    def limited(*a, **k):
        con = sqlite3.connect(*a, **k)
        pages = con.execute("PRAGMA page_count").fetchone()[0]
        con.execute(f"PRAGMA max_page_count={pages + 1}")
        return con

    full_msgs, results = [], []
    w = _writer(p, batch=50, connect=limited, on_disk_full=full_msgs.append)
    for i in range(50):
        w.put(mbtiles.Write(6, i, 3, make_png((i, 2, i), 128), lambda ok, e: results.append((ok, e))))
    assert w.flush()
    assert w.full and full_msgs and "disk full" in full_msgs[0]
    assert all(not ok and "disk full" in e for ok, e in results)
    w.put(mbtiles.Write(6, 99, 3, make_png((1, 1, 1), 16), lambda ok, e: results.append((ok, e))))
    w.flush()
    assert results[-1] == (False, "disk full")      # nothing written while full
    w.stop()
    assert mbtiles.is_disk_full(sqlite3.OperationalError("database or disk is full"))
    ok, msg, _ = mbtiles.check(p, quick=False)
    assert ok
    r = mbtiles.Reader(p)
    assert r.count() == 8                            # earlier tiles intact, the failed batch absent
    r.close()


def test_batching_and_checkpoints(tmp_path):
    p = tmp_path / "batch.mbtiles"
    mbtiles.create(p, {"name": "B", "format": "png"})
    w = _writer(p, batch=10, checkpoint_every=2)
    tile = make_png((5, 5, 5), 16)
    for i in range(100):
        w.put(mbtiles.Write(8, i, 0, tile))
    assert w.flush()
    w.stop()
    assert w.stats.written == 100
    assert 10 <= w.stats.commits <= 100 // 1
    assert w.stats.checkpoints >= 1


def test_set_metadata_queued(tmp_path):
    p = tmp_path / "m.mbtiles"
    mbtiles.create(p, {"name": "M", "format": "png"})
    w = _writer(p)
    w.set_metadata({"bounds": "-1,-1,1,1", "maxzoom": 9})
    assert w.flush()
    w.stop()
    r = mbtiles.Reader(p)
    md = r.metadata()
    assert md["bounds"] == "-1,-1,1,1" and md["maxzoom"] == "9"
    r.close()
