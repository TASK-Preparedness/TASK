# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-maps 0.1.1 — Joshua's 12 acceptance tests, simulated (loopback tile server, local fixtures).
legacy_010_settings.py is a verbatim copy of 0.1.0's settings.py (git 0b503b9) for the rollback test."""

import ast
import hashlib
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from mapfix import TileServer, make_mbtiles, user_source
from task_maps import mbtiles, online, overlays
from task_maps import settings as settings_mod
from task_maps.tilemath import BBox
from test_ui import make_window

MAPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAPS.parent / "comms"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def server():
    s = TileServer()
    s.start()
    yield s
    s.stop()


def win(qtbot, tmp_path, server, **kw):
    src = user_source(server.url, sid="usgs-topo", name="USGS Topo (test server)")
    st = kw.pop("settings", None) or settings_mod.Settings(online_auto=True, view=[40.9, -77.8, 6.0])
    mw = make_window(qtbot, tmp_path, srcs=[src], settings=st, **kw)
    return mw, src


def prov(mw):
    return mw.providers[online.layer_path("usgs-topo")]


def tile_paths(server, z=None):
    out = {r[1] for r in server.tile_requests()}
    return {p for p in out if z is None or p.startswith(f"/tiles/{z}/")}


def test_1_opening_with_internet_displays_map(qtbot, tmp_path, server):
    mw, _ = win(qtbot, tmp_path, server)
    assert mw.view.layer.kind == "online"
    qtbot.waitUntil(lambda: mw.view.paints and (mw.view.repaint() or mw.view.stats["downloaded"] > 4), timeout=8000)
    assert tile_paths(server, 6)


def test_2_panning_loads_new_tiles(qtbot, tmp_path, server):
    mw, _ = win(qtbot, tmp_path, server)
    qtbot.waitUntil(lambda: (mw.view.repaint() or mw.view.stats["downloaded"]) > 4, timeout=8000)
    before = tile_paths(server, 6)
    mw.view.pan_pixels(900, 0)
    qtbot.waitUntil(lambda: (mw.view.repaint() or len(tile_paths(server, 6) - before)) > 0, timeout=8000)


def test_3_zooming_loads_that_zoom(qtbot, tmp_path, server):
    mw, _ = win(qtbot, tmp_path, server)
    mw.view.set_view(40.9, -77.8, 9.0)
    qtbot.waitUntil(lambda: (mw.view.repaint() or len(tile_paths(server, 9))) > 2, timeout=8000)


def test_4_and_5_offline_uses_saved_tiles_and_switches_automatically(qtbot, tmp_path, server):
    mw, _ = win(qtbot, tmp_path, server)
    qtbot.waitUntil(lambda: (mw.view.repaint() or prov(mw).cache.count()) > 4, timeout=8000)
    p = prov(mw)
    p.probe_s = 0.3
    server.down = True
    mw.view.set_view(40.9, -77.8, 8.0)              # needs network -> NetworkError -> offline
    qtbot.waitUntil(lambda: (mw.view.repaint() or not p.online), timeout=8000)
    assert mw.net_label.text().startswith("Offline")
    mw.view.cache.clear()
    mw.view.set_view(40.9, -77.8, 6.0)              # cached zoom: displayed without network
    qtbot.waitUntil(lambda: (mw.view.repaint() or mw.view.stats["downloaded"]) > 4, timeout=8000)
    server.down = False
    time.sleep(0.35)
    mw.view.set_view(40.9, -77.8, 8.0)
    qtbot.waitUntil(lambda: (mw.view.repaint() or p.online), timeout=8000)
    qtbot.waitUntil(lambda: mw.net_label.text() == "Online", timeout=3000)
    qtbot.waitUntil(lambda: (mw.view.repaint() or len(tile_paths(server, 8))) > 0, timeout=8000)


def test_6_offline_region_download_still_works(qtbot, tmp_path, server):
    mw, src = win(qtbot, tmp_path, server)
    job = mw.manager.create_job(src.id, "Region", BBox(-78.0, 40.8, -77.6, 41.0), 8, 9)
    mw.manager.start(job.id)
    qtbot.waitUntil(lambda: mw.manager.store.get(job.id).state == "completed", timeout=30000)
    manual = tmp_path / "data" / "maps" / "usgs-topo.mbtiles"
    r = mbtiles.Reader(manual)
    assert r.count() > 0
    r.close()


def test_7_existing_pennsylvania_downloads_intact(qtbot, tmp_path, server):
    data = tmp_path / "data"
    pa = [(6, x, y) for x in range(17, 20) for y in range(23, 26)]      # around central PA (view z6 is x18 y24)
    manual = make_mbtiles(data / "maps" / "usgs-topo.mbtiles", bbox_tiles=pa, metadata={"name": "Pennsylvania"})
    before = sha(manual)
    st = settings_mod.Settings(online_auto=True, view=[40.9, -77.8, 6.0], layer=str(manual), cache_mb=16)
    mw, _ = win(qtbot, tmp_path, server, settings=st)
    assert mw.view.layer.path == online.layer_path("usgs-topo")       # saved PA layer shown through online layer
    qtbot.waitUntil(lambda: (mw.view.repaint() or mw.view.stats["downloaded"]) > 4, timeout=8000)
    served_from_net = tile_paths(server, 6)
    assert not any(f"/tiles/6/{x}/{y}.png" in served_from_net for _, x, y in pa)   # manual tiles: no network
    assert served_from_net                                                           # others fetched online
    p = prov(mw)
    p.cache.set_limit(1)                                                # force eviction
    mw.dialogs.answers["confirm"] = True
    mw.clear_cache()
    mw.close()
    assert sha(manual) == before and mbtiles.check(manual)[0]


