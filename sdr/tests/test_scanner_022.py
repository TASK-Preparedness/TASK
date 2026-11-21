# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-sdr 0.2.2 scanner corrections: ignore tolerance (exact default, cap, boundaries, migration), history
actions, carrier-only timeout OFF by default, Scan/Pause/Resume/Skip state machine. Synthetic IQ only."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from task_sdr import prefs as P  # noqa: E402
from task_sdr import scanner as S  # noqa: E402
from task_sdr.backends import RTL_BLOG_V4  # noqa: E402
from task_sdr.engine import Engine  # noqa: E402
from task_sdr.scanner import TRANSITIONS, IgnoreList, ScanConfig, Scanner, cap_for_spacing  # noqa: E402
from task_sdr.sim_band import BandDevice  # noqa: E402

from test_scanner import RATE, drive  # noqa: E402

COMMANDS = ("scan", "stop", "pause", "resume", "skip")


def make_state(name):
    """Real scanner driven into `name` with synthetic IQ (no shortcuts on the state field)."""
    d = BandDevice([{"freq": 146_000_000, "start": 0.2, "dur": 60.0}])
    sc = Scanner(RATE, RTL_BLOG_V4)
    if name == "idle":
        return sc, d
    d.configure(RATE, sc.start(ScanConfig()))
    if name in ("locked", "paused/L"):
        while sc.state != "locked":
            a = sc.feed(d.read(S.SCAN_BLOCK))
            if a["tune"] is not None:
                d.set_frequency(a["tune"])
    if name.startswith("paused"):
        assert sc.pause()
    return sc, d


def state_of(sc):
    return f"paused/{sc.paused_from[0].upper()}" if sc.state == "paused" else sc.state


@pytest.mark.parametrize("start", ["idle", "scanning", "locked", "paused/S", "paused/L"])
@pytest.mark.parametrize("cmd", COMMANDS)
def test_t01_state_machine_table(start, cmd):
    sc, d = make_state(start)
    assert state_of(sc) == start
    if cmd == "scan":
        sc.start(ScanConfig())
    else:
        getattr(sc, cmd)()
    assert state_of(sc) == TRANSITIONS.get((start, cmd), start), (start, cmd)
    if start == "paused/L" and cmd == "resume":
        assert sc.locked == 146_000_000
    if start in ("locked", "paused/L") and cmd == "skip":
        assert sc.stats["released_skipped"] == 1


def test_t02_paused_semantics_and_hold_freeze():
    sc, d = make_state("paused/L")
    for _ in range(int(6.0 / (S.SCAN_BLOCK / RATE))):          # 6 s paused: longer than the 4 s hold
        assert sc.feed(d.read(S.SCAN_BLOCK)) == {"tune": None, "listen": True, "prebuffer": []}
    assert sc.state == "paused"
    sc.resume()
    assert sc.state == "locked" and sc.snapshot()["hold_left"] == pytest.approx(4.0, abs=0.05)
    sc2, d2 = make_state("paused/S")
    ci = sc2.ci
    for _ in range(50):
        assert sc2.feed(d2.read(S.SCAN_BLOCK)) == {"tune": None, "listen": False, "prebuffer": []}
    assert sc2.ci == ci


def test_t03_tolerance_default_exact_and_cap_boundaries():
    assert cap_for_spacing(12_500) == 6_249 and cap_for_spacing(25_000) == 12_499 and cap_for_spacing(None) is None
    ig = IgnoreList()
    e = ig.add(146_500_000)
    assert e.tolerance_hz == 0 and ig.match(146_500_000) and not ig.match(146_500_001)
    ig.edit(146_500_000, tolerance_hz=6_249)
    ig.cap_hz = cap_for_spacing(12_500)
    assert ig.match(146_506_249) and not ig.match(146_506_250) and not ig.match(146_512_500)
    ig.edit(146_500_000, tolerance_hz=50_000)
    assert ig.effective_tolerance(ig.entries[146_500_000]) == 6_249
    assert not ig.match(146_512_500) and not ig.match(146_487_500)
    with pytest.raises(ValueError):
        ig.edit(146_500_000, tolerance_hz=-1)
    with pytest.raises(ValueError):
        ig.add(1, tolerance_hz=1_000_001)


def test_t04_adjacent_channel_still_detected_with_large_tolerance():
    sc = Scanner(RATE, RTL_BLOG_V4)
    sc.ignores.add(146_500_000, persistent=True, tolerance_hz=100_000)
    sc, _, _ = drive([{"freq": 146_512_500, "start": 0.5, "dur": 5.0}], 2.0, scanner=sc)
    assert sc.locked == 146_512_500
    sc2 = Scanner(RATE, RTL_BLOG_V4)
    sc2.start(ScanConfig(channels=[146_500_000, 146_525_000, 147_000_000]))
    assert sc2.ignores.cap_hz == 12_499


