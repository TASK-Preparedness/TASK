# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Qt UI: offline rendering (pixel checks), live refresh, cache bound, layout at 1920×1080 and
1024×600, no UI-thread blocking, main-window flows. Offscreen platform, local data only."""

import time

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from mapfix import SKY, TPV_FIX, make_png, tile_color, user_source
from task_maps import layers, mbtiles, sources
from task_maps import tilemath as tm
from task_maps.gpsd import GpsState, apply_report
from task_maps.ui.main_window import MainWindow
from task_maps.ui.map_view import MapView
from task_maps.ui.tiles import TileCache, TileLoader
from task_maps.tilemath import BBox
from uifix import ScriptedDialogs, labelled_mbtiles, shot_dir

FAST = dict(backoff_base=0.02, backoff_cap=0.1, net_backoff_cap=0.3, checkpoint_s=0.05)
ALL_Z2 = [(z, x, y) for z in range(3) for x in range(2 ** z) for y in range(2 ** z)]


def near(c1, c2, tol=6):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))


def rgb(img, x, y):
    c = QColor(img.pixel(int(x), int(y)))
    return (c.red(), c.green(), c.blue())


def tile_origin(view, z, x, y):
    """Screen position of tile (z,x,y) at an integer zoom equal to z."""
    cx, cy = view.center_world(z)
    return x * 256 - cx + view.width() / 2, y * 256 - cy + view.height() / 2


@pytest.fixture
def view(qtbot):
    loader = TileLoader(2)
    v = MapView(loader, cache_tiles=64)
    v.resize(800, 600)
    qtbot.addWidget(v)
    v.show()
    yield v
    loader.stop()


def settle(qtbot, v, ms=5000):
    """Render until no tile is still loading (grab() forces a real paint even offscreen)."""
    def done():
        before = v.paints
        v.grab()
        return v.paints > before and v.stats["loading"] == 0
    qtbot.waitUntil(done, timeout=ms)


def test_offline_render_pixels(qtbot, view, tmp_path):
    p = labelled_mbtiles(tmp_path / "fix.mbtiles", ALL_Z2)
    view.set_layer(layers.describe(p, "imported"))
    view.set_view(0, 0, 2)
    settle(qtbot, view)
    img = view.grab().toImage()
    for x, y in ((1, 1), (2, 1), (1, 2), (2, 2)):
        ox, oy = tile_origin(view, 2, x, y)
        assert near(rgb(img, ox + 20, oy + 20), tile_color(2, x, y)), (x, y)
    assert view.stats["downloaded"] >= 4 and view.stats["missing"] == 0
    assert view.overzoom_info == ""


def test_missing_coverage_hatched_and_overzoom(qtbot, view, tmp_path):
    p = labelled_mbtiles(tmp_path / "part.mbtiles", [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 1)])
    view.set_layer(layers.describe(p, "imported"))
    view.set_view(0, 0, 2)
    settle(qtbot, view)
    assert view.stats["missing"] > 0
    img = view.grab().toImage()
    ox, oy = tile_origin(view, 2, 2, 2)          # tile 2/2/2 is not in the file -> hatched, not a colour
    samples = {rgb(img, ox + dx, oy + dy) for dx in range(10, 60, 3) for dy in range(10, 60, 3)}
    assert len(samples) >= 2                      # hatch pattern: more than one colour
    assert not any(near(s, tile_color(2, 2, 2)) for s in samples)
    # overzoom: beyond the file's max zoom the z2 tile is scaled up and marked
    view.set_view(*_center_of(2, 1, 1), 4)
    settle(qtbot, view)
    assert view.stats["overzoom"] > 0 and "z2" in view.overzoom_info


def _center_of(z, x, y):
    w, s, e, n = tm.tile_bounds(z, x, y)
    return (s + n) / 2, (w + e) / 2


def test_live_refresh_when_tiles_committed(qtbot, view, tmp_path):
    p = tmp_path / "live.mbtiles"
    mbtiles.create(p, {"name": "live", "format": "png", "attribution": "TEST"})
    view.set_layer(layers.describe(p, "downloaded"))
    view.set_view(0, 0, 1)
    settle(qtbot, view)
    assert view.stats["missing"] > 0
    view.pending_region = (BBox(-180, -85, 180, 85), 0, 1)
    view.repaint()
    assert view.stats["pending"] > 0              # "downloading…" state while a job covers it
    w = mbtiles.TileWriter(p, on_commit=lambda t: committed.extend(t))
    committed = []
    w.start()
    for x in range(2):
        for y in range(2):
            w.put(mbtiles.Write(1, x, y, make_png(tile_color(1, x, y), 256)))
    w.flush()
    w.stop()
    view.tiles_committed(str(p), committed)
    view.pending_region = None
    settle(qtbot, view)
    img = view.grab().toImage()
    ox, oy = tile_origin(view, 1, 1, 1)
    assert near(rgb(img, ox + 30, oy + 30), tile_color(1, 1, 1))
    assert view.stats["missing"] == 0 and view.layer.maxzoom == 1


def test_failed_and_corrupt_tiles_marked(qtbot, view, tmp_path):
    p = tmp_path / "bad.mbtiles"
    mbtiles.create(p, {"name": "bad", "format": "png"})
    import sqlite3
    con = sqlite3.connect(p)
    con.execute("INSERT INTO tiles VALUES (1, 0, 1, ?)", (b"\x89PNG\r\n\x1a\nbroken" * 10,))  # undecodable
    con.commit()
    con.close()
    view.set_layer(layers.describe(p, "downloaded"))
    view.failed = {(1, 1, 1)}
    view.set_view(0, 0, 1)
    settle(qtbot, view)
    assert (1, 0, 0) in view.failed               # corrupt bytes in the file are shown as failed, no crash
    assert view.stats["failed"] >= 2


def test_cache_is_bounded(qtbot, tmp_path):
    p = labelled_mbtiles(tmp_path / "many.mbtiles", [(4, x, y) for x in range(16) for y in range(16)])
    loader = TileLoader(2)
    v = MapView(loader, cache_tiles=20)
    v.resize(600, 400)
    qtbot.addWidget(v)
    v.show()
    v.set_layer(layers.describe(p, "imported"))
    for lon in range(-170, 171, 20):
        v.set_view(0, lon, 4)
        v.repaint()
        qtbot.wait(30)
    settle(qtbot, v)
    assert len(v.cache.images) <= 20
    loader.stop()
    c = TileCache(max_images=3, max_absent=5)
    for i in range(10):
        c.store((0, i, 0), object())
        c.store((1, i, 0), None)
    assert len(c.images) == 3 and len(c.absent) == 5


def test_pan_zoom_keyboard_wheel_rect(qtbot, view):
    view.set_view(10, 10, 5)
    lat0, lon0 = view.lat, view.lon
    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert view.lon > lon0
    qtbot.keyClick(view, Qt.Key.Key_Plus)
    assert view.zoom == 6
    qtbot.keyClick(view, Qt.Key.Key_Minus)
    assert view.zoom == 5
    _drag(view, (400, 300), (300, 250))
    assert view.lon > lon0 and view.lat < 85
    # download mode: drag creates the rectangle, handle drag resizes it
    view.download_mode = True
    _drag(view, (200, 200), (400, 350))
    b = view.rect_bbox()
    assert b is not None and b.west < b.east and b.south < b.north
    r = view.rect_screen()
    assert abs(r.left() - 200) < 2 and abs(r.bottom() - 350) < 2
    _drag(view, (r.right(), r.bottom()), (r.right() + 50, r.bottom() + 40))
    r2 = view.rect_screen()
    assert abs(r2.right() - (r.right() + 50)) < 2 and abs(r2.bottom() - (r.bottom() + 40)) < 2


def test_rect_across_antimeridian(qtbot, view):
    view.set_view(0, 180, 3)
    view.download_mode = True
    _drag(view, (300, 250), (500, 350))
    b = view.rect_bbox()
    assert b.crosses_antimeridian
    assert tm.count_tiles(b, 3, 3) == sum(x1 - x0 + 1 for x0, x1 in tm.x_ranges(b, 3)) * \
        (tm.y_range(b, 3)[1] - tm.y_range(b, 3)[0] + 1)


def _mouse(w, kind, pos, buttons):
    btn = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    ev = QMouseEvent(kind, QPointF(*pos), w.mapToGlobal(QPointF(*pos)), btn, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w, ev)


def _drag(w, a, b, steps=8):
    L = Qt.MouseButton.LeftButton
    _mouse(w, QEvent.Type.MouseButtonPress, a, L)
    for i in range(1, steps + 1):
        _mouse(w, QEvent.Type.MouseMove, (a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps), L)
    _mouse(w, QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.NoButton)


# ----------------------------------------------------------------- main window
def make_window(qtbot, tmp_path, srcs=(), dialogs=None, size=(1920, 1080), **kw):
    cat = sources.Catalog({s.id: s for s in srcs}) if srcs else sources.load()
    if "settings" not in kw:      # 0.1.0 behaviour tests: no automatic online layer (0.1.1 tests pass settings)
        from task_maps import settings as settings_mod
        kw["settings"] = settings_mod.Settings(online_auto=False)
    mw = MainWindow(data_dir=tmp_path / "data", dialogs=dialogs or ScriptedDialogs(), catalog=cat, start_gps=False,
                    core_fn=lambda: ("no-provider", "device connected, no Core provider"),
                    engine_kwargs=dict(FAST), reserve_bytes=1024, **kw)
    qtbot.addWidget(mw)
    mw.resize(*size)
    mw.show()
    qtbot.waitExposed(mw)
    return mw


def fixture_world(tmp_path):
    d = tmp_path / "data" / "maps" / "imported"
    d.mkdir(parents=True)
    tiles = ALL_Z2 + [(3, x, y) for x in range(1, 3) for y in range(2, 4)]
    return labelled_mbtiles(d / "fixture-world.mbtiles", tiles)


@pytest.mark.parametrize("size", [(1920, 1080), (1024, 600)])
def test_layout_fits(qtbot, tmp_path, size):
    fixture_world(tmp_path)
    mw = make_window(qtbot, tmp_path, size=size)
    qtbot.wait(50)
    assert mw.width() == size[0] and mw.height() == size[1]
    assert mw.compact() == (size[0] < 1280)
    for key in ("maps", "download", "gps", "waypoints"):
        mw.show_panel(key)
        qtbot.wait(30)
        for name, b in mw.tool.items():
            g = b.geometry()
            assert b.isVisible() and b.mapTo(mw, g.topLeft() - g.topLeft()).x() + g.width() <= size[0], name
        assert mw.side.horizontalScrollBar().isHidden() or not mw.side.horizontalScrollBar().isVisible()
        assert mw.stack.currentWidget().width() <= mw.side.viewport().width() + 1
        assert mw.view.width() >= (600 if size[0] == 1024 else 1400)
        assert mw.view.height() >= (450 if size[1] == 600 else 900)
    hint = mw.minimumSizeHint()
    assert hint.width() <= 1024 and hint.height() <= 600
    mw.close()


def test_ui_thread_not_blocked_during_download(qtbot, tmp_path, tile_server):
    tile_server.delay = 0.05
    src = user_source(tile_server.url, rate_limit=10.0, max_concurrency=3)
    mw = make_window(qtbot, tmp_path, srcs=(src,))
    gaps, last = [], [time.monotonic()]

    def tick():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    t = QTimer()
    t.setInterval(10)
    t.timeout.connect(tick)
    t.start()
    mw.show_panel("download")
    mw.view.set_view(47.6, -122.35, 9)
    mw.view.rect = (-122.5, 47.5, -122.2, 47.7)
    mw.update_estimate()
    qtbot.waitUntil(lambda: mw.dl_panel.start_btn.isEnabled(), timeout=5000)
    mw.dl_panel.maxz.setValue(13)
    qtbot.waitUntil(lambda: mw.dl_panel.start_btn.isEnabled(), timeout=5000)
    qtbot.mouseClick(mw.dl_panel.start_btn, Qt.MouseButton.LeftButton)
    job = mw.manager.store.list()[0]
    qtbot.waitUntil(lambda: mw.manager.store.get(job.id).state == "completed", timeout=60000)
    t.stop()
    assert max(gaps[5:]) < 0.25, f"event loop stalled {max(gaps):.3f}s"
    mw.close()


def test_download_flow_live_tiles_progress(qtbot, tmp_path, tile_server):
    src = user_source(tile_server.url, name="Loopback test server")
    mw = make_window(qtbot, tmp_path, srcs=(src,))
    mw.show_panel("download")
    mw.view.set_view(47.6, -122.35, 10)
    qtbot.wait(50)
    _drag(mw.view, (mw.view.width() / 2 - 120, mw.view.height() / 2 - 80),
          (mw.view.width() / 2 + 120, mw.view.height() / 2 + 80))
    assert mw.view.rect is not None
    mw.dl_panel.minz.setValue(9)
    mw.dl_panel.maxz.setValue(12)
    qtbot.waitUntil(lambda: "tiles" in mw.dl_panel.estimate.text() and mw.dl_panel.start_btn.isEnabled(), timeout=5000)
    est = mw.last_estimate
    assert est["tiles"] == tm.count_tiles(mw.view.rect_bbox(), 9, 12)
    assert "Storage needed" in mw.dl_panel.estimate.text() and "Download permitted" in mw.dl_panel.permission.text()
    mw.dl_panel.name.setText("Test area")
    qtbot.mouseClick(mw.dl_panel.start_btn, Qt.MouseButton.LeftButton)
    job = mw.manager.store.list()[0]
    qtbot.waitUntil(lambda: mw.manager.store.get(job.id).state == "completed", timeout=60000)
    qtbot.waitUntil(lambda: "/" in mw.dl_panel.progress.text() and mw.dl_panel.bar.value() == 1000, timeout=5000)
    assert mw.view.layer and mw.view.layer.path.endswith("test-src.mbtiles")
    settle(qtbot, mw.view)
    assert mw.view.stats["downloaded"] > 0
    assert "completed" in mw.dl_panel.jobs.item(0).text().lower()
    mw.close()


def test_non_permitted_source_offers_import_only(qtbot, tmp_path):
    mw = make_window(qtbot, tmp_path)                       # shipped catalog
    mw.show_panel("download")
    i = mw.dl_panel.source.findData("osm-standard")
    assert i >= 0 and "not permitted" in mw.dl_panel.source.itemText(i)
    assert mw.dl_panel.source.currentData() != "osm-standard"   # a permitted source is preselected
    mw.dl_panel.source.setCurrentIndex(i)
    mw.view.rect = (-1, -1, 1, 1)
    mw.update_estimate()
    assert "Not permitted" in mw.dl_panel.permission.text() and "osmfoundation" in mw.dl_panel.permission.text()
    assert not mw.dl_panel.import_btn.isHidden()
    qtbot.wait(200)
    assert not mw.dl_panel.start_btn.isEnabled()
    mw.start_download()                                      # forced: still refused
    assert mw.manager.store.list() == []
    assert any("Cannot start" in e[1] for e in mw.dialogs.log if e[0] == "inform")
    mw.close()


def test_resume_prompt_after_crash(qtbot, tmp_path, tile_server):
    src = user_source(tile_server.url)
    from task_maps.downloader import JobManager
    m = JobManager(tmp_path / "data", sources.Catalog({src.id: src}))
    job = m.create_job(src.id, "Crash", BBox(-122.5, 47.5, -122.2, 47.7), 9, 11)
    m.store.set_state(job.id, "running")                    # as if power was lost mid-download
    m.shutdown()
    d = ScriptedDialogs(confirm=True)
    mw = make_window(qtbot, tmp_path, srcs=(src,), dialogs=d)
    qtbot.waitUntil(lambda: any(e[0] == "confirm" and "Resume" in e[1] for e in d.log), timeout=3000)
    qtbot.waitUntil(lambda: mw.manager.store.get(job.id).state == "completed", timeout=30000)
    mw.close()
    d2 = ScriptedDialogs(confirm=False)
    m = JobManager(tmp_path / "data2", sources.Catalog({src.id: src}))
    j2 = m.create_job(src.id, "Crash2", BBox(-122.5, 47.5, -122.2, 47.7), 9, 10)
    m.store.set_state(j2.id, "running")
    m.shutdown()
    mw2 = MainWindow(data_dir=tmp_path / "data2", dialogs=d2, catalog=sources.Catalog({src.id: src}),
                     start_gps=False, core_fn=lambda: (None, "x"))
    qtbot.addWidget(mw2)
    qtbot.waitUntil(lambda: mw2.manager.store.get(j2.id).state == "paused", timeout=3000)
    mw2.close()


def test_import_mbtiles_via_window(qtbot, tmp_path):
    src_file = labelled_mbtiles(tmp_path / "usb" / "region.mbtiles", ALL_Z2) if (tmp_path / "usb").mkdir() is None \
        else None
    d = ScriptedDialogs(open_path=str(src_file))
    mw = make_window(qtbot, tmp_path, dialogs=d)
    mw.import_mbtiles()
    qtbot.waitUntil(lambda: mw.view.layer is not None and mw.view.layer.name == "Fixture", timeout=10000)
    assert (tmp_path / "data" / "maps" / "imported" / "region.mbtiles").exists()
    assert mw.maps_panel.list.count() == 1
    bad = tmp_path / "usb" / "bad.mbtiles"
    bad.write_bytes(b"x" * 4096)
    d.open_path = str(bad)
    mw.import_mbtiles()
    qtbot.waitUntil(lambda: any(e[0] == "inform" and "failed" in e[1] for e in d.log), timeout=10000)
    mw.close()


def test_waypoints_tracks_gpx_overwrite(qtbot, tmp_path):
    out = tmp_path / "export.gpx"
    out.write_bytes(b"precious")
    d = ScriptedDialogs(confirm=False, save_path=str(out), text="Renamed")
    mw = make_window(qtbot, tmp_path, dialogs=d)
    mw.wpt_panel.by_click.setChecked(True)
    mw.view.set_view(47.6, -122.3, 12)
    _mouse(mw.view, QEvent.Type.MouseButtonPress, (100, 100), Qt.MouseButton.LeftButton)
    _mouse(mw.view, QEvent.Type.MouseButtonRelease, (100, 100), Qt.MouseButton.NoButton)
    wps = mw.store.waypoints()
    assert len(wps) == 1 and wps[0].source == "map"
    mw.rename_waypoint(wps[0].id)
    assert mw.store.get_waypoint(wps[0].id).name == "Renamed"
    mw.export_gpx()
    assert out.read_bytes() == b"precious"                  # declined: not overwritten
    d.answers["confirm"] = True
    mw.export_gpx()
    assert b"Renamed" in out.read_bytes() and b"urn:rain:task:gpx-ext:1" in out.read_bytes()
    # GPS waypoint + track recording through the GPS pipeline
    now = time.monotonic()
    st = apply_report(apply_report(GpsState(connection="connected"), TPV_FIX, now), SKY, now)
    mw._on_gps(st)
    mw.add_waypoint_at_gps()
    assert mw.store.waypoints()[-1].source == "gps" and mw.store.waypoints()[-1].accuracy_m == 4.2
    mw.wpt_panel.record.setChecked(True)
    for i in range(5):
        t = time.monotonic()
        msg = dict(TPV_FIX, lat=47.6062 + i * 0.0005)
        mw._on_gps(apply_report(mw.gps_state, msg, t))
    trk = mw.store.recording_track()
    assert trk is not None
    pts = [t for t in mw.store.tracks() if t.id == trk.id][0].points
    assert len(pts) == 5
    mw.wpt_panel.record.setChecked(False)
    assert mw.store.recording_track() is None
    mw.close()


def test_follow_mode_and_gps_panel(qtbot, tmp_path):
    mw = make_window(qtbot, tmp_path)
    mw.set_follow(True)
    now = time.monotonic()
    st = apply_report(apply_report(GpsState(connection="connected"), TPV_FIX, now), SKY, now)
    mw._on_gps(st)
    assert mw.view.lat == pytest.approx(47.6062) and mw.view.lon == pytest.approx(-122.3321)
    text = mw.gps_panel_text() if hasattr(mw, "gps_panel_text") else " ".join(
        lab.text() for lab in mw.gps_panel.findChildren(type(mw.coord_label)))
    assert "47.6062" in text and "3D" in text and "9" in text and "14" in text
    assert "no Core provider" in text or "checking" in text
    _drag(mw.view, (300, 300), (200, 200))
    assert not mw.tool["follow"].isChecked()                # manual pan leaves follow mode
    lost = apply_report(st, {"class": "TPV", "mode": 1}, now + 1)
    mw._on_gps(lost)
    assert "no fix" in mw.gps_label.text().lower()
    mw.close()


def test_settings_persist_view(qtbot, tmp_path):
    from task_maps import settings
    mw = make_window(qtbot, tmp_path)
    mw.view.set_view(10, 20, 7)
    mw.close()
    s = settings.load()
    assert s.view == [pytest.approx(10), pytest.approx(20), 7]


# ----------------------------------------------------------------- screenshots (TESTDATA)
def test_screenshots(qtbot, tmp_path, tile_server):
    out = shot_dir(tmp_path)
    fixture_world(tmp_path)
    tile_server.delay = 0.03
    src = user_source(tile_server.url, name="Loopback test tile server (user-attested)", rate_limit=8.0,
                      max_concurrency=2)
    cat_srcs = list(sources.load().sources.values()) + [src]
    for size in ((1920, 1080), (1024, 600)):
        tag = f"{size[0]}x{size[1]}"
        mw = make_window(qtbot, tmp_path, srcs=cat_srcs, size=size)
        mw.view.set_view(0, 0, 2.6)
        settle(qtbot, mw.view)
        mw.grab().save(str(out / f"01-map-fixture-tiles-{tag}.png"))
        assert mw.view.stats["downloaded"] > 0
        # missing coverage + overzoom (file max zoom is 3; z3 exists only for x1-2/y2-3)
        mw.view.set_view(42, -80, 3.7)
        settle(qtbot, mw.view)
        mw.grab().save(str(out / f"04-missing-coverage-overzoom-{tag}.png"))
        assert mw.view.stats["missing"] > 0 and mw.view.stats["overzoom"] > 0
        assert "Overzoom" in mw.oz_label.text()
        mw.close()
    # download dialog with rectangle + estimates, then progress (1920 and 1024)
    for size in ((1920, 1080), (1024, 600)):
        tag = f"{size[0]}x{size[1]}"
        fixture_world(tmp_path / ("dl" + tag))
        mw = make_window(qtbot, tmp_path / ("dl" + tag), srcs=cat_srcs, size=size)
        mw.show_panel("download")
        mw.dl_panel.source.setCurrentIndex(mw.dl_panel.source.findData("usgs-topo"))
        mw.view.set_view(47.6, -122.33, 9)
        mw.view.rect = (-122.55, 47.45, -122.1, 47.78)
        mw.dl_panel.minz.setValue(8)
        mw.dl_panel.maxz.setValue(14)
        mw.update_estimate()
        qtbot.waitUntil(lambda: "tiles" in mw.dl_panel.estimate.text(), timeout=5000)
        qtbot.wait(50)
        mw.grab().save(str(out / f"02-download-rectangle-estimate-{tag}.png"))
        mw.dl_panel.source.setCurrentIndex(mw.dl_panel.source.findData("test-src"))
        mw.dl_panel.minz.setValue(9)
        mw.dl_panel.maxz.setValue(13)
        mw.dl_panel.name.setText("Seattle test area")
        mw.update_estimate()
        qtbot.waitUntil(lambda: mw.dl_panel.start_btn.isEnabled(), timeout=5000)
        qtbot.mouseClick(mw.dl_panel.start_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: mw.manager.engine and mw.manager.engine.snapshot()["finished"] > 25, timeout=30000)
        mw.view.set_view(47.62, -122.33, 11)
        qtbot.wait(400)
        settle(qtbot, mw.view)
        mw.grab().save(str(out / f"03-download-progress-live-tiles-{tag}.png"))
        mw.manager.cancel()
        mw.close()
    # waypoints / track + GPS panel (fixture GPS data from the fake-gpsd reports)
    for size in ((1920, 1080), (1024, 600)):
        tag = f"{size[0]}x{size[1]}"
        fixture_world(tmp_path / ("w" + tag))
        mw = make_window(qtbot, tmp_path / ("w" + tag), srcs=cat_srcs, size=size)
        now = time.monotonic()
        st = apply_report(apply_report(GpsState(connection="connected", gpsd_version="3.25",
                                                devices=["/dev/ttyACM0"]), TPV_FIX, now), SKY, now)
        mw.store.add_waypoint("TEST Camp", 47.61, -122.34, source="map")
        mw.store.add_waypoint("TEST Ridge", 47.595, -122.31, source="map")
        from task_maps.waypoints import TrackPoint
        mw.store.add_track("TEST track", [TrackPoint(47.60 + i * 0.002, -122.345 + (i % 3) * 0.004) for i in range(8)],
                           source="gps")
        mw.refresh_waypoints()
        mw.view.set_view(47.605, -122.33, 13.5)
        mw._on_gps(st)
        mw.show_panel("waypoints")
        settle(qtbot, mw.view)
        mw.grab().save(str(out / f"05-waypoints-track-{tag}.png"))
        mw.show_panel("gps")
        mw._on_gps(st)
        qtbot.wait(50)
        mw.grab().save(str(out / f"06-gps-panel-{tag}.png"))
        mw.close()
    assert len(list(out.glob("*.png"))) == 12