def test_8_imported_mbtiles_accessible(qtbot, tmp_path, server):
    ext = make_mbtiles(tmp_path / "ext.mbtiles", zooms=(0, 1))
    mw, _ = win(qtbot, tmp_path, server)
    from task_maps import layers
    dest = layers.import_mbtiles(ext, tmp_path / "data")
    mw.refresh_layers()
    mw.select_layer(str(dest))
    assert mw.view.layer.kind == "imported"
    mw.view.set_view(0, 0, 1)
    qtbot.waitUntil(lambda: (mw.view.repaint() or mw.view.stats["downloaded"]) > 0, timeout=8000)


def test_9_network_errors_do_not_crash(qtbot, tmp_path, server):
    for i, act in enumerate(["drop", 500, "corrupt", ("429", 1), 403, 404]):
        server.script[(6, 16 + i, 24)] = [act] * 3
    mw, _ = win(qtbot, tmp_path, server)
    qtbot.waitUntil(lambda: (mw.view.repaint() or len(server.tile_requests())) > 8, timeout=8000)
    qtbot.wait(500)
    mw.view.repaint()
    assert mw.isVisible() and mw.view.paints > 0
    assert prov(mw).errors


def _feed(path, rows, schema="1"):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); CREATE TABLE entity(id TEXT PRIMARY KEY,"
                     " layer TEXT, label TEXT, lat REAL, lon REAL, alt_m REAL, accuracy_m REAL, observed_ts INTEGER,"
                     " source TEXT, kind TEXT, stale_after_s INTEGER, attrs_json TEXT);")
    db.execute("INSERT INTO meta VALUES('schema', ?)", (schema,))
    for r in rows:
        db.execute("INSERT INTO entity VALUES(?,?,?,?,?,NULL,NULL,?,?,?,3600,'{}')", r)
    db.commit()
    db.close()


def test_10_aprs_and_mesh_overlays_independent(qtbot, tmp_path, server):
    fd = tmp_path / "feeds"
    now = int(time.time())
    _feed(fd / "task-aprs.sqlite", [("aprs:N0POS", "aprs", "N0POS", 40.9, -77.8, now, "APRS RF", "observed")])
    (fd / "task-mesh.sqlite").write_bytes(b"not a database")
    assert overlays.read("task-mesh", "mesh", fd) == []
    assert [e["id"] for e in overlays.read("task-aprs", "aprs", fd)] == ["aprs:N0POS"]
    mw, _ = win(qtbot, tmp_path, server)
    mw.feeds_dir = fd
    mw.refresh_overlays()
    assert mw.view.overlay_enabled["aprs"] and not mw.view.overlay_enabled["mesh"]     # mesh off by default
    _feed(fd / "mesh2" / "task-mesh.sqlite", [("mesh:1", "mesh", "Node1", 40.95, -77.7, now, "Meshtastic", "observed")])
    mw.feeds_dir = fd / "mesh2"                       # only mesh present now, APRS feed missing
    mw.overlay_boxes["mesh"].setChecked(True)
    assert mw.view.overlays["aprs"] == [] and len(mw.view.overlays["mesh"]) == 1
    mw.view.repaint()
    mw.overlay_boxes["aprs"].setChecked(False)
    assert mw.settings.overlays == {"aprs": False, "mesh": True, "gmrs": False}


def test_11_no_unauthorized_location_transmission(qtbot, tmp_path, server):
    from task_maps.gpsd import GpsState
    mw, _ = win(qtbot, tmp_path, server)
    g = GpsState(connection="connected")
    g.lat, g.lon, g.mode = 40.912345, -77.812345, 3
    mw._on_gps(g)
    qtbot.waitUntil(lambda: (mw.view.repaint() or len(server.tile_requests())) > 4, timeout=8000)
    for _, path, ua in server.requests:
        assert path.startswith("/tiles/") and "40.91" not in path and "77.81" not in path
        assert "40.91" not in ua
    assert {r[1].split("/")[1] for r in server.requests} == {"tiles"}
    for f in (MAPS / "task_maps").rglob("*.py"):
        src = f.read_text()
        assert "FeedWriter" not in src and "sendto(" not in src, f
    tree = ast.parse((MAPS / "task_maps" / "overlays.py").read_text())
    assert "mode=ro" in ast.unparse(tree)


def test_12_rollback_keeps_offline_maps(qtbot, tmp_path, server):
    data = tmp_path / "data"
    manual = make_mbtiles(data / "maps" / "usgs-topo.mbtiles", zooms=(0, 1))
    before = sha(manual)
    mw, _ = win(qtbot, tmp_path, server)
    qtbot.waitUntil(lambda: (mw.view.repaint() or prov(mw).cache.count()) > 0, timeout=8000)
    mw.close()
    settings_file = tmp_path / "xdg_config" / "task-maps" / "settings.json"
    cfg = Path(settings_mod.paths.config_dir()) / "settings.json"
    assert cfg.exists()
    spec = importlib.util.spec_from_file_location("legacy010", MAPS / "tests" / "legacy_010_settings.py")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    s010 = legacy.load(cfg)                            # 0.1.0 reads 0.1.1's settings without error
    assert not s010.load_error
    assert sha(manual) == before
    assert mbtiles.check(data / "cache" / "usgs-topo.mbtiles")[0]   # cache is plain MBTiles, ignored by 0.1.0
    assert [p.name for p in (data / "maps").glob("*.mbtiles")] == ["usgs-topo.mbtiles"]
    assert json.loads(cfg.read_text())["schema"] == 1
    del settings_file