def test_t05_edit_remove_one_entry_never_neighbours():
    ig = IgnoreList([146_500_000, 146_512_500])
    ig.edit(146_500_000, tolerance_hz=10_000)
    assert ig.remove(146_500_000)
    assert ig.persistent == [146_512_500]
    assert not ig.remove(146_500_000)
    ig.add(147_000_000)
    ig.edit(147_000_000, persistent=True, label="birdie")
    ig.add(147_100_000, persistent=False)
    entries, legacy = ig.to_prefs()
    assert legacy == [146_512_500, 147_000_000]
    assert {"freq_hz": 147_000_000, "tolerance_hz": 0, "label": "birdie"} in entries
    assert [r[1] for r in ig.review()] == ["always", "always", "session"]


def test_t06_migration_from_021_is_lossless_and_rollback_compatible(tmp_path):
    old = {"freq_hz": 146_520_000, "mode": "NFM", "scan_ignores": [146_520_000, 147_000_000, 162_550_000],
           "scan_step_hz": 12_500}
    f = tmp_path / "prefs.json"
    f.write_text(json.dumps(old))
    pr = P.load(f)
    lst = P.ignore_list(pr)
    assert sorted(lst) == [146_520_000, 147_000_000, 162_550_000]
    sc = Scanner(RATE, RTL_BLOG_V4, persistent_ignores=lst)
    assert [(r[0], r[1], r[2]) for r in sc.ignores.review()] == [
        (146_520_000, "always", 0), (147_000_000, "always", 0), (162_550_000, "always", 0)]
    sc.ignores.edit(147_000_000, tolerance_hz=2_500)
    P.store_ignores(pr, sc.ignores)
    P.save(pr, f)
    data = json.loads(f.read_text())
    assert data["scan_ignores"] == [146_520_000, 147_000_000, 162_550_000]
    assert {"freq_hz": 147_000_000, "tolerance_hz": 2_500, "label": ""} in data["scan_ignore_entries"]
    again = Scanner(RATE, RTL_BLOG_V4, persistent_ignores=P.ignore_list(P.load(f)))
    assert [(r[0], r[2]) for r in again.ignores.review()] == [(146_520_000, 0), (147_000_000, 2_500),
                                                              (162_550_000, 0)]


def test_t07_carrier_timeout_off_by_default_and_configurable():
    assert ScanConfig().carrier_timeout_s is None and P.Prefs().scan_carrier_timeout_s is None
    car = [{"freq": 146_000_000, "start": 0.5, "dur": 60.0, "kind": "carrier", "amp": 0.05}]
    sc, _, _ = drive(car, 30.0)
    assert sc.state == "locked" and sc.stats.get("released_carrier_timeout", 0) == 0
    assert sc.history.items[0].voice is False
    sc, _, _ = drive(car, 8.0, cfg=ScanConfig(carrier_timeout_s=5.0))
    assert sc.stats["released_carrier_timeout"] == 1 and "after 5 s" in sc.history.items[-1].note
    for bad in (0, 3601):
        with pytest.raises(ValueError):
            P.Prefs(scan_carrier_timeout_s=bad).validate()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    from task_sdr import backends as B
    from task_sdr.backends.simulated import SimulatedBackend
    from task_sdr.ui.main_window import MainWindow
    e = Engine(P.Prefs(), lambda: None, status_dir=str(tmp_path / "s"), claim_dir=str(tmp_path / "c"))
    w = MainWindow(e, None, tmp_path / "p.json", backends=[SimulatedBackend(), *[b for b in B.registry() if b.stub]])
    qtbot.addWidget(w)
    yield w, e, tmp_path
    w.close()


def test_t08_no_autostart(window):
    w, e, _ = window
    assert e._thread is None and e.scanner is None and w.scan.scanner.state == "idle"
    assert not w.scan.pause_btn.isEnabled() and not w.scan.resume_btn.isEnabled()
    assert w.scan.carrier_on.isChecked() is False and "OFF" in w.scan.carrier_off_note.text()


def _fill_history(panel, n, start=146_000_000):
    from task_sdr.scanner import HistoryEntry
    with panel.scanner.lock:
        for i in range(n):
            panel.scanner.history.add(HistoryEntry(start + i * 12_500, "NFM", 0.0, 0.0, -40.0))
    panel.refresh(force=True)


