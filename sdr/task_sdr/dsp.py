# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Demodulators built on scipy.signal (filter design + stateful lfilter); only the glue is ours.
Receive only."""

import numpy as np
from scipy import signal

AUDIO_RATE = 48_000
MODES = ("WFM", "NFM", "AM", "USB", "LSB", "CW")
# mode -> (IF rate, channel half-bandwidth Hz, audio low-pass Hz)
PLAN = {"WFM": (240_000, 100_000, 15_000), "NFM": (48_000, 6_250, 4_000), "AM": (48_000, 5_000, 4_500),
        "USB": (48_000, 1_500, 3_000), "LSB": (48_000, 1_500, 3_000), "CW": (48_000, 1_500, 1_200)}
# mode -> (default, min, max) user bandwidth in Hz (full width of the passband)
BANDWIDTH = {"WFM": (200_000, 50_000, 220_000), "NFM": (12_500, 5_000, 25_000), "AM": (10_000, 3_000, 15_000),
             "USB": (2_800, 1_500, 4_000), "LSB": (2_800, 1_500, 4_000), "CW": (500, 100, 1_500)}
CW_PITCH = 700.0


class StatefulFir:
    """FIR low-pass + integer decimation with filter state kept across blocks.
    0.2.4: overlap-save FFT convolution (scipy.signal.oaconvolve) instead of direct-form lfilter — numerically the same
    filter (tested block-size invariant) at a fraction of the cost (profiled: the channel filter was 82 % of the WFM
    block time in 0.2.3). Real input stays real (the audio path no longer runs as complex)."""

    def __init__(self, rate, cutoff, decim=1, taps=129):
        self.h = signal.firwin(taps, min(cutoff, rate / 2 * 0.95), fs=rate)
        self.hist = None
        self.decim, self.phase = int(decim), 0

    def __call__(self, x):
        if len(x) == 0:
            return x[:0]
        if self.hist is None or (np.iscomplexobj(x) and not np.iscomplexobj(self.hist)):
            self.hist = np.zeros(len(self.h) - 1, dtype=x.dtype if np.iscomplexobj(x) else np.float64)
        buf = np.concatenate((self.hist, x))
        y = signal.oaconvolve(buf, self.h, mode="valid") if len(x) > 4 * len(self.h) else \
            np.convolve(buf, self.h, mode="valid")
        self.hist = buf[len(buf) - (len(self.h) - 1):]
        out = y[self.phase::self.decim]
        self.phase = (self.phase - len(x)) % self.decim
        return out


class Demodulator:
    def __init__(self, mode: str, in_rate: int, deemphasis_us: float = 75.0, bandwidth=None):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
        self.mode, self.in_rate = mode, int(in_rate)
        if_rate, half_bw, af = PLAN[mode]
        dflt, lo, hi = BANDWIDTH[mode]
        self.bandwidth = int(min(max(int(bandwidth or dflt), lo), hi))
        if mode in ("WFM", "NFM", "AM"):
            half_bw = self.bandwidth / 2
            af = min(af, half_bw)
        d1 = max(1, round(self.in_rate / if_rate))
        self.if_rate = self.in_rate / d1
        self.chan = StatefulFir(self.in_rate, half_bw, d1)
        self.prev = 0j
        self.n = 0
        self.ssb_shift = {"USB": +1, "LSB": -1, "CW": +1}.get(mode, 0)
        self.ssb_osc = 0
        ssb_bw = self.bandwidth / 2
        self.ssb_filter = StatefulFir(self.if_rate, ssb_bw, 1) if self.ssb_shift else None
        self.audio_lp = StatefulFir(self.if_rate, af, 1)
        self.resample = (AUDIO_RATE, self.if_rate)
        if mode == "WFM" and deemphasis_us:
            tau = deemphasis_us * 1e-6
            a = np.exp(-1.0 / (self.if_rate * tau))
            self.de_b, self.de_a = [1 - a], [1, -a]
            self.de_zi = np.zeros(1)
        else:
            self.de_b = None
        self.dc = 0.0
        self.frac = 0.0
        self.last = 0.0          # last audio-rate-domain sample of the previous block (resampler continuity)
        # discriminator normalisation: WFM broadcast is +-75 kHz peak deviation -> +-1.0 (0.2.3 used the 100 kHz
        # channel half-width, i.e. full deviation came out at 0.75). Other modes unchanged.
        self.fm_ref_hz = 75_000.0 if mode == "WFM" else float(PLAN[mode][1])

    def _fm(self, x):
        z = np.concatenate(([self.prev], x))
        self.prev = x[-1]
        d = np.angle(z[1:] * np.conj(z[:-1]))
        return d * self.if_rate / (2 * np.pi * self.fm_ref_hz)   # 1.0 at the reference (WFM: 75 kHz) deviation

    def process(self, iq: np.ndarray) -> np.ndarray:
        """Complex64 IQ at in_rate -> float32 audio at 48 kHz (−1..1)."""
        x = self.chan(np.asarray(iq, np.complex64))
        if len(x) == 0:
            return np.zeros(0, np.float32)
        if self.mode in ("WFM", "NFM"):
            a = self._fm(x)
        elif self.mode == "AM":
            env = np.abs(x)
            self.dc = 0.999 * self.dc + 0.001 * float(env.mean()) if self.n else float(env.mean())
            a = (env - self.dc) / (self.dc + 1e-9)
        else:
            # Weaver-style: shift the wanted sideband to centre, low-pass, shift back, take real part
            t = np.arange(len(x)) + self.ssb_osc
            self.ssb_osc += len(x)
            # SSB: passband centre = bandwidth/2 from the carrier; CW: centre = 0 Hz offset, BFO pitch added below
            centre = self.bandwidth / 2 if self.mode != "CW" else 0.0
            w = 2 * np.pi * centre / self.if_rate
            lo = np.exp(-1j * self.ssb_shift * w * t)
            y = self.ssb_filter(x * lo)
            if self.mode == "CW":
                bfo = np.exp(2j * np.pi * CW_PITCH * t / self.if_rate)
                a = np.real(y * bfo) * 2
            else:
                a = np.real(y * np.conj(lo)) * 2
        self.n += 1
        a = self.audio_lp(np.ascontiguousarray(np.real(a), dtype=np.float64))
        if self.de_b is not None:
            a, self.de_zi = signal.lfilter(self.de_b, self.de_a, a, zi=self.de_zi)
        return self._to_audio(a)

    def _to_audio(self, a):
        """Fractional resampling (linear interpolation) of an already low-passed (<=15 kHz at >=240 kHz, i.e. 16x
        oversampled) signal. 0.2.4: the previous block's last sample is prepended so an output position that falls
        between two blocks is interpolated, not clamped; phase kept across blocks -> block-size invariant output.
        No clipping here (clipping, if any, happens once at the output stage and is counted there)."""
        step = self.if_rate / AUDIO_RATE
        z = np.concatenate(([self.last], a))             # index 0 = previous block's last sample (position -1)
        pos = np.arange(self.frac, len(a) - 1 + 1e-9, step)   # positions relative to a[0]; may be in (-1, 0)
        self.frac = (pos[-1] + step - len(a)) if len(pos) else self.frac - len(a)
        self.last = float(a[-1]) if len(a) else self.last
        out = np.interp(pos + 1.0, np.arange(len(z)), z)
        return out.astype(np.float32)


def power_dbfs(iq: np.ndarray) -> float:
    p = float(np.mean(np.abs(iq) ** 2)) if len(iq) else 0.0
    return 10 * np.log10(p + 1e-20)


class Squelch:
    def __init__(self, threshold_dbfs=None):
        self.threshold = threshold_dbfs

    def open(self, level):
        return self.threshold is None or level >= self.threshold


class Spectrum:
    """Windowed FFT (dBFS) + waterfall ring buffer."""

    def __init__(self, size=1024, rows=200):
        self.size, self.window = size, signal.windows.blackmanharris(size)
        self.norm = np.sum(self.window) ** 2
        self.waterfall = np.full((rows, size), -120.0, np.float32)
        self.row = 0

    def compute(self, iq):
        if len(iq) < self.size:
            iq = np.pad(iq, (0, self.size - len(iq)))
        spec = np.fft.fftshift(np.fft.fft(iq[:self.size] * self.window))
        db = (10 * np.log10(np.abs(spec) ** 2 / self.norm + 1e-20)).astype(np.float32)
        self.waterfall[self.row % len(self.waterfall)] = db
        self.row += 1
        return db

    def ordered_waterfall(self):
        r = self.row % len(self.waterfall)
        return np.vstack((self.waterfall[r:], self.waterfall[:r]))[::-1]   # newest first


class Agc:
    """Audio AGC (receive audio only). 0.2.4 rewrite.
    0.2.3 normalised every 64 ms block to a PEAK of 0.25 with one gain step per block: programme audio sat ~-20 dBFS
    RMS (quiet) and the gain jumped at block boundaries. Now: RMS target with time constants (attack 30 ms,
    release 1.5 s), the gain is ramped sample-by-sample across the block (no zipper steps), and a look-at-block
    peak limit keeps |out| <= 0.95 so the AGC itself never clips. Gain range 0.1 .. max_gain."""

    def __init__(self, target=0.25, attack_s=0.03, release_s=1.5, max_gain=50.0, min_gain=0.1, peak_limit=0.95,
                 rate=AUDIO_RATE):
        self.target, self.attack_s, self.release_s = target, attack_s, release_s
        self.max_gain, self.min_gain, self.peak_limit, self.rate = max_gain, min_gain, peak_limit, rate
        self.gain = 1.0

    @property
    def gain_db(self):
        return 20 * np.log10(max(self.gain, 1e-9))

    def __call__(self, a):
        a = np.asarray(a, np.float32)
        if len(a) == 0:
            return a
        rms = float(np.sqrt(np.mean(np.square(a, dtype=np.float64)))) + 1e-9
        peak = float(np.max(np.abs(a))) + 1e-9
        want = min(max(self.target / rms, self.min_gain), self.max_gain)
        tau = self.attack_s if want < self.gain else self.release_s
        k = 1.0 - np.exp(-len(a) / (self.rate * tau))
        g_end = float(np.exp(np.log(self.gain) + (np.log(want) - np.log(self.gain)) * k))   # smoothed in dB
        ramp = np.geomspace(self.gain, g_end, len(a) + 1)[1:]
        lim = self.peak_limit / np.maximum(np.abs(a), 1e-9)
        g = np.minimum(ramp, lim)                    # instantaneous limiter: never exceeds peak_limit
        if g_end * peak > self.peak_limit:           # carry the limited gain forward (fast attack on peaks)
            g_end = min(g_end, self.peak_limit / peak)
        self.gain = float(g_end)
        return (a * g).astype(np.float32)


def audio_levels(a):
    """(rms, peak) linear of a float audio block; (0, 0) when empty."""
    if len(a) == 0:
        return 0.0, 0.0
    return float(np.sqrt(np.mean(np.square(a, dtype=np.float64)))), float(np.max(np.abs(a)))


def dbfs(x):
    return 20 * np.log10(max(float(x), 1e-10))


def channel_power_dbfs(spectrum_db, bin_hz, offset_hz, bandwidth_hz):
    """Power inside the tuned channel from a centred spectrum (dBFS); robust to out-of-channel signals."""
    n = len(spectrum_db)
    c = n // 2 + int(round(offset_hz / bin_hz))
    half = max(1, int(round(bandwidth_hz / 2 / bin_hz)))
    lo, hi = max(0, c - half), min(n, c + half + 1)
    if lo >= hi:
        return -150.0
    return float(10 * np.log10(np.sum(10 ** (spectrum_db[lo:hi] / 10)) + 1e-20))


def s_meter(dbfs, s9_dbfs=-30.0):
    """-> (label, s_units_float). UNCALIBRATED: S9 is a configurable dBFS reference, 6 dB per S unit."""
    s = 9 + (dbfs - s9_dbfs) / 6.0
    if s <= 9:
        return f"S{max(0, int(round(s)))}", max(0.0, s)
    return f"S9+{int(round(dbfs - s9_dbfs))}", s
