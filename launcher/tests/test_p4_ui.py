# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A UI: readiness lines, non-blocking probes, Library / Radio / Weather / Medical windows,
Mesh fallback sheet, tile actions, layouts at 1024×600 and 1920×1080. TESTDATA only."""

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from p4helpers import DATA, FakeKiwix, FakeTnc, ax25_ui, kiss
from task_launcher.services import direwolf, kiwix, medical, mesh, weather
from task_launcher.ui.dialogs import InfoSheet


def kiwix_status(port):
    c = kiwix.Candidate(port, "/kiwix/", source="TESTDATA unit", verified=True)
    books = kiwix.parse_opds((DATA / "opds_entries.xml").read_bytes())
    return kiwix.KiwixStatus(endpoint=c, candidates=[c], books=books)


def probe_result(kst=None, dw=None):
    kst = kst or kiwix.KiwixStatus()
    return {"kiwix": kst, "direwolf": dw or direwolf.DirewolfStatus(), "mesh": mesh.MeshStatus(),
            "weather": weather.WeatherStatus(), "medical": medical.collect(kst, (), module_dirs=()),
            "gpsd_open": False, "ref_error": ""}


def test_probes_do_not_block_the_ui(qtbot, launcher):
    started = threading.Event()

    def slow():
        started.set()
        time.sleep(1.5)
        return probe_result()

    t0 = time.monotonic()
    w = launcher(start=False, scan=False, start_workers=True, net_reader=lambda: None, probe_fn=slow)
    assert time.monotonic() - t0 < 1.2
    assert started.wait(2)
    ticks = []
    from PySide6.QtCore import QTimer
    tm = QTimer()
    tm.timeout.connect(lambda: ticks.append(1))
    tm.start(20)
    qtbot.waitUntil(lambda: w.probes.kiwix is not None, timeout=5000)
    tm.stop()
    assert len(ticks) >= 20                         # the event loop kept running during the probe
    lib = w.home.tile_widget("app:task.library")
    assert lib.ready_line == "No Kiwix server or library found"


def test_readiness_lines_on_tiles(qtbot, launcher):
    w = launcher(start=False)
    w._on_probes(probe_result())
    lines = {t.tile.key: (t.state_line, t.ready_line) for t in w.home.tiles}
    assert lines["app:task.library"] == ("Available — native viewer", "No Kiwix server or library found")
    assert lines["app:task.radio"][1] == "Direwolf not installed"
    assert lines["app:task.weather"][1] == "No weather sources or local data · no forecast"
    assert lines["app:task.medical"][1] == "No offline medical reference found"
    assert lines["app:task.sdr"][1] == "RTL-SDR: unknown (task-core not connected)"
    assert lines["app:task.maps"][1] == "Core: not connected · gpsd not reachable"
    assert lines["app:task.mission-planner"] == ("Planned", "")
    assert lines["app:task.system"] == ("", "") and lines["app:task.files"] == ("", "")


@pytest.mark.parametrize("size", [(1024, 600), (1920, 1080)])
def test_layouts_with_readiness_lines_do_not_clip(qtbot, launcher, size):
    w = launcher(start=False, size=size)
    w._on_probes(probe_result())
    QApplication.processEvents()
    for t in w.home.tiles:
        r = t.tile_rect()
        name, state, icon = t.text_rects()
        for rect in (name, state, icon, t.ready_rect()):
            if rect is not None:
                assert r.contains(rect), (t.tile.name, size, rect, r)


def test_library_window_search_and_read(qtbot, launcher, local_port):
    with FakeKiwix("/kiwix/") as fk:
        local_port(fk.port)
        w = launcher(start=False)
        w._on_probes(probe_result(kiwix_status(fk.port)))
        lib = w.open_builtin("library")
        assert lib.books.count() == 3 and "verified" in lib.status.text()
        lib.books.setCurrentRow(0)
        lib.query.setText("water")
        lib.do_search()
        qtbot.waitUntil(lambda: lib.results.count() == 2 and "Water purification" in lib.results.item(0).text(),
                        timeout=5000)
        lib._hit_activated(lib.results.item(0))
        qtbot.waitUntil(lambda: "TESTDATA article" in lib.view.toPlainText(), timeout=5000)
        lib.open_main()
        qtbot.waitUntil(lambda: "TESTDATA Main Page" in lib.view.toPlainText(), timeout=5000)
        assert "alert" not in lib.view.toHtml()
        from PySide6.QtCore import QUrl
        lib._link_clicked(QUrl("https://example.invalid/out"))       # external: refused, nothing fetched
        assert not any("example" in r for r in fk.requests)


def test_library_window_offline_state(qtbot, launcher):
    w = launcher(start=False)
    w._on_probes(probe_result())
    lib = w.open_builtin("library")
    assert "No reachable Kiwix server" in lib.status.text() and not lib.search_btn.isEnabled()


def test_radio_window_receive_only_monitor(qtbot, launcher, local_port):
    frames = [kiss(ax25_ui("N0CALL-7", "APRS", "!4903.50N/07201.75W-hello", ["WIDE1-1"]))]
    with FakeTnc(frames) as tnc:
        local_port(tnc.port)
        dw = direwolf.DirewolfStatus(binary="/usr/bin/direwolf", kiss_open={tnc.port: True})
        w = launcher(start=False)
        w._on_probes(probe_result(dw=dw))
        win = w.open_builtin("radio")
        assert any(l.text().startswith("RECEIVE ONLY") for l in win.findChildren(type(win.mon_state)))
        assert win.start_btn.isEnabled()
        win.start_monitor()
        qtbot.waitUntil(lambda: win.table.rowCount() == 1, timeout=5000)
        assert win.table.item(0, 1).text() == "N0CALL-7" and win.table.item(0, 3).text() == "position"
        win.stop_monitor()
        qtbot.waitUntil(lambda: win.monitor is None, timeout=5000)
        assert tnc.client_closed.wait(5) and bytes(tnc.received) == b""


def test_radio_window_shows_config_without_secrets(qtbot, launcher, tmp_path):
    c = direwolf.parse_config((DATA / "direwolf.conf").read_text(), "/home/op/direwolf.conf")
    dw = direwolf.DirewolfStatus(binary="/usr/bin/direwolf", configs=[c], kiss_open={8001: False})
    w = launcher(start=False)
    w._on_probes(probe_result(dw=dw))
    win = w.open_builtin("radio")
    text = win.info.text()
    assert "N0CALL-10" in text and "12345" not in text and "TRANSMIT-CAPABLE" in text
    assert not win.start_btn.isEnabled()                   # no open KISS port → no monitor


def test_weather_and_medical_windows_are_honest(qtbot, launcher):
    w = launcher(start=False)
    w._on_probes(probe_result())
    wx = w.open_builtin("weather")
    assert "no forecast" in wx.text.toPlainText() and "None configured" in wx.text.toPlainText()
    med = w.open_builtin("medical")
    assert med.list.item(0).text() == "No offline medical reference material found on this device."


def test_medical_kiwix_item_opens_library(qtbot, launcher, local_port):
    with FakeKiwix("/kiwix/") as fk:
        local_port(fk.port)
        w = launcher(start=False)
        w._on_probes(probe_result(kiwix_status(fk.port)))
        med = w.open_builtin("medical")
        assert med.list.count() == 1 and "mdwiki" in med.list.item(0).text()
        lib = med._open(med.list.item(0))
        assert lib.selected_book().name == "mdwiki_en_all_testdata"


def test_mesh_unavailable_sheet_is_labelled_temporary(qtbot, launcher):
    w = launcher(start=False)
    w._on_probes(probe_result())
    sheet = w.activate(w.registry.get("app:task.mesh"))
    assert isinstance(sheet, InfoSheet)
    text = " ".join(l.text() for l in sheet.findChildren(type(w.home.title)))
    assert "temporary, not the Mesh app" in text and "/usr/bin/task-mesh" in text
    assert "meshtastic command-line tool alone does not count" in text


def test_tile_menu_lists_actions(qtbot, launcher):
    w = launcher(start=False)
    menu = w.tile_menu(w.home.tile_widget("app:task.maps"), None)
    labels = [a.text() for a in menu.actions()]
    assert "GPS monitor (gpsmon, terminal)" in labels and "GPS status (cgps, terminal)" in labels
    menu.close()


def test_existing_builtins_still_open(qtbot, launcher):
    w = launcher(start=False)
    for which in ("system", "app-manager", "devices"):
        win = w.open_builtin(which)
        assert win.isVisible()
        win.close()


def test_native_window_closing_stops_workers(qtbot, launcher, local_port):
    from task_launcher.workers import live_workers
    with FakeKiwix("/kiwix/") as fk:
        local_port(fk.port)
        w = launcher(start=False)
        w._on_probes(probe_result(kiwix_status(fk.port)))
        lib = w.open_builtin("library")
        lib.books.setCurrentRow(0)
        lib.open_main()
        lib.close()
        assert not [x for x in live_workers() if x.objectName().startswith("kiwix")]


def test_compact_tile_keeps_fallback_label_visible(qtbot, launcher, tmp_path, safe_dir):
    from test_p4_render import simulated_registry
    w = launcher(start=False, size=(1024, 600), registry=simulated_registry(tmp_path, safe_dir))
    t = w.home.tile_widget("app:task.maps")
    assert t.state_line == "Available — FoxtrotGPS (fallback)"
    assert t.fitted_state_line() in ("Available — FoxtrotGPS (fallback)", "FoxtrotGPS (fallback)")
    assert "FoxtrotGPS (fallback)" in t.toolTip() and "FoxtrotGPS (fallback)" in t.accessibleDescription()


def test_app_manager_detail_shows_candidates_readiness_actions(qtbot, launcher):
    w = launcher(start=False)
    w._on_probes(probe_result())
    am = w.open_builtin("app-manager")
    for r in range(am.table.rowCount()):
        if am.table.item(r, 0).text() == "Maps & GPS":
            am.table.selectRow(r)
    am.render_detail()
    text = am.detail.text()
    assert "/usr/bin/task-maps (T.A.S.K. Maps), /usr/bin/foxtrotgps (FoxtrotGPS (fallback))" in text
    assert "Readiness (display only): Core: not connected · gpsd not reachable" in text
    assert "GPS monitor (gpsmon, terminal)" in text