def test_t09_history_actions_buttons_and_context_menu(window, qtbot):
    w, e, tmp = window
    p = w.scan
    _fill_history(p, 3)
    assert set(p.h_actions) == {"retune", "ignore", "ignore_always", "unignore", "bm_add", "bm_remove", "pin", "clear"}
    newest = 146_000_000 + 2 * 12_500
    p.history.setCurrentRow(0)
    p.h_actions["bm_add"].click()
    assert any(b["freq_hz"] == newest for b in e.prefs.bookmarks) and w.bookmarks.count() == 1
    assert P.load(tmp / "p.json").bookmarks[0]["freq_hz"] == newest
    p.history.setCurrentRow(0)
    p.h_actions["bm_remove"].click()
    assert not e.prefs.bookmarks and w.bookmarks.count() == 0
    p.history.setCurrentRow(0)
    p.h_actions["ignore_always"].click()
    assert p.scanner.ignores.review()[0][:2] == (newest, "always")
    assert newest in P.load(tmp / "p.json").scan_ignores
    p.history.setCurrentRow(0)
    p.h_actions["unignore"].click()
    assert not p.scanner.ignores.entries and P.load(tmp / "p.json").scan_ignores == []
    p.history.setCurrentRow(1)
    p.h_actions["ignore"].click()
    assert p.scanner.ignores.review()[0][1] == "session" and P.load(tmp / "p.json").scan_ignores == []
    p.history.setCurrentRow(2)
    p.h_actions["pin"].click()
    assert p.scanner.history.items[2].pinned
    p.history.setCurrentRow(2)
    p.h_actions["retune"].click()
    assert e.prefs.freq_hz == 146_000_000 and w.tuner.hz == 146_000_000
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMenu
    seen = []

    def grab():
        m = QApplication.activePopupWidget()
        if isinstance(m, QMenu):
            seen.extend(a.text() for a in m.actions())
            m.close()
    QTimer.singleShot(200, grab)
    p._history_menu(p.history.rect().center())
    assert seen == [b.text() for b in p.h_actions.values()]


def test_t10_history_50_newest_first_pins_kept_through_ui(window):
    w, e, _ = window
    p = w.scan
    _fill_history(p, 3)
    p.history.setCurrentRow(2)
    p.h_actions["pin"].click()
    _fill_history(p, 70, start=150_000_000)
    items = p.scanner.history.items
    assert len([x for x in items if not x.pinned]) == 50 and p.history.count() == 51
    assert items[0].freq_hz == 150_000_000 + 69 * 12_500
    assert any(x.pinned and x.freq_hz == 146_000_000 for x in items)
    p.h_actions["clear"].click()
    assert [x.freq_hz for x in p.scanner.history.items] == [146_000_000]


def test_t11_ignore_editor_units_and_kind(window):
    w, e, tmp = window
    p = w.scan
    p.scanner.ignores.add(146_520_000, persistent=False)
    p.refresh(force=True)
    p.ignored.setCurrentRow(0)
    p.edit_tol.unit.setCurrentText("kHz")
    p.edit_tol.num.setValue(2.5)
    p.edit_apply.click()
    assert p.scanner.ignores.entries[146_520_000].tolerance_hz == 2_500
    assert "±2.5 kHz" in p.ignored.item(0).text() and "[Session]" in p.ignored.item(0).text()
    p.ignored.setCurrentRow(0)
    p.make_always.click()
    assert "[Always]" in p.ignored.item(0).text()
    assert P.load(tmp / "p.json").scan_ignore_entries == [{"freq_hz": 146_520_000, "tolerance_hz": 2_500, "label": ""}]
    p.ignored.setCurrentRow(0)
    p.edit_tol.unit.setCurrentText("Hz")
    p.edit_tol.num.setValue(0)
    p.edit_apply.click()
    assert "exact" in p.ignored.item(0).text()
    p.ignored.setCurrentRow(0)
    p.unign_btn.click()
    assert p.ignored.count() == 0 and P.load(tmp / "p.json").scan_ignore_entries == []


def test_t12_live_ui_scan_pause_resume_skip(window, qtbot):
    w, e, tmp = window
    p = w.scan
    w.start_btn.click()
    qtbot.waitUntil(lambda: e.state == "connected", timeout=5000)
    p.start_e.setText("162.4")
    p.stop_e.setText("162.55")
    p.step.setCurrentIndex(p.step.findData(25_000))
    p.toggle()
    assert e.scanner is not None
    qtbot.waitUntil(lambda: p.scanner.state in ("scanning", "locked"), timeout=3000)
    p.pause_btn.click()
    assert p.scanner.state == "paused" and p.resume_btn.isEnabled() and not p.pause_btn.isEnabled()
    p.resume_btn.click()
    assert p.scanner.state in ("scanning", "locked")
    p.skip_btn.click()
    assert p.scanner.state == "scanning"
    p.toggle()
    assert e.scanner is None and p.scanner.state == "idle" and p.scan_btn.text() == "Scan"
