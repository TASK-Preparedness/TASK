# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Receive-only device layer over SoapySDR (python3-soapysdr). No transmit API is ever used.
A FakeDevice produces synthetic IQ for simulated tests and training."""

import time

import numpy as np

RTL_RATES = (1_024_000, 1_200_000, 1_920_000, 2_048_000, 2_400_000)


class DeviceError(OSError):
    pass


class DeviceBusy(DeviceError):
    pass


def _busy_text(msg):
    m = msg.lower()
    return "usb_claim_interface" in m or "busy" in m or "-6" in m


def enumerate_devices(soapy=None):
    """[{label, driver, serial, tuner, args}] for RTL-SDR devices."""
    try:
        soapy = soapy or __import__("SoapySDR")
        found = soapy.Device.enumerate({"driver": "rtlsdr"})
    except (ImportError, RuntimeError) as exc:
        raise DeviceError(f"SoapySDR unavailable: {exc}")
    out = []
    for kw in found:
        d = {k: kw[k] for k in kw.keys()} if hasattr(kw, "keys") else dict(kw)
        label = d.get("label") or d.get("product") or "RTL-SDR"
        out.append({"label": label, "driver": d.get("driver", "rtlsdr"), "serial": d.get("serial", ""),
                    "tuner": d.get("tuner", ""), "args": d,
                    "blog_v4": "blog v4" in (label + d.get("product", "")).lower()})
    return out


class SoapyDevice:
    def __init__(self, args: dict, soapy=None):
        self.soapy = soapy or __import__("SoapySDR")
        try:
            self.dev = self.soapy.Device(args)
        except RuntimeError as exc:
            if _busy_text(str(exc)):
                raise DeviceBusy("the SDR is in use by another program")
            raise DeviceError(str(exc))
        self.stream = None
        self.rate = None

    def info(self):
        return {"hardware": self.dev.getHardwareKey(), "info": dict(self.dev.getHardwareInfo()),
                "gain_range": str(self.dev.getGainRange(self.soapy.SOAPY_SDR_RX, 0))}

    def configure(self, rate, freq_hz, gain_db=None, ppm=0):
        rx = self.soapy.SOAPY_SDR_RX
        self.dev.setSampleRate(rx, 0, rate)
        self.rate = rate
        self.set_frequency(freq_hz)
        self.set_gain(gain_db)
        if ppm and self.dev.hasFrequencyCorrection(rx, 0):
            self.dev.setFrequencyCorrection(rx, 0, ppm)

    def set_frequency(self, hz):
        self.dev.setFrequency(self.soapy.SOAPY_SDR_RX, 0, float(hz))

    def set_gain(self, gain_db):
        rx = self.soapy.SOAPY_SDR_RX
        if gain_db is None:
            self.dev.setGainMode(rx, 0, True)
        else:
            self.dev.setGainMode(rx, 0, False)
            self.dev.setGain(rx, 0, float(gain_db))

    def start(self):
        self.stream = self.dev.setupStream(self.soapy.SOAPY_SDR_RX, self.soapy.SOAPY_SDR_CF32)
        self.dev.activateStream(self.stream)

    def read(self, n):
        buf = np.empty(n, np.complex64)
        sr = self.dev.readStream(self.stream, [buf], n, timeoutUs=500_000)
        if sr.ret < 0:
            if sr.ret == self.soapy.SOAPY_SDR_TIMEOUT:
                return buf[:0]
            raise DeviceError(f"read failed ({self.soapy.errToStr(sr.ret)}) — unplugged?")
        return buf[:sr.ret]

    def close(self):
        if self.stream is not None:
            try:
                self.dev.deactivateStream(self.stream)
                self.dev.closeStream(self.stream)
            except Exception:  # noqa: BLE001 — device may already be gone
                pass
            self.stream = None
        self.dev = None


class FakeDevice:
    """Synthetic IQ: signals = [(offset_hz, kind, params)] relative to the tuned frequency.
    kind: 'tone' | 'fm' (audio tone, deviation) | 'am' (tone, depth). Simulates busy / unplug on request."""

    def __init__(self, signals=(), noise=1e-3, busy=False, unplug_after=None, seed=1, pace=False):
        if busy:
            raise DeviceBusy("the SDR is in use by another program (simulated)")
        self.signals, self.noise, self.unplug_after = list(signals), noise, unplug_after
        self.rng = np.random.default_rng(seed)
        self.t0 = 0
        self.rate = None
        self.freq = None
        self.gain = None
        self.reads = 0
        self.pace = pace
        self.closed = False

    def info(self):
        return {"hardware": "SIMULATED RTL-SDR", "info": {}, "gain_range": "0-49.6 dB"}

    def configure(self, rate, freq_hz, gain_db=None, ppm=0):
        self.rate, self.freq, self.gain = rate, freq_hz, gain_db

    def set_frequency(self, hz):
        self.freq = hz

    def set_gain(self, g):
        self.gain = g

    def start(self):
        pass

    def read(self, n):
        if self.unplug_after is not None and self.reads >= self.unplug_after:
            raise DeviceError("read failed (simulated unplug)")
        self.reads += 1
        t = (np.arange(n) + self.t0) / self.rate
        self.t0 += n
        x = (self.rng.normal(size=n) + 1j * self.rng.normal(size=n)) * self.noise
        for off, kind, p in self.signals:
            if kind == "tone":
                x += p.get("amp", 0.5) * np.exp(2j * np.pi * off * t)
            elif kind == "fm":
                phase = 2 * np.pi * off * t + p["dev"] / p["af"] * np.sin(2 * np.pi * p["af"] * t)
                x += p.get("amp", 0.5) * np.exp(1j * phase)
            elif kind == "am":
                x += p.get("amp", 0.5) * (1 + p["depth"] * np.sin(2 * np.pi * p["af"] * t)) * \
                    np.exp(2j * np.pi * off * t)
        if self.pace:
            time.sleep(n / self.rate)
        return x.astype(np.complex64)

    def close(self):
        self.closed = True
