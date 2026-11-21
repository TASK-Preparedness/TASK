# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SDR Studio M2 Smart Scanner (task-sdr 0.2.1 behaviour, kept in 0.2.2): synthetic IQ only (task_sdr.sim_band), no hardware."""

import inspect
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from task_sdr import prefs as P  # noqa: E402
from task_sdr import scanner as S  # noqa: E402
from task_sdr.backends import RTL_BLOG_V4  # noqa: E402
from task_sdr.dsp import Demodulator  # noqa: E402
from task_sdr.engine import Engine  # noqa: E402
from task_sdr.scanner import History, HistoryEntry, IgnoreList, ScanConfig, Scanner, plan_chunks, vad  # noqa: E402
from task_sdr.sim_band import BandDevice  # noqa: E402

RATE = 1_024_000
SRC = Path(S.__file__).resolve().parent                # the task_sdr package actually under test
BENCH = Path(__file__).resolve().parents[1] / "bench"


def drive(tx, seconds, cfg=None, demod=True, noise=1e-3, scanner=None, on_block=None):
    d = BandDevice(tx, noise=noise)
    sc = scanner or Scanner(RATE, RTL_BLOG_V4)
    cfg = cfg or ScanConfig()
    d.configure(RATE, sc.start(cfg))
    dem = Demodulator(cfg.mode, RATE, bandwidth=cfg.channel_bw_hz)
    tunes = 0
    while d.t < seconds:
        iq = d.read(S.SCAN_BLOCK)
        a = sc.feed(iq)
        if a["tune"] is not None:
            d.set_frequency(a["tune"])
            tunes += 1
            dem = Demodulator(cfg.mode, RATE, bandwidth=cfg.channel_bw_hz)
        if demod and a["listen"]:
            for p in a["prebuffer"]:
                sc.on_audio(dem.process(p))
            if a["tune"] is None:
                sc.on_audio(dem.process(iq))
        if on_block:
            on_block(d, sc)
    return sc, d, tunes


def test_m01_plan_chunks_fast_and_range():
    cfg = ScanConfig()
    ch = cfg.channel_list(RTL_BLOG_V4)
    assert len(ch) == 321 and ch[0] == 144_000_000 and ch[-1] == 148_000_000
    chunks = plan_chunks(ch, RATE, 12_500)
    assert len(chunks) == 5                                   # FAST: 5 retunes per pass, not 321
    assert sorted(c for _, g in chunks for c in g) == ch
    for centre, g in chunks:
        assert all(abs(c - centre) <= RATE * S.USABLE / 2 for c in g)
    (centre, g), = plan_chunks([146_520_000], RATE, 12_500)
    assert centre != 146_520_000                              # single channel kept off DC
    with pytest.raises(ValueError):
        ScanConfig(start_hz=2_400_000_000, stop_hz=2_401_000_000).channel_list(RTL_BLOG_V4)
    with pytest.raises(ValueError):
        ScanConfig(start_hz=5_800_000_000, stop_hz=5_801_000_000).channel_list(RTL_BLOG_V4)
    part = ScanConfig(start_hz=1_765_000_000, stop_hz=1_770_000_000, step_hz=1_000_000).channel_list(RTL_BLOG_V4)
    assert part == [1_765_000_000, 1_766_000_000]             # 1766 MHz is the inclusive top; 1767+ dropped
    (centre, _), = plan_chunks([1_766_000_000], RATE, 12_500, accepts=RTL_BLOG_V4.accepts)
    assert RTL_BLOG_V4.accepts(centre)                        # offset centre stays inside the range


def test_m02_detects_and_locks_quickly_on_right_channel():
    sc, d, _ = drive([{"freq": 146_500_000, "start": 1.0, "dur": 2.0, "amp": 0.02}], 2.0)
    assert sc.state == "locked" and sc.locked == 146_500_000
    e = sc.history.items[0]
    assert e.freq_hz == 146_500_000 and 1.0 <= e.t_rx <= 1.0 + 0.2      # within ~2 passes (80 ms idle revisit)


def test_m03_hold_4s_and_resets_on_activity():
    # two bursts 2 s apart on one channel -> ONE history entry (hold reset), release 4 s after the last
    tx = [{"freq": 145_500_000, "start": 1.0, "dur": 1.0}, {"freq": 145_500_000, "start": 4.0, "dur": 1.0}]
    seen = {}

    def watch(d, sc):
        if sc.state == "scanning" and "lock_seen" in seen and "release" not in seen:
            seen["release"] = d.t
        if sc.state == "locked":
            seen["lock_seen"] = True
    sc, d, _ = drive(tx, 11.0, on_block=watch)
    assert len(sc.history.items) == 1
    assert 5.0 + 4.0 - 0.1 <= seen["release"] <= 5.0 + 4.0 + 0.2
    assert sc.stats["released_ended"] == 1
    assert sc.history.items[0].duration_s == pytest.approx(4.0, abs=0.15)


