# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Simulated tests: FakeDevice synthetic IQ; audio sink mocked. No hardware."""

import ast
from pathlib import Path

import numpy as np
import pytest

from task_sdr import prefs as P
from task_sdr.audio import allowed_devices, direwolf_cards
from task_sdr.device import DeviceBusy, FakeDevice, enumerate_devices
from task_sdr.dsp import AUDIO_RATE, Demodulator, Spectrum
from task_sdr.engine import Engine
from task_comms.ownership import DeviceClaim
from task_comms.status import read_status

PKG = Path(__file__).resolve().parents[1] / "task_sdr"
RATE = 1_024_000


def demod_peak(mode, sig, blocks=12):
    d = FakeDevice([sig])
    d.configure(RATE, 100e6)
    dm = Demodulator(mode, RATE)
    a = np.concatenate([dm.process(d.read(65536)) for _ in range(blocks)])[AUDIO_RATE // 4:]
    s = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    f = np.fft.rfftfreq(len(a), 1 / AUDIO_RATE)
    return f[np.argmax(s[10:]) + 10], float(np.std(a))


@pytest.mark.parametrize("mode,sig,tone", [
    ("WFM", (0, "fm", {"dev": 75000, "af": 1000}), 1000),
    ("NFM", (0, "fm", {"dev": 5000, "af": 800}), 800),
    ("AM", (0, "am", {"depth": 0.5, "af": 700}), 700),
    ("USB", (1000, "tone", {}), 1000),
    ("LSB", (-1000, "tone", {}), 1000)])
def test_demodulators_recover_tone(mode, sig, tone):
    f, level = demod_peak(mode, sig)
    assert abs(f - tone) < 5 and level > 0.1


def test_ssb_sideband_rejection():
    _, wanted = demod_peak("USB", (1000, "tone", {}))
    _, unwanted = demod_peak("LSB", (1000, "tone", {}))
    assert unwanted < wanted / 100


def test_audio_rate_is_48k():
    d = FakeDevice()
    d.configure(RATE, 1e8)
    dm = Demodulator("NFM", RATE)
    n = sum(len(dm.process(d.read(65536))) for _ in range(16))
    assert abs(n - 16 * 65536 * AUDIO_RATE / RATE) < 4


def test_spectrum_peak_and_waterfall():
    d = FakeDevice([(128_000, "tone", {})])
    d.configure(RATE, 1e8)
    sp = Spectrum(1024, rows=8)
    for _ in range(10):
        db = sp.compute(d.read(4096))
    peak_bin = int(np.argmax(db))
    assert abs((peak_bin - 512) * RATE / 1024 - 128_000) <= RATE / 1024
    wf = sp.ordered_waterfall()
    assert wf.shape == (8, 1024) and np.argmax(wf[0]) == peak_bin


class Sink:
    def __init__(self):
        self.blocks = []

    def write(self, a):
        self.blocks.append(a)


def make_engine(tmp_path, opener, **kw):
    pr = P.Prefs(**kw)
    return Engine(pr, opener, audio=Sink(), status_dir=tmp_path / "st", claim_dir=tmp_path / "locks")


def test_engine_runs_and_releases(tmp_path):
    devs = []

    def opener():
        devs.append(FakeDevice([(0, "fm", {"dev": 5000, "af": 600})]))
        return devs[-1]
    e = make_engine(tmp_path, opener)
    e.start()
    assert e.wait_state("connected")
    import time
    t = time.time()
    while not e.audio.blocks and time.time() - t < 3:
        time.sleep(0.01)
    assert e.audio.blocks and e.level is not None
    assert read_status(e.status.path)["state"] == "rx-only"
    e.stop()
    assert devs[0].closed and DeviceClaim("rtlsdr-0", "x", tmp_path / "locks").acquire()
    assert read_status(e.status.path)["state"] == "stopped"


def test_busy_device_reported(tmp_path):
    def opener():
        return FakeDevice(busy=True)
    e = make_engine(tmp_path, opener)
    e.start()
    assert e.wait_state("busy") and "in use" in e.error
    e.stop()


def test_claimed_by_other_task_app(tmp_path):
    other = DeviceClaim("rtlsdr-0", "task-other", tmp_path / "locks")
    assert other.acquire()
    e = make_engine(tmp_path, lambda: FakeDevice())
    e.start()
    assert e.state == "busy"
    other.release()


def test_unplug_and_replug(tmp_path):
    n = {"opens": 0}

    def opener():
        n["opens"] += 1
        return FakeDevice(unplug_after=3 if n["opens"] == 1 else None)
    import task_sdr.engine as eng
    eng.REOPEN_S = 0.05
    e = make_engine(tmp_path, opener)
    seen = []
    e.on_update = lambda kind, d: seen.append((d["state"], d["error"])) if kind == "state" else None
    e.start()
    assert e.wait_state("connected")
    import time
    time.sleep(0.3)
    states = [s for s, _ in seen]
    assert "disconnected" in states and "connected" in states[states.index("disconnected"):]
    assert any("unplugged" in (err or "") for _, err in seen)
    assert n["opens"] >= 2
    e.stop()


def test_squelch_mutes(tmp_path):
    e = make_engine(tmp_path, lambda: FakeDevice(noise=1e-4), squelch_dbfs=-20.0)
    e.demod = Demodulator("NFM", RATE)
    d = FakeDevice(noise=1e-4)
    d.configure(RATE, 1e8)
    out = e.process(d.read(65536))
    assert not np.any(out)


def test_prefs_persist_and_validate(tmp_path):
    p = tmp_path / "prefs.json"
    pr = P.Prefs(freq_hz=146_520_000, mode="NFM", ppm=3)
    P.save(pr, p)
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert P.load(p).freq_hz == 146_520_000 and P.load(p).ppm == 3
    with pytest.raises(ValueError):
        P.Prefs(freq_hz=10).validate()
    p.write_text("{broken")
    assert P.load(p).freq_hz == P.Prefs().freq_hz


def test_direwolf_card_excluded(tmp_path):
    conf = tmp_path / "direwolf.conf"
    conf.write_text("ADEVICE plughw:CARD=Device,DEV=0\n")
    cards = direwolf_cards([conf])
    assert cards == {"device"}
    devs = [("alsa_output.usb-C-Media_USB_Audio_Device", "USB Audio Device"), ("hdmi", "HDMI")]
    assert allowed_devices(devs, cards) == [("hdmi", "HDMI")]


def test_enumerate_with_fake_soapy():
    class Dev:
        @staticmethod
        def enumerate(args):
            return [{"driver": "rtlsdr", "label": "Generic RTL2832U OEM :: 00000001", "serial": "1",
                     "product": "Blog V4"}]

    class Soapy:
        Device = Dev
    out = enumerate_devices(Soapy)
    assert out[0]["blog_v4"] and out[0]["serial"] == "1"


def test_receive_only_sources():
    for f in PKG.rglob("*.py"):
        src = f.read_text()
        for bad in ("SOAPY_SDR_TX", "writeStream", "shell=True", "os.system", "subprocess"):
            assert bad not in src, (f, bad)
        tree = ast.parse(src)
        assert tree


def test_real_soapysdr_binding_imports():
    SoapySDR = pytest.importorskip("SoapySDR")
    assert hasattr(SoapySDR, "SOAPY_SDR_RX") and hasattr(SoapySDR.Device, "enumerate")
