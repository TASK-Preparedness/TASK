# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""0.2.3 frequency audit: frequencies are exact integer Hz with no 32-bit, float or coercion surprises.
Covers >2**31, >2**32, negatives, NaN/inf, floats, strings, bools, huge strings, GHz precision, out-of-range input,
Qt signal transport, prefs JSON, bookmarks/presets/ignores/scanner, the RTL uint32 boundary and overlay isolation."""

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from task_sdr import freq as F
from task_sdr import prefs as P
from task_sdr import tuner as T
from task_sdr.backends import RTL_BLOG_V4, DeviceProfile, RangeError
from task_sdr.engine import Engine
from task_sdr.scanner import IgnoreList, ScanConfig

BIG = [2**31 - 1, 2**31, 2**31 + 1, 2**32 - 1, 2**32, 2**32 + 1, 5_999_999_999, 10_000_000_001]
JUNK = [146.52e6, 146_000_000.0, float("nan"), float("inf"), float("-inf"), "146000000", b"1", None, True, False,
        np.float64(146e6), np.float32(146e6), [146_000_000], {"hz": 1}, complex(1, 0)]


# ---------------------------------------------------------------- core
@pytest.mark.parametrize("v", BIG + [0, 1, np.int64(2**33), np.int32(146_000_000), np.uint64(2**36)])
def test_f01_strict_hz_accepts_exact_ints(v):
    out = F.hz(v)
    assert type(out) is int and out == int(v)


@pytest.mark.parametrize("v", JUNK, ids=repr)
def test_f02_strict_hz_rejects_non_ints(v):
    with pytest.raises(F.FrequencyError):
        F.hz(v)
    assert F.is_hz(v) is False


@pytest.mark.parametrize("v", [-1, -(2**31), -(2**63), F.ABS_MAX_HZ + 1, 10**400])
def test_f03_strict_hz_bounds(v):
    with pytest.raises(F.FrequencyError):
        F.hz(v)


# ---------------------------------------------------------------- tuner text and digits
@pytest.mark.parametrize("text,hz", [
    ("2147483648", 2_147_483_648), ("4294967297", 4_294_967_297), ("4294.967297M", 4_294_967_297),
    ("1766.000001M", 1_766_000_001), ("5999.999999 MHz", 5_999_999_999), ("9.999999999G", 9_999_999_999),
    ("99.999999999 GHz", 99_999_999_999), ("146.52", 146_520_000), ("0.000001", 1), ("1.2345675M", 1_234_568),
    ("1.2345665M", 1_234_566), ("02.147.483.648", 2_147_483_648), ("162,550,000", 162_550_000),
])
def test_f04_parse_exact_at_ghz(text, hz):
    out = T.parse(text)
    assert type(out) is int and out == hz


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "1e9", "-146", "146.52x", "", ".", "..", "1.2.3M",
                                  "100G", "100000000000", "9" * 41, "1" * 10_000, "0x10", "146,52,0.5,5",
                                  "\u0661\u0664\u0666"])
def test_f05_parse_rejects_cleanly(text):
    with pytest.raises(ValueError):           # never OverflowError/InvalidOperation leaking out
        T.parse(text)


def test_f06_digit_tuner_rejects_junk_without_exceptions():
    t = T.DigitTuner(146_000_000, RTL_BLOG_V4.accepts, lambda h: "outside the receiver's range")
    for v in JUNK + [2**31, 2**32, -5, 10**30]:
        assert t.set_hz(v) is False and t.hz == 146_000_000 and t.last_rejection
    assert t.enter("2147.483648M") is False and t.hz == 146_000_000          # above this receiver
    assert t.enter("1" * 10_000) is False and "too long" in t.last_rejection
    wide = DeviceProfile("wide test profile", 1, 99_999_999_999)
    t2 = T.DigitTuner(146_000_000, wide.accepts, lambda h: "outside")
    for v in BIG:
        assert t2.set_hz(v) is True and t2.hz == v and type(t2.hz) is int
    t2.set_hz(4_294_967_295)
    assert t2.step(0, +1) and t2.hz == 4_294_967_296                         # carry across 2**32
    assert T.format_hz(t2.hz) == "04.294.967.296"
    with pytest.raises(ValueError):
        T.DigitTuner(146.0e6)


# ---------------------------------------------------------------- receiver limits
def test_f07_profile_check_strict_and_per_receiver():
    assert RTL_BLOG_V4.check(np.int64(146_000_000)) == 146_000_000
    for v in BIG + [-1, 0, 499_999, 1_766_000_001]:
        with pytest.raises(RangeError):
            RTL_BLOG_V4.check(v)
        assert RTL_BLOG_V4.accepts(v) is False
    for v in JUNK:
        with pytest.raises(RangeError):
            RTL_BLOG_V4.check(v)
        assert RTL_BLOG_V4.accepts(v) is False
    assert RTL_BLOG_V4.check(1_766_000_000) == 1_766_000_000 and RTL_BLOG_V4.check(500_000) == 500_000


def test_f08_engine_retune_rejects_and_changes_nothing(tmp_path):
    e = Engine(P.Prefs(), lambda: None, status_dir=str(tmp_path / "s"), claim_dir=str(tmp_path / "c"))
    before = e.prefs.freq_hz
    for v in BIG + [x for x in JUNK if x is not None] + [-1]:      # freq_hz=None means "leave unchanged"
        with pytest.raises(RangeError):
            e.retune(freq_hz=v)
        with pytest.raises(RangeError):
            e.retune_checked(v)
        assert e.prefs.freq_hz == before
    assert e.retune_checked(np.int64(162_400_000)) == 162_400_000 and type(e.prefs.freq_hz) is int


def test_f09_rtlsdr_uint32_guard():
    from task_sdr.backends.rtlsdr import RtlSdrDevice
    calls = []

    class Lib:
        def rtlsdr_set_center_freq(self, h, hz):
            calls.append(hz)
            return 0
    d = object.__new__(RtlSdrDevice)
    d.lib, d.h, d.profile = Lib(), None, DeviceProfile("hypothetical wide", 1, 99_999_999_999)
    for v in (2**32, 2**32 + 1, 5_000_000_000):
        with pytest.raises(RangeError, match="uint32"):
            d.set_frequency(v)
    d.set_frequency(2**32 - 1)
    d.set_frequency(1_766_000_000)
    assert calls == [2**32 - 1, 1_766_000_000]
    d.profile = RTL_BLOG_V4
    for v in (146.52e6, float("nan"), "146000000", True):
        with pytest.raises(RangeError):
            d.set_frequency(v)
    assert calls == [2**32 - 1, 1_766_000_000]


# ---------------------------------------------------------------- prefs JSON
def _load(tmp_path, **kv):
    p = tmp_path / "prefs.json"
    d = {"freq_hz": 146_520_000}
    d.update(kv)
    p.write_text(json.dumps(d))
    return P.load(p)


@pytest.mark.parametrize("bad", [146.52e6, 146_520_000.0, "146520000", True, None, -146_520_000, 2**31, 2**32,
                                 2**63, 10**400, float("nan"), float("inf")], ids=repr)
def test_f10_prefs_freq_rejected_to_defaults(tmp_path, bad):
    assert _load(tmp_path, freq_hz=bad).freq_hz == P.Prefs().freq_hz


def test_f11_prefs_raw_json_specials(tmp_path):
    p = tmp_path / "prefs.json"
    for raw in ('{"freq_hz": NaN}', '{"freq_hz": Infinity}', '{"freq_hz": -Infinity}', '{"freq_hz": 1e400}',
                '{"freq_hz": 146520000e0}', '[146520000]', '146520000', '"x"', '{"freq_hz": ' + "9" * 5000 + "}"):
        p.write_text(raw)
        assert P.load(p).freq_hz == P.Prefs().freq_hz, raw
    p.write_text('{"freq_hz": 146520000}')
    assert P.load(p).freq_hz == 146_520_000


def test_f12_prefs_lists_drop_only_bad_entries(tmp_path):
    good_bm = {"name": "ok", "freq_hz": 146_520_000, "mode": "NFM", "bandwidth_hz": None}
    far_bm = {"name": "far (kept; tune is rejected per receiver)", "freq_hz": 5_000_000_000, "mode": "NFM"}
    pr = _load(tmp_path,
               bookmarks=[good_bm, far_bm, {"name": "f", "freq_hz": 146.5e6}, {"name": "s", "freq_hz": "1"},
                          {"name": "b", "freq_hz": True}, {"name": "neg", "freq_hz": -1}, "junk",
                          {"name": "mode", "freq_hz": 1, "mode": "TX"}],
               presets=[{"name": "p", "freq_hz": 162_400_000, "mode": "NFM"}, {"name": "x", "freq_hz": 1e9}],
               scan_ignores=[146_000_000, 146.0e6, True, -5, 2**33],
               scan_ignore_entries=[{"freq_hz": 146_010_000, "tolerance_hz": 0},
                                    {"freq_hz": 146_020_000, "tolerance_hz": 2.5},
                                    {"freq_hz": 146_030_000.0}, {"freq_hz": 146_040_000, "tolerance_hz": 10**7}])
    assert pr.freq_hz == 146_520_000
    assert pr.bookmarks == [good_bm, far_bm]
    assert [p["name"] for p in pr.presets] == ["p"]
    assert pr.scan_ignores == [146_000_000, 2**33]
    assert [e["freq_hz"] for e in pr.scan_ignore_entries] == [146_010_000]


@pytest.mark.parametrize("field,bad", [("sample_rate", 1.024e6), ("scan_step_hz", 12.5e3), ("scan_start_hz", "1"),
                                       ("scan_stop_hz", float("inf")), ("bandwidth_hz", 12.5e3), ("ppm", 1.5),
                                       ("ppm", True), ("scan_ignore_tol_hz", 1.0), ("scan_step_hz", 0)])
def test_f13_prefs_scalar_hz_fields_strict(tmp_path, field, bad):
    with pytest.raises(ValueError):
        P.Prefs(**{field: bad}).validate()


def test_f14_prefs_roundtrip_large_ints_exact(tmp_path):
    pr = P.Prefs(scan_ignores=[2**31, 2**32 + 7], bookmarks=[{"name": "x", "freq_hz": 2**33 + 1, "mode": "AM"}])
    P.save(pr, tmp_path / "p.json")
    back = P.load(tmp_path / "p.json")
    assert back.scan_ignores == [2**31, 2**32 + 7] and back.bookmarks[0]["freq_hz"] == 2**33 + 1


# ---------------------------------------------------------------- scanner / ignores
def test_f15_scanner_inputs_strict():
    with pytest.raises(ValueError):
        ScanConfig(start_hz=144e6).channel_list()
    with pytest.raises(ValueError):
        ScanConfig(channels=[146_000_000, 146.5e6]).channel_list()
    with pytest.raises(ValueError):
        ScanConfig(channels=[True]).channel_list()
    ch = ScanConfig(channels=[np.int64(146_000_000), 2**32]).channel_list(RTL_BLOG_V4)
    assert ch == [146_000_000] and all(type(c) is int for c in ch)      # 2**32 outside this receiver: filtered
    il = IgnoreList()
    for v in (146.5e6, True, "146000000", float("nan"), -1):
        with pytest.raises(ValueError):
            il.add(v)
    with pytest.raises(ValueError):
        il.add(146_000_000, tolerance_hz=2.5)
    il.add(2**32 + 5)
    assert il.match(2**32 + 5) and not il.match(2**32 + 6) and not il.match(5)        # no wrap-around at 2**32
    with pytest.raises(ValueError):
        IgnoreList([True])


# ---------------------------------------------------------------- Qt signals and UI
@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    from task_sdr import backends as B
    from task_sdr.backends.simulated import SimulatedBackend
    from task_sdr.ui.main_window import MainWindow
    sysd = tmp_path / "sys"
    sysd.mkdir()
    fx = Path(__file__).parent / "fixtures" / "overlays"
    for f in ("example-ranges.json", "example-markers.json"):
        shutil.copy(fx / f, sysd)
    usr = tmp_path / "data" / "task-sdr" / "overlays"
    opts = {"dirs": [("system", sysd), ("user", usr)], "toggles_path": tmp_path / "cfg" / "ov.json", "user_dir": usr}
    e = Engine(P.Prefs(), lambda: None, status_dir=str(tmp_path / "s"), claim_dir=str(tmp_path / "c"))
    w = MainWindow(e, None, tmp_path / "p.json", backends=[SimulatedBackend(), *[b for b in B.registry() if b.stub]],
                   overlay_opts=opts)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: bool(not w.overlays.loading and w.overlays.set.datasets), timeout=10000)
    yield w, e, tmp_path
    w.close()


@pytest.mark.filterwarnings("error")
def test_f16_signals_carry_64bit_exactly(window):
    w, e, _ = window
    got = []
    for sig in (w.tuner.changed, w.view.tuneRequested, w.scan.tuneRequested, w.overlays.tuneRequested):
        sig.connect(got.append)
        for v in BIG:
            sig.emit(v)
    # every value arrived exactly (connections also reach MainWindow.tune, which rejects them by range)
    assert [v for v in got if v in BIG] == BIG * 4 and all(type(v) is int for v in got)
    assert e.prefs.freq_hz == P.Prefs().freq_hz


def test_f17_main_window_tune_rejects_bad_values(window):
    w, e, _ = window
    start = e.prefs.freq_hz
    for v in BIG + JUNK + [-1]:
        assert w.tune(v) is False and e.prefs.freq_hz == start
    assert w.tune(np.int64(146_520_000)) is True and e.prefs.freq_hz == 146_520_000 and w.tuner.hz == 146_520_000


def test_f18_spectrum_x_hz_precision_at_ghz(window):
    w, _, _ = window
    v = w.view
    v.resize(1000, 400)
    v.center_hz, v.rate = 1_766_000_000, 2_400_000
    assert v.x_to_hz(500) == 1_766_000_000 and type(v.x_to_hz(500)) is int
    assert v.x_to_hz(0) == 1_764_800_000 and v.x_to_hz(1000) == 1_767_200_000
    v.center_hz = 5_999_000_000                                     # beyond 2**32: still exact
    assert v.x_to_hz(500) == 5_999_000_000 and abs(v.hz_to_x(5_999_000_000) - 500) < 1e-6


def test_f19_tuner_widget_set_hz_junk(window):
    w, _, _ = window
    before = w.tuner.hz
    for v in JUNK + BIG:
        assert w.tuner.set_hz(v) is False and w.tuner.hz == before


# ---------------------------------------------------------------- overlays: off, receive-only, isolated
def test_f20_overlays_off_by_default_and_isolated(window):
    w, e, tmp = window
    pr = e.prefs
    snap = lambda: json.dumps({k: getattr(pr, k) for k in ("bookmarks", "presets", "scan_ignores",
                                                           "scan_ignore_entries", "scan_start_hz", "scan_stop_hz",
                                                           "scan_step_hz", "scan_mode")}, sort_keys=True)
    before = snap()
    ign_before = [(x.freq_hz, x.tolerance_hz) for x in w.scan.scanner.ignores.entries.values()]
    assert all(not w.overlays.set.enabled(i) for i in w.overlays.set.datasets) and w.view.overlay_items == []
    w.overlays.set_enabled("example-markers", True)
    w.overlays.set_enabled("example-ranges", True)
    w.overlays.confirm = lambda t: True
    d = w.overlays.set.datasets["example-markers"]
    w.overlays.offer_tune(d, d.items[1])
    assert e.prefs.freq_hz == 146_025_000
    w.overlays.ask_text = lambda *a, **k: "note"
    w.overlays.annotate_current()
    assert snap() == before
    assert [(x.freq_hz, x.tolerance_hz) for x in w.scan.scanner.ignores.entries.values()] == ign_before
    assert w.scan.scanner.state == "idle" and e.scanner is None                # nothing started the scanner
    saved = json.loads((tmp / "p.json").read_text())
    assert not any("overlay" in k for k in saved) and saved["bookmarks"] == pr.bookmarks
    assert not hasattr(w.overlays, "scan") and not hasattr(w.overlays, "engine")   # no handle to scanner/engine


def test_f21_overlay_marker_beyond_receiver_rejected(window):
    import warnings
    w, e, _ = window
    from task_sdr import overlays as O
    doc = json.loads((Path(__file__).parent / "fixtures" / "overlays" / "example-markers.json").read_text())
    doc["items"] = [{"kind": "marker", "label": "EXAMPLE far", "freq_hz": 4_294_967_297}]
    d = O.parse_dataset(doc)
    assert d.items[0].freq_hz == 4_294_967_297
    w.overlays.confirm = lambda t: True
    start = e.prefs.freq_hz
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        w.overlays.offer_tune(d, d.items[0])
    assert e.prefs.freq_hz == start


def test_f22_no_32bit_frequency_signals_in_source():
    import re
    src = Path(__file__).resolve().parents[1] / "task_sdr"
    for p in src.rglob("*.py"):
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"(tune|changed|freq|hz)\w*\s*=\s*Signal\((int|float)", line, re.I):
                pytest.fail(f"{p.name}:{n}: frequency signal must be Signal(object): {line.strip()}")