def test_m04_pause_resume_skip():
    tx = [{"freq": 146_000_000, "start": 0.5, "dur": 20.0}]
    sc, d, _ = drive(tx, 1.0)
    assert sc.state == "locked"
    sc.pause()
    assert sc.state == "paused"
    assert sc.feed(d.read(S.SCAN_BLOCK)) == {"tune": None, "listen": True, "prebuffer": []}
    nxt = sc.skip()                                           # skip: does not re-lock the same channel at once
    assert sc.state == "scanning" and nxt is not None and sc.stats["released_skipped"] == 1
    sc.stop()
    assert sc.state == "idle" and sc.feed(d.read(S.SCAN_BLOCK))["tune"] is None


def test_m05_ignore_session_persistent_tolerance_review():
    ig = IgnoreList([146_520_000])                            # migrated 0.2.1 entry: exact
    assert ig.match(146_520_000) and not ig.match(146_520_001)
    ig.add(147_000_000, tolerance_hz=5_000)
    assert ig.review() == [(146_520_000, "always", 0, 0, ""), (147_000_000, "session", 5_000, 5_000, "")]
    assert ig.match(147_005_000) and not ig.match(147_005_001)
    assert ig.remove(146_520_000) and not ig.match(146_520_000)
    # an ignored active channel is never locked; others still are
    tx = [{"freq": 146_000_000, "start": 0.5, "dur": 5.0}, {"freq": 147_000_000, "start": 0.5, "dur": 5.0}]
    sc = Scanner(RATE, RTL_BLOG_V4, persistent_ignores=[146_000_000])
    sc, d, _ = drive(tx, 2.0, scanner=sc)
    assert sc.locked == 147_000_000
    sc.ignore_current(persistent=False)
    assert [r[:2] for r in sc.ignores.review()] == [(146_000_000, "always"), (147_000_000, "session")]
    assert sc.state == "scanning"


def test_m06_history_50_with_pins():
    h = History()
    for i in range(3):
        h.add(HistoryEntry(100_000_000 + i, "NFM", 0, 0, -50))
    h.pin(1)                                                  # pin entry #2 (freq +1)
    for i in range(3, 80):
        h.add(HistoryEntry(100_000_000 + i, "NFM", 0, 0, -50))
    assert len([x for x in h.items if not x.pinned]) == 50
    assert any(x.pinned and x.freq_hz == 100_000_001 for x in h.items)
    assert h.items[0].freq_hz == 100_000_079                  # newest first
    h.clear()
    assert [x.freq_hz for x in h.items] == [100_000_001]


def test_m07_adaptive_floor_and_squelch():
    # strong noise floor: no false detections in 5 s; a weak signal under the user squelch is ignored
    sc, d, _ = drive([], 5.0, noise=2e-2)
    assert sc.stats["detections"] == 0
    weak = [{"freq": 145_000_000, "start": 1.0, "dur": 3.0, "amp": 0.003}]
    sc, _, _ = drive(weak, 3.0)
    assert sc.stats["detections"] == 1                        # adaptive floor finds it (≈ 20 dB SNR)
    sc, _, _ = drive(weak, 3.0, cfg=ScanConfig(squelch_dbfs=-20.0))
    assert sc.stats["detections"] == 0                        # user squelch above it


def test_m08_vad_and_dead_carrier_and_fallback():
    t = np.arange(48_000) / 48_000
    voice = np.sin(2 * np.pi * 700 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t))
    assert vad(voice, 48_000) is True
    assert vad(0.3 * np.sin(2 * np.pi * 1000 * t), 48_000) is False          # steady tone
    assert vad(np.zeros(48_000), 48_000) is False
    assert vad(voice[:100], 48_000) is None
    car = [{"freq": 146_000_000, "start": 0.5, "dur": 30.0, "kind": "carrier", "amp": 0.05}]
    sc, _, _ = drive(car, 13.0, cfg=ScanConfig(carrier_timeout_s=10.0))
    assert sc.stats["released_carrier_timeout"] == 1 and "carrier without voice" in sc.history.items[-1].note
    sc, _, _ = drive([dict(car[0], kind="voice")], 13.0, cfg=ScanConfig(carrier_timeout_s=10.0))
    assert sc.stats.get("released_carrier_timeout", 0) == 0 and sc.history.items[0].voice is True
    # CW (no voice) and VAD off: squelch-only, never released while the carrier stays
    for cfg in (ScanConfig(mode="CW", channel_bw_hz=500, carrier_timeout_s=2.0),
                ScanConfig(use_vad=False, carrier_timeout_s=2.0)):
        sc, _, _ = drive(car, 6.0, cfg=cfg, demod=cfg.mode != "CW")
        assert sc.state == "locked" and sc.history.items[0].voice is None


