# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Synthetic band for scanner tests/benchmarks (no hardware): transmissions at ABSOLUTE frequencies with
start/duration in SAMPLE time, so results are deterministic and independent of CPU speed."""

import numpy as np


class BandDevice:
    def __init__(self, transmissions, rate=1_024_000, noise=1e-3, seed=7, retune_latency_samples=0):
        """transmissions: [dict(freq, start, dur, kind='voice'|'carrier', amp)] (seconds)."""
        self.tx, self.rate, self.noise = list(transmissions), rate, noise
        self.rng = np.random.default_rng(seed)
        self.n = 0                       # samples elapsed
        self.freq = None
        self.retunes = 0
        self.latency = retune_latency_samples
        self.profile = None

    @property
    def t(self):
        return self.n / self.rate

    def configure(self, rate, freq_hz, gain_db=None, ppm=0):
        self.rate, self.freq = rate, freq_hz

    def set_frequency(self, hz):
        self.freq = hz
        self.retunes += 1
        self.n += self.latency           # time lost while the tuner settles

    def set_gain(self, g):
        pass

    def start(self):
        pass

    def close(self):
        pass

    def read(self, n):
        t = (np.arange(n) + self.n) / self.rate
        x = (self.rng.normal(size=n) + 1j * self.rng.normal(size=n)) * self.noise
        lo, hi = t[0], t[-1]
        for s in self.tx:
            if s["start"] > hi or s["start"] + s["dur"] < lo:
                continue
            off = s["freq"] - self.freq
            if abs(off) > self.rate / 2:
                continue
            on = ((t >= s["start"]) & (t < s["start"] + s["dur"])).astype(np.float32)
            a = s.get("amp", 0.05)
            if s.get("kind", "voice") == "voice":
                # FM, 3 kHz deviation, syllabic (4 Hz) amplitude-varying 300-2500 Hz audio
                m = np.sin(2 * np.pi * 800 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) + \
                    0.5 * np.sin(2 * np.pi * 1700 * t) * (0.5 + 0.5 * np.cos(2 * np.pi * 3 * t))
                phase = 2 * np.pi * off * t + 2 * np.pi * 3000 * np.cumsum(m) / self.rate
            else:
                phase = 2 * np.pi * off * t
            x += a * on * np.exp(1j * phase)
        self.n += n
        return x.astype(np.complex64)


def random_traffic(channels, seconds, count, seed=3, dur=(1.0, 6.0), amp=(0.01, 0.1), kind="voice"):
    """Non-overlapping-per-channel random transmissions (for the missed-transmission benchmark)."""
    rng = np.random.default_rng(seed)
    out, busy = [], {}
    while len(out) < count:
        f = int(rng.choice(channels))
        s = float(rng.uniform(1.0, seconds - dur[1]))
        d = float(rng.uniform(*dur))
        if any(not (s + d + 0.5 < a or s > b + 0.5) for a, b in busy.get(f, [])):
            continue
        busy.setdefault(f, []).append((s, s + d))
        out.append({"freq": f, "start": s, "dur": d, "amp": float(rng.uniform(*amp)), "kind": kind})
    return sorted(out, key=lambda x: x["start"])
