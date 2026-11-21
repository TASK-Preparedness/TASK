# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SDR Studio M1 (task-sdr 0.2.0): backends, safe discovery, ranges, digit tuner, DSP, bounded queues, UI.
All with synthetic IQ / a fake librtlsdr — no hardware."""

import ctypes
import inspect
import os
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from task_sdr import backends as B  # noqa: E402
from task_sdr import prefs as P  # noqa: E402
from task_sdr.backends import rtlsdr as R  # noqa: E402
from task_sdr.backends.simulated import SimulatedBackend  # noqa: E402
from task_sdr.device import DeviceBusy, DeviceError, FakeDevice  # noqa: E402
from task_sdr.dsp import AUDIO_RATE, Agc, Demodulator, channel_power_dbfs, s_meter  # noqa: E402
from task_sdr.engine import AUDIO_QUEUE, FRAME_QUEUE, Engine  # noqa: E402
from task_sdr.tuner import DigitTuner, format_hz, parse  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "task_sdr"


# ------------------------------------------------------------------ fake librtlsdr
class Fn:
    def __init__(self, f):
        self.f = f

    def __call__(self, *a):
        return self.f(*a)


class FakeLib:
    def __init__(self, devices=(("RTLSDRBlog", "Blog V4", "00000001"),), open_rc=0):
        self.devices, self.open_rc = list(devices), open_rc
        self.calls = []
        self.freq = None
        lib = self

        def rec(name, fn):
            def w(*a):
                lib.calls.append(name)
                return fn(*a)
            return Fn(w)
        self.rtlsdr_get_device_count = rec("count", lambda: len(self.devices))
        self.rtlsdr_get_device_name = rec("name", lambda i: b"Generic RTL2832U OEM")

        def strings(i, m, p, s):
            m.value, p.value, s.value = (x.encode() for x in self.devices[i])
            return 0
        self.rtlsdr_get_device_usb_strings = rec("usb_strings", strings)

        def op(ref, i):
            if self.open_rc:
                return self.open_rc
            ref._obj.value = 4242
            return 0
        self.rtlsdr_open = rec("open", op)
        self.rtlsdr_close = rec("close", lambda h: 0)
        self.rtlsdr_set_center_freq = rec("tune", lambda h, f: setattr(self, "freq", f) or 0)
        self.rtlsdr_get_center_freq = rec("get_freq", lambda h: self.freq or 0)
        self.rtlsdr_set_freq_correction = rec("ppm", lambda h, p: 0)
        self.rtlsdr_get_tuner_type = rec("tuner", lambda h: 6)

        def gains(h, arr):
            g = [0, 9, 14, 27, 37, 77, 87, 125, 144, 157, 166, 197, 207, 229, 254, 280, 297, 328, 338, 364, 372,
                 386, 402, 421, 434, 439, 445, 480, 496]
            if arr:
                for i, x in enumerate(g):
                    arr[i] = x
            return len(g)
        self.rtlsdr_get_tuner_gains = rec("gains", gains)
        self.rtlsdr_set_tuner_gain = rec("gain", lambda h, g: setattr(self, "gain", g) or 0)
        self.rtlsdr_set_tuner_gain_mode = rec("gain_mode", lambda h, m: 0)
        self.rtlsdr_set_sample_rate = rec("rate", lambda h, r: 0)
        self.rtlsdr_set_agc_mode = rec("agc", lambda h, on: 0)
        self.rtlsdr_reset_buffer = rec("reset", lambda h: 0)

        def read(h, buf, n, got):
            arr = (ctypes.c_uint8 * n).from_address(ctypes.addressof(buf))
            arr[0:4] = [255, 128, 0, 128]
            got._obj.value = n
            return 0
        self.rtlsdr_read_sync = rec("read", read)


def rtl(lib):
    return R.RtlSdrBackend(loader=lambda path: lib)


# ------------------------------------------------------------------ backends / discovery / ranges
def test_s01_v4_detected_with_verified_range():
    lib = FakeLib()
    devs = rtl(lib).enumerate()
    assert devs[0].profile is B.RTL_BLOG_V4 and devs[0].serial == "00000001"
    p = B.RTL_BLOG_V4
    assert (p.min_hz, p.max_hz) == (500_000, 1_766_000_000)
    for bad in (2_400_000_000, 5_800_000_000, 1_766_000_001, 499_999):
        assert not p.accepts(bad)
        with pytest.raises(B.RangeError):
            p.check(bad)
    assert p.accepts(7_074_000) and p.accepts(1_090_000_000)
    assert R.profile_for("Realtek", "RTL2838UHIDIR") is B.RTL_GENERIC and not B.RTL_GENERIC.accepts(7_074_000)


def test_s02_safe_discovery_never_opens_and_reports_stubs():
    lib = FakeLib()
    res = B.discover([rtl(lib), SimulatedBackend()] + [b for b in B.registry() if b.stub])
    assert "open" not in lib.calls and "tune" not in lib.calls
    stubs = [(b.key, ok, why) for b, ok, why, _ in res if b.stub]
    assert {k for k, _, _ in stubs} == {"airspy", "sdrplay", "hackrf", "lime", "pluto", "uhd", "network"}
    assert all(not ok and "STUB" in why for _, ok, why in stubs)
    for b, *_ in res:
        if b.stub:
            with pytest.raises(NotImplementedError):
                b.open(None)


def test_s03_missing_librtlsdr_and_soapy_are_not_fatal():
    def nolib(path):
        raise OSError("not found")
    b = R.RtlSdrBackend(loader=nolib)
    ok, why = b.available()
    assert not ok and "librtlsdr0" in why
    res = B.discover([b, B.registry()[1]])
    assert all(isinstance(r[2], str) for r in res)


def test_s04_rtlsdr_open_configure_read_and_errors():
    lib = FakeLib()
    be = rtl(lib)
    info = be.enumerate()[0]
    d = be.open(info)
    d.configure(1_024_000, 162_550_000, 30.0, ppm=2)
    assert lib.freq == 162_550_000 and lib.gain == 297      # nearest real gain step (29.7 dB)
    iq = d.read(65_536)
    assert iq.dtype == np.complex64 and len(iq) == 65_536 and abs(iq[0].real - 1.0) < 0.01
    with pytest.raises(B.RangeError):
        d.set_frequency(2_400_000_000)
    assert lib.freq == 162_550_000
    d.close()
    with pytest.raises(DeviceBusy):
        rtl(FakeLib(open_rc=-6)).open(info)
    with pytest.raises(DeviceError, match="permission"):
        rtl(FakeLib(open_rc=-3)).open(info)


def test_s05_no_transmit_or_bias_tee_paths():
    code = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    assert "rtlsdr_set_bias_tee" not in R.ALLOWED_SYMBOLS and "set_bias_tee(" not in code
    assert "SOAPY_SDR_TX" not in code and "writeStream" not in code
    for cls in (R.RtlSdrDevice, FakeDevice, B.Backend):
        names = [n.lower() for n, _ in inspect.getmembers(cls)]
        assert not any("transmit" in n or n.startswith("tx") or "write" == n for n in names)


# ------------------------------------------------------------------ digit tuner
def test_s06_format_and_carry_borrow():
    t = DigitTuner(144_390_000, B.RTL_BLOG_V4.accepts)
    assert t.text == "00.144.390.000" and format_hz(1_766_000_000) == "01.766.000.000"
    assert t.step(4, +1) and t.text == "00.144.400.000"           # 10 kHz digit 9 -> carry
    assert t.step(0, -1) and t.text == "00.144.399.999"           # borrow through all lower digits
    assert t.step(6, +1) and t.hz == 145_399_999


def test_s07_range_rejection_never_clamps():
    t = DigitTuner(1_700_000_000, B.RTL_BLOG_V4.accepts, lambda hz: "outside V4")
    assert not t.step(8, +1) and t.hz == 1_700_000_000 and t.last_rejection == "outside V4"   # +100 MHz
    assert not t.enter("2.4G") and not t.enter("5.8 GHz") and t.hz == 1_700_000_000
    t2 = DigitTuner(550_000, B.RTL_BLOG_V4.accepts)
    assert not t2.step(5, -1) and t2.hz == 550_000                # 450 kHz < 500 kHz floor
    assert DigitTuner(600_000, B.RTL_BLOG_V4.accepts).step(5, -1)  # 500 kHz edge is inside


def test_s08_parse_and_keyboard_entry():
    assert parse("146.52M") == parse("146.52") == parse("00.146.520.000") == 146_520_000
    assert parse("1.2g") == 1_200_000_000 and parse("7074k") == 7_074_000 and parse("162550000") == 162_550_000
    for bad in ("abc", "1.2.3M", "-5"):
        with pytest.raises(ValueError):
            parse(bad)
    t = DigitTuner(100_000_000, B.RTL_BLOG_V4.accepts)
    t.cursor = 8
    for d in (1, 4, 6):
        assert t.type_digit(d)
    assert t.hz == 146_000_000 and t.cursor == 5
    t.move_cursor(-1)
    assert t.cursor == 6


def test_s09_tuner_widget_mouse_wheel_keys(qtbot):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from task_sdr.ui.widgets import TunerWidget
    w = TunerWidget(144_390_000, B.RTL_BLOG_V4.accepts, lambda hz: "outside")
    qtbot.addWidget(w)
    w.resize(600, 70)
    w.show()
    w.grab()
    seen = []
    w.changed.connect(seen.append)
    r = w._rects[11 - 1 - 3]                                   # 1 kHz digit
    qtbot.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.top() + 5)))
    assert w.hz == 144_391_000
    qtbot.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.bottom() - 5)))
    qtbot.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.bottom() - 5)))
    assert w.hz == 144_389_000 and seen[-1] == 144_389_000
    qtbot.keyClick(w, Qt.Key.Key_Up)
    assert w.hz == 144_390_000
    rej = []
    w.rejected.connect(rej.append)
    assert not w.prompt("2.4G") and rej == ["outside"] and w.hz == 144_390_000
    from PySide6.QtGui import QWheelEvent
    ev = QWheelEvent(QPointF(r.center()), QPointF(r.center()), QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)
    assert w.hz == 144_391_000


# ------------------------------------------------------------------ DSP
def _iq(sig, rate=1_024_000, n=262_144):
    d = FakeDevice([sig], noise=1e-4)
    d.configure(rate, 100e6)
    return d.read(n)


def _peak(a):
    f = np.fft.rfftfreq(len(a), 1 / AUDIO_RATE)
    return f[np.argmax(np.abs(np.fft.rfft(a * np.hanning(len(a)))))]


def test_s10_cw_and_bandwidth():
    iq = _iq((0, "tone", {"amp": 0.5}))
    a = Demodulator("CW", 1_024_000).process(iq)[4800:]
    assert abs(_peak(a) - 700) < 40                           # carrier at the dial -> 700 Hz pitch
    d = Demodulator("NFM", 1_024_000, bandwidth=8_000)
    assert d.bandwidth == 8_000 and Demodulator("NFM", 1_024_000, bandwidth=10**6).bandwidth == 25_000
    assert Demodulator("USB", 1_024_000).bandwidth == 2_800


def test_s11_agc_and_smeter():
    agc = Agc()
    quiet = (0.01 * np.sin(np.arange(4800) / 7)).astype(np.float32)
    for _ in range(80):
        out = agc(quiet)
    assert np.max(np.abs(out)) > 0.15
    assert s_meter(-30.0)[0] == "S9" and s_meter(-18.0)[0] == "S9+12" and s_meter(-84.0)[0] == "S0"
    spec = np.full(1024, -100.0)
    spec[512] = -20.0
    assert channel_power_dbfs(spec, 1000, 0, 5000) > -21 and channel_power_dbfs(spec, 1000, 100_000, 5000) < -80


# ------------------------------------------------------------------ engine: bounded queues, range
def test_s12_bounded_queues_drop_oldest(tmp_path):
    e = Engine(P.Prefs(), lambda: FakeDevice([(0, "fm", {"dev": 5000, "af": 600})]),
               status_dir=tmp_path / "s", claim_dir=tmp_path / "l")
    e.start()
    end = time.time() + 10
    while e.dropped_audio == 0 and time.time() < end:
        time.sleep(0.05)
    e.stop()
    assert e.audio_q.qsize() <= AUDIO_QUEUE and len(e.frames) <= FRAME_QUEUE and e.dropped_audio > 0
    f = e.take_frame()
    assert f is not None and len(e.frames) == 0 and len(f["spectrum"]) == 1024


def test_s13_engine_rejects_out_of_range_and_bad_saved_freq(tmp_path):
    e = Engine(P.Prefs(), lambda: FakeDevice(), status_dir=tmp_path / "s", claim_dir=tmp_path / "l")
    e.profile = B.RTL_BLOG_V4
    with pytest.raises(B.RangeError):
        e.retune(freq_hz=2_400_000_000)
    assert e.prefs.freq_hz == 162_550_000
    p = P.Prefs(freq_hz=10_000_000)

    def opener():
        d = FakeDevice()
        d.profile = B.RTL_GENERIC
        return d
    e2 = Engine(p, opener, status_dir=tmp_path / "s2", claim_dir=tmp_path / "l2")
    e2.start()
    assert e2.wait_state("error", 3) and "outside" in e2.error
    e2.stop()


# ------------------------------------------------------------------ UI
class Sink:
    def __init__(self):
        self.n = 0

    def write(self, a):
        self.n += len(a)

    def close(self):
        pass


@pytest.fixture
def studio(qtbot, tmp_path):
    from task_sdr.ui.main_window import MainWindow
    e = Engine(P.Prefs(), lambda: None, status_dir=tmp_path / "s", claim_dir=tmp_path / "l")
    sink = Sink()
    w = MainWindow(e, sink, tmp_path / "prefs.json", backends=[SimulatedBackend(), *[b for b in B.registry() if b.stub]])
    qtbot.addWidget(w)
    w.resize(1280, 760)
    w.show()
    yield w, e, sink
    w.close()


def test_s14_studio_runs_spectrum_waterfall_audio_smeter(qtbot, studio):
    w, e, sink = studio
    assert "SIMULATED" in w.device_box.currentText() and "[STUB]" in " ".join(
        w.backend_box.itemText(i) for i in range(w.backend_box.count()))
    w.start_btn.click()
    qtbot.waitUntil(lambda: sink.n > AUDIO_RATE // 4 and w.view.frames > 3, timeout=8000)
    assert "connected" in w.state.text() and w.smeter.dbfs is not None
    img = w.grab()
    assert not img.isNull()
    w.start_btn.click()
    assert e.state == "stopped"


def test_s15_gui_stays_responsive(qtbot, studio):
    w, e, sink = studio
    w.start_btn.click()
    qtbot.waitUntil(lambda: w.view.frames > 2, timeout=8000)
    worst = 0.0
    for _ in range(30):
        t0 = time.perf_counter()
        w._tick()
        w.view.repaint()
        worst = max(worst, time.perf_counter() - t0)
        qtbot.wait(10)
    w.start_btn.click()
    assert worst < 0.25, f"GUI tick took {worst * 1000:.0f} ms"


def test_s16_click_to_tune_modes_bookmarks_persist_and_reject(qtbot, studio, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    w, e, _ = studio
    w.view.rate, w.view.center_hz = 1_024_000, 162_550_000
    qtbot.mouseClick(w.view, Qt.MouseButton.LeftButton, pos=QPoint(w.view.width() * 3 // 4, 100))
    assert abs(e.prefs.freq_hz - (162_550_000 + 256_000)) < 3_000 and w.tuner.hz == e.prefs.freq_hz
    for m in ("AM", "USB", "LSB", "CW", "WFM", "NFM"):
        w.mode_btns[m].click()
        assert e.prefs.mode == m and w.bw.value() == {"WFM": 200_000, "NFM": 12_500, "AM": 10_000, "USB": 2_800,
                                                      "LSB": 2_800, "CW": 500}[m]
    w.add_bookmark("Test BM")
    saved = P.load(tmp_path / "prefs.json")
    assert saved.bookmarks[-1]["name"] == "Test BM" and saved.mode == "NFM"
    e.profile = B.RTL_BLOG_V4
    assert not w.tune(2_400_000_000) and "Rejected" in w.message.text() and e.prefs.freq_hz != 2_400_000_000
    assert w.use_entry(0, "presets") and e.prefs.freq_hz == P.DEFAULT_PRESETS[0]["freq_hz"]