def test_m09_prebuffer_is_shifted_to_baseband():
    d = BandDevice([{"freq": 146_300_000, "start": 0.0, "dur": 5.0, "kind": "carrier", "amp": 0.05}])
    sc = Scanner(RATE, RTL_BLOG_V4)
    d.configure(RATE, sc.start(ScanConfig()))
    a = None
    while a is None or not a["prebuffer"]:
        a = sc.feed(d.read(S.SCAN_BLOCK))
        if a["tune"] and not a["prebuffer"]:
            d.set_frequency(a["tune"])
    assert a["tune"] == 146_300_000
    pre = a["prebuffer"][0]
    spec = np.abs(np.fft.fftshift(np.fft.fft(pre[:4096])))
    peak_hz = (np.argmax(spec) - 2048) * RATE / 4096
    assert abs(peak_hz) < 500                                 # the captured start is at the channel (0 Hz)


def test_m10_engine_integration_audio_only_when_locked():
    tmp = tempfile.mkdtemp()
    d = BandDevice([{"freq": 145_200_000, "start": 0.5, "dur": 3.0}])
    e = Engine(P.Prefs(), lambda: d, status_dir=tmp + "/s", claim_dir=tmp + "/c")
    e.profile, e.dev = RTL_BLOG_V4, d
    d.configure(RATE, e.prefs.freq_hz)
    sc = Scanner(RATE, RTL_BLOG_V4)
    e.start_scan(sc, ScanConfig())
    assert e.prefs.mode == "NFM" and e.prefs.freq_hz == sc.chunks[0][0]
    while d.t < 0.45:
        e.scan_step(sc, d.read(sc.block_size()))
    assert e.audio_q.empty() and e.frames[-1]["scan"]["state"] == "scanning"
    while d.t < 1.5:
        e.scan_step(sc, d.read(sc.block_size()))
    assert sc.locked == 145_200_000 and e.prefs.freq_hz == 145_200_000 and d.freq == 145_200_000
    assert not e.audio_q.empty()
    e.stop_scan()
    assert e.scanner is None and sc.state == "idle"


def test_m11_scanner_is_receive_only():
    for f in ("scanner.py", "sim_band.py", "ui/scanner_panel.py"):
        src = (SRC / f).read_text().lower()
        for bad in ("bias_tee", "set_bias", "transmit(", "tx_", "write_sync", "shell=true", "os.system", "subprocess"):
            assert bad not in src, (f, bad)
    calls = {n for n, _ in inspect.getmembers(Scanner, inspect.isfunction)}
    assert not any("tx" in n or "transmit" in n for n in calls)


def test_m12_prefs_round_trip_and_validation(tmp_path):
    p = P.Prefs(scan_ignores=[146_520_000], scan_step_hz=25_000, scan_mode="AM")
    P.save(p, tmp_path / "p.json")
    q = P.load(tmp_path / "p.json")
    assert q.scan_ignores == [146_520_000] and q.scan_step_hz == 25_000 and q.scan_mode == "AM"
    assert oct((tmp_path / "p.json").stat().st_mode & 0o777) == "0o600"
    for bad in ({"scan_mode": "XX"}, {"scan_step_hz": 0}, {"scan_ignores": ["x"]}):
        with pytest.raises(ValueError):
            P.Prefs(**bad).validate()


def test_m13_ui_panel(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    from task_sdr.ui.main_window import MainWindow
    from task_sdr.backends.simulated import SimulatedBackend
    from task_sdr import backends as B
    e = Engine(P.Prefs(), lambda: None, status_dir=str(tmp_path / "s"), claim_dir=str(tmp_path / "c"))
    w = MainWindow(e, None, tmp_path / "p.json", backends=[SimulatedBackend(), *[b for b in B.registry() if b.stub]])
    qtbot.addWidget(w)
    panel = w.scan
    panel.toggle()
    assert "Start the receiver first" in w.message.text()
    panel.start_e.setText("2400M")
    panel.stop_e.setText("2401M")
    w.start_btn.click()
    qtbot.waitUntil(lambda: e.state == "connected", timeout=5000)
    panel.toggle()
    assert "Scan not started" in w.message.text() and e.scanner is None
    panel.start_e.setText("162.4")
    panel.stop_e.setText("162.55")
    panel.step.setCurrentIndex(panel.step.findData(25_000))
    panel.toggle()
    assert e.scanner is not None and "Scanning 7 channels" in w.message.text()
    qtbot.waitUntil(lambda: panel.status.text().startswith(("Scanning", "LOCKED")), timeout=5000)
    w.tune(100_000_000)                                       # manual tune takes the receiver back
    assert e.scanner is None and panel.scan_btn.text() == "Scan"
    assert P.load(tmp_path / "p.json").scan_step_hz == 25_000
    w.close()
    assert e.scanner is None


def test_m14_benchmark_light_traffic_no_sweep_misses():
    sys.path.insert(0, str(BENCH))
    import bench_scanner
    r = bench_scanner.run(seconds=40, count=5)
    assert r["transmissions"] == 5 and r["missed_while_sweeping"] == 0
    assert r["detected"] + r["missed_receiver_busy"] == 5
    assert r["cpu_per_rx_second"] > 0 and r["tracemalloc_peak_mib"] < 50
