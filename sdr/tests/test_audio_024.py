# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""0.2.4 audio-pipeline repair: WFM path, AGC, resampler continuity, AudioRing (partial writes, under/overruns),
reader/DSP threads, disconnect, start/stop/restart, scan -> receive recovery, diagnostics. Synthetic IQ only."""
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_sdr import prefs as P  # noqa: E402
from task_sdr.audioring import AudioRing  # noqa: E402
from task_sdr.backends import RTL_BLOG_V4  # noqa: E402
from task_sdr.device import DeviceError, FakeDevice  # noqa: E402
from task_sdr.dsp import AUDIO_RATE, Agc, Demodulator, audio_levels  # noqa: E402
from task_sdr.engine import BLOCK, Engine  # noqa: E402
from task_sdr.scanner import ScanConfig, Scanner  # noqa: E402

FS = 1_024_000
SRC = Path(__file__).resolve().parents[1] / "task_sdr"


def wfm_iq(n, dev=75_000.0, tone=1000.0, t0=0, noise=0.0, seed=0, amp=1.0):
    t = (np.arange(n) + t0) / FS
    x = amp * np.exp(1j * (dev / tone) * np.sin(2 * np.pi * tone * t))
    if noise:
        r = np.random.default_rng(seed)
        x = x + noise * (r.standard_normal(n) + 1j * r.standard_normal(n))
    return x.astype(np.complex64)


def tone_freq(a, rate=AUDIO_RATE):
    w = np.hanning(len(a))
    sp = np.abs(np.fft.rfft(a * w))
    k = int(np.argmax(sp[1:])) + 1
    return k * rate / len(a)


def eng(tmp_path, dev_factory, **kw):
    pr = P.Prefs()
    pr.freq_hz, pr.mode, pr.volume, pr.agc = 95_500_000, "WFM", 1.0, kw.pop("agc", True)
    return Engine(pr, dev_factory, status_dir=tmp_path / "s", claim_dir=tmp_path / "c", **kw)


# ------------------------------------------------------------------ WFM demod
@pytest.mark.parametrize("dev,expect", [(75_000, 1.0), (37_500, 0.5), (15_000, 0.2)])
def test_a01_wfm_discriminator_scaled_to_75k(dev, expect):
    d = Demodulator("WFM", FS, deemphasis_us=0)
    a = np.concatenate([d.process(wfm_iq(BLOCK, dev=dev, t0=k * BLOCK)) for k in range(8)])[AUDIO_RATE // 4:]
    peak = np.max(np.abs(a))
    assert abs(peak - expect) / expect < 0.05, peak
    assert abs(tone_freq(a) - 1000) < 15
    assert abs(float(np.mean(a))) < 0.01                       # no DC


def test_a02_deemphasis_75us_response():
    lv = {}
    for f in (1000.0, 10_000.0):
        d = Demodulator("WFM", FS)
        a = np.concatenate([d.process(wfm_iq(BLOCK, dev=20_000, tone=f, t0=k * BLOCK)) for k in range(8)])[12000:]
        lv[f] = audio_levels(a)[0]
    rel = 20 * np.log10(lv[10_000.0] / lv[1000.0])
    tau = 75e-6
    exp = -10 * np.log10(1 + (2 * np.pi * 10_000 * tau) ** 2) + 10 * np.log10(1 + (2 * np.pi * 1000 * tau) ** 2)
    assert abs(rel - exp) < 1.5, (rel, exp)


def test_a03_audio_lpf_rejects_19k_pilot():
    d = Demodulator("WFM", FS, deemphasis_us=0)
    a = np.concatenate([d.process(wfm_iq(BLOCK, dev=7_500, tone=19_000, t0=k * BLOCK)) for k in range(6)])[8000:]
    assert audio_levels(a)[0] < 0.1 * 7_500 / 75_000 * 0.7071   # >20 dB down vs. an in-band tone


def test_a04_wfm_output_never_clipped_in_demod():
    d = Demodulator("WFM", FS)
    a = np.concatenate([d.process(wfm_iq(BLOCK, dev=75_000, t0=k * BLOCK, noise=0.05, seed=k)) for k in range(6)])
    assert np.max(np.abs(a)) < 1.0


# ------------------------------------------------------------------ continuity
@pytest.mark.parametrize("mode", ["WFM", "NFM", "USB", "LSB", "CW"])
def test_a05_block_size_invariant_randomized(mode):
    n = FS // 2
    iq = wfm_iq(n, dev=75_000 if mode == "WFM" else 3_000, noise=0.01)
    ref = Demodulator(mode, FS).process(iq)
    for seed in (1, 2, 3):
        r = np.random.default_rng(seed)
        d, outs, i = Demodulator(mode, FS), [], 0
        while i < n:
            k = int(r.integers(1, 30_000))
            outs.append(d.process(iq[i:i + k]))
            i += k
        o = np.concatenate(outs)
        assert abs(len(o) - len(ref)) <= 1
        m = min(len(o), len(ref))
        assert np.max(np.abs(o[:m] - ref[:m])) < 1e-4, (mode, seed)


def test_a06_resampler_rate_exact_and_no_drift():
    d = Demodulator("WFM", FS)
    total = sum(len(d.process(wfm_iq(BLOCK, t0=k * BLOCK))) for k in range(160))   # 10.24 s
    assert abs(total - 160 * BLOCK * AUDIO_RATE / FS) <= 1


def test_a07_no_clicks_at_block_boundaries():
    d = Demodulator("WFM", FS)
    a = np.concatenate([d.process(wfm_iq(int(k), dev=30_000, t0=s)) for s, k in
                        zip(np.cumsum([0] + [7_777] * 80)[:-1], [7_777] * 80)])[4000:]
    jump = np.max(np.abs(np.diff(a)))
    smooth = 2 * np.pi * 1000 / AUDIO_RATE * 0.4 * 1.2                     # max slope of a 0.4-amplitude 1 kHz sine
    assert jump < smooth


# ------------------------------------------------------------------ AGC
def test_a08_agc_levels_and_no_clipping():
    for amp in (0.01, 0.1, 0.9):
        agc = Agc()
        x = (amp * np.sin(2 * np.pi * 1000 * np.arange(3072 * 120) / AUDIO_RATE)).astype(np.float32)
        out = np.concatenate([agc(x[i:i + 3072]) for i in range(0, len(x), 3072)])
        tail = out[-AUDIO_RATE:]
        rms = audio_levels(tail)[0]
        assert np.max(np.abs(out)) <= 0.95 + 1e-6
        if amp >= 0.01:
            assert 0.15 < rms < 0.35, (amp, rms)


def test_a09_agc_gain_ramps_smoothly_and_releases_slowly():
    agc = Agc()
    loud = (0.8 * np.sin(np.arange(3072) / 5)).astype(np.float32)
    quiet = (0.05 * np.sin(np.arange(3072) / 5)).astype(np.float32)
    for _ in range(20):
        agc(loud)
    g0 = agc.gain
    agc(quiet)
    assert agc.gain < g0 * 1.2                          # release ~1.5 s: one 64 ms block barely moves it
    out = agc(loud * 1.0)
    assert np.max(np.abs(out)) <= 0.95 + 1e-6           # limiter holds on a sudden loud block


def test_a10_agc_attack_fast():
    agc = Agc()
    q = (0.01 * np.sin(np.arange(3072) / 5)).astype(np.float32)
    for _ in range(100):
        agc(q)
    hi = agc.gain
    out = agc((0.9 * np.sin(np.arange(3072) / 5)).astype(np.float32))
    assert agc.gain < hi / 5 and np.max(np.abs(out)) <= 0.95 + 1e-6


# ------------------------------------------------------------------ AudioRing
def test_a11_ring_order_and_wrap():
    r = AudioRing(target_ms=10, max_ms=1000)
    x = np.arange(20_000, dtype=np.float32)
    got = []
    for i in range(0, len(x), 1234):
        r.push(x[i:i + 1234])
        got.append(r.pull(900, pad=False))
    got.append(r.pull(r.level(), pad=False))
    assert np.array_equal(np.concatenate(got), x)
    assert r.overrun_events == 0 and r.generated == r.accepted == len(x)


def test_a12_ring_overrun_drops_oldest_and_counts():
    r = AudioRing(target_ms=10, max_ms=100)              # cap 4800
    x = np.arange(10_000, dtype=np.float32)
    r.push(x)
    assert r.level() == 4800 and r.overrun_samples == 5200 and r.overrun_events == 1
    assert np.array_equal(r.pull(4800, pad=False), x[-4800:])


def test_a13_ring_underrun_pads_counts_and_reprimes():
    r = AudioRing(target_ms=20, max_ms=200)              # target 960
    out = r.pull(480)                                    # before first prime: start-up fill, not an underrun
    assert len(out) == 480 and not out.any() and r.underrun_events == 0 and r.startup_samples == 480
    r.push(np.ones(1000, np.float32))
    assert r.pull(480).all()
    out = r.pull(1000)
    assert out[:520].all() and not out[520:].any()
    assert r.underrun_events == 1 and r.underrun_samples == 480
    r.push(np.ones(500, np.float32))                     # below target: still re-priming
    assert not r.pull(100).any() and r.underrun_events == 1
    r.push(np.ones(500, np.float32))
    assert r.pull(100).all()


class FakePushSink:
    """Models QAudioSink push mode: bounded buffer, write() may accept less than offered."""

    def __init__(self, cap_bytes):
        self.cap, self.level, self.data = cap_bytes, 0, bytearray()

    def bytesFree(self):
        return self.cap - self.level

    def write(self, b):
        n = min(len(b), self.cap - self.level)
        n -= n % 4
        n = min(n, 1000)                                 # also short writes even when there is room
        self.data += b[:n]
        self.level += n
        return n

    def drain(self, nbytes):
        self.level = max(0, self.level - nbytes)


def test_a14_push_mode_partial_writes_lose_nothing():
    from task_sdr.audio import QtAudioOut
    out = QtAudioOut.__new__(QtAudioOut)                 # exercise _pump without a real audio device
    out.ring = AudioRing(target_ms=10, max_ms=2000)
    sink = FakePushSink(4096)
    out.sink, out.io = sink, sink
    out.partial_writes = out.bytes_written = 0
    x = np.arange(48_000, dtype=np.float32)
    for i in range(0, len(x), 3072):
        out.ring.push(x[i:i + 3072])
        for _ in range(8):
            out._pump()
            sink.drain(1600)
    for _ in range(400):
        out._pump()
        sink.drain(4096)
    got = np.frombuffer(bytes(sink.data), np.float32)
    assert np.array_equal(got, x)                         # every sample, in order, none dropped or duplicated
    assert out.partial_writes > 0 and out.ring.overrun_events == 0


def test_a15_pull_source_qiodevice_reads_ring(qtbot):
    from task_sdr.audio import make_pull_source
    r = AudioRing(target_ms=10, max_ms=200)
    src = make_pull_source(r)
    r.push(np.full(960, 0.5, np.float32))
    b = src.read(4 * 480)
    a = np.frombuffer(bytes(b), np.float32)
    assert len(a) == 480 and np.allclose(a, 0.5)
    b = src.read(4 * 960)                                 # 480 real + 480 counted silence
    a = np.frombuffer(bytes(b), np.float32)
    assert len(a) == 960 and np.allclose(a[:480], 0.5) and not a[480:].any() and r.underrun_events == 1
    src.close()


# ------------------------------------------------------------------ engine threads
def test_a16_engine_realtime_no_iq_loss_and_continuous_audio(tmp_path):
    d = FakeDevice([(0, "fm", {"dev": 75_000, "af": 1000, "amp": 1.0})], pace=True)
    e = eng(tmp_path, lambda: d, agc=False)
    e.start()
    t0 = time.monotonic()
    pulled = []
    while time.monotonic() - t0 < 3.0:                   # a 10 ms pull-mode consumer
        time.sleep(0.01)
        pulled.append(e.ring.pull(480))
    diag = e.diagnostics()
    e.stop()
    a = np.concatenate(pulled)
    st = e.ring.stats()
    assert diag["iq_dropped_blocks"] == 0 and diag["read_errors"] == 0
    assert diag["iq_rate_ratio"] is not None and 0.9 < diag["iq_rate_ratio"] < 1.1
    assert st["overrun_events"] == 0
    assert st["underrun_samples"] < 0.05 * len(a), st      # sleep-paced consumer jitter only
    live = a[np.abs(a) > 0]
    assert audio_levels(live)[0] > 0.5                     # loud: full deviation tone ~0.7 RMS, no AGC
    assert diag["dsp_blocks"] > 0 and diag["dsp_over_budget"] == 0


def test_a17_stale_blocks_after_retune_are_never_demodulated(tmp_path):
    e = eng(tmp_path, lambda: FakeDevice())
    e.demod = e._demod()
    g = e.gen
    e.retune(freq_hz=96_100_000)
    e.handle_block(wfm_iq(BLOCK), gen=g, scanning=False)
    assert e.stats.stale_blocks == 1 and e.ring.generated == 0
    e.handle_block(wfm_iq(BLOCK), gen=e.gen, scanning=False)
    assert e.ring.generated > 0


def test_a18_disconnect_and_reconnect(tmp_path):
    devs = []

    def opener():
        devs.append(FakeDevice([(0, "fm", {"dev": 50_000, "af": 800})], unplug_after=None if devs else 30))
        return devs[-1]
    e = eng(tmp_path, opener)
    e.start()
    try:
        end = time.time() + 15
        while (len(devs) < 2 or e.state != "connected") and time.time() < end:
            time.sleep(0.05)
        g = e.ring.generated
        time.sleep(0.5)
        d = e.diagnostics()
        assert e.ring.generated > g                       # audio flows again on the reopened device
    finally:
        e.stop()
    assert len(devs) >= 2 and devs[0].closed and d["read_errors"] >= 1 and e.state == "stopped"


def test_a19_start_stop_restart_threads_clean(tmp_path):
    e = eng(tmp_path, lambda: FakeDevice([(0, "fm", {"dev": 50_000, "af": 800})], pace=True))
    for _ in range(3):
        e.start()
        mine = [t for t in (e._thread, e._dsp_thread, e._diag_thread) if t]
        assert e.wait_state("connected", 5)
        time.sleep(0.4)
        assert e.ring.generated > 0
        e.stop()
        assert mine and not any(t.is_alive() for t in mine)
        assert e.ring.level() == 0 and e.dev is None


def test_a20_overrun_counted_when_nobody_consumes(tmp_path):
    e = eng(tmp_path, lambda: FakeDevice([(0, "fm", {"dev": 50_000, "af": 800})]))   # unpaced: faster than RT
    e.start()
    end = time.time() + 10
    while e.ring.overrun_events == 0 and time.time() < end:
        time.sleep(0.05)
    e.stop()
    assert e.dropped_audio > 0 and e.ring.overrun_samples > 0
    assert e.ring.max_level <= e.ring.cap                  # latency bound held


def test_a21_scan_then_receive_audio_recovers(tmp_path):
    d = FakeDevice([(0, "fm", {"dev": 5_000, "af": 700, "amp": 0.5})], pace=True)
    e = eng(tmp_path, lambda: d)
    e.start()
    assert e.wait_state("connected", 5)
    e.profile = RTL_BLOG_V4
    sc = Scanner(FS, RTL_BLOG_V4)
    e.start_scan(sc, ScanConfig())
    time.sleep(1.0)
    e.stop_scan()
    e.retune(freq_hz=95_500_000, mode="WFM", bandwidth=None)
    e.ring.clear()
    g0 = e.ring.generated
    t0 = time.monotonic()
    pulled = []
    while time.monotonic() - t0 < 1.5:
        time.sleep(0.01)
        pulled.append(e.ring.pull(480))
    e.stop()
    assert e.ring.generated - g0 > 0.8 * 1.5 * AUDIO_RATE * 0.8
    a = np.concatenate(pulled)
    assert audio_levels(a[np.abs(a) > 0])[0] > 0.05 and e.prefs.mode == "WFM"


def test_a22_diag_log_json_lines(tmp_path):
    log = tmp_path / "diag.jsonl"
    e = eng(tmp_path, lambda: FakeDevice([(0, "fm", {"dev": 50_000, "af": 800})], pace=True), diag_log=str(log))
    e.start()
    time.sleep(2.3)
    e.stop()
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(rows) >= 2
    for k in ("audio_rms_dbfs", "audio_peak_dbfs", "agc_gain_db", "audio_underrun_events", "audio_overrun_events",
              "audio_queue_ms", "iq_dropped_blocks", "dsp_avg_ms", "dsp_max_ms", "dsp_over_budget",
              "iq_rate_measured", "audio_generated", "audio_accepted", "iq_queue"):
        assert k in rows[-1], k


def test_a23_no_tx_no_shell_in_new_code():
    for f in ("audioring.py", "audio.py", "engine.py", "dsp.py"):
        src = (SRC / f).read_text().lower()
        for bad in ("shell=true", "os.system", "subprocess", "transmit(", "write_sync", "bias_tee", "pactl",
                    "wpctl", "amixer"):
            assert bad not in src, (f, bad)


def test_a24_gui_timer_does_not_touch_audio_when_sink_pulls(qtbot, tmp_path):
    from task_sdr.ui.main_window import MainWindow

    class Out:
        def __init__(self, ring):
            self.ring, self.writes = ring, 0

        def write(self, a):
            self.writes += 1

        def stats(self):
            return {"mode": "pull"}

        def close(self):
            pass
    e = eng(tmp_path, lambda: FakeDevice())
    out = Out(e.ring)
    w = MainWindow(e, out, prefs_path=tmp_path / "p.json", backends=[], load_overlays=False)
    qtbot.addWidget(w)
    e.ring.push(np.ones(9600, np.float32))
    w._tick()
    assert out.writes == 0 and e.ring.level() == 9600 and e.sink_info is out
    w.close()


def test_a25_prefs_from_020_preserved(tmp_path):
    p = tmp_path / "prefs.json"
    old = {"freq_hz": 95_500_000, "mode": "WFM", "volume": 1.0, "agc": True, "bandwidth_hz": 200_000,
           "bookmarks": [{"name": "WXYZ", "freq_hz": 95_500_000, "mode": "WFM", "bandwidth_hz": 200_000}],
           "presets": [{"name": "Air", "freq_hz": 121_500_000, "mode": "AM"}], "s9_dbfs": -30.0}
    p.write_text(json.dumps(old))
    pr = P.load(p)
    assert pr.bookmarks == old["bookmarks"] and pr.presets == old["presets"] and pr.freq_hz == 95_500_000
    P.save(pr, p)
    again = json.loads(p.read_text())
    for k, v in old.items():
        assert again[k] == v


def test_a26_acceptance_analyzer_on_real_engine_log(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import hw_acceptance as H
    log = tmp_path / "d.jsonl"
    e = eng(tmp_path, lambda: FakeDevice([(0, "fm", {"dev": 60_000, "af": 1000, "amp": 1.0})], pace=True),
            diag_log=str(log))
    e.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 4.2:
        time.sleep(0.01)
        e.ring.pull(480)
    e.stop()
    verdict, checks = H.analyze(H.load(log), steady_from=1.0)
    c = {n: (v, ok) for n, v, _, ok in checks}
    assert verdict == "FAIL" and not c["steady duration s"][1]          # 4 s is not the required 5 minutes
    assert c["IQ dropped blocks"] == (0, True) and c["audio overrun events"][1]
    assert c["audio RMS dBFS (median)"][1], c["audio RMS dBFS (median)"]  # AGC puts programme at ~-12 dBFS
    assert c["audio peak dBFS (max)"][1]
    rows = H.load(log)
    long = [dict(r, t=r["t"] + 100 * i) for i, r in enumerate(rows)]      # same rows stretched over > 5 min
    v2, ch2 = H.analyze(long, steady_from=0)
    assert dict((n, ok) for n, _, _, ok in ch2)["steady duration s"]
    assert H.main(["analyze", str(log)]) in (1, 3)
