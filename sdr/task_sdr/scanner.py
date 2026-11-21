# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Smart Scanner (SDR Studio M2, task-sdr 0.2.1). RECEIVE ONLY.

FAST sweep: the channel list is grouped into "chunks" that fit inside the usable part of one tuned bandwidth;
each dwell measures every channel of the chunk from ONE averaged PSD, so a 4 MHz band at 12.5 kHz steps
needs ~5 retunes per pass, not 320.

Activity  = channel power >= max(adaptive noise floor + snr_db, user squelch).
            The noise floor is a per-channel EMA updated only while the channel is idle (median-seeded).
On activity the scanner LOCKS: it centres the receiver on the channel. The triggering IQ block is kept as a
pre-buffer, shifted to baseband and demodulated first, so the start of the transmission is heard.
Hold      = 4 s after the last activity; any activity resets it. Then the sweep resumes after that channel.
VAD       = optional voice check on the demodulated audio (voice-band energy ratio + modulation).
            OPTIONAL carrier-only timeout (OFF by default): a channel the VAD judged "no voice" is released
            after `carrier_timeout_s`. When off, the only release is the 4 s hold. Modes without
            voice (CW, WFM) and audio that cannot be analysed fall back to squelch-only.
Ignore    = entries {freq, tolerance (default 0 Hz = exact), session|persistent}; edit/remove by entry.
            Effective tolerance is capped below half the channel spacing so adjacent channels are never hidden.
States    = idle | scanning | locked | paused (paused_from = scanning|locked). See TRANSITIONS.
History   = newest first, 50 entries; pinned entries are never evicted and do not count toward the 50.
The Scanner never transmits and never touches anything but the receive frequency."""

import collections
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from task_sdr.freq import hz as _hz

HOLD_S = 4.0
HISTORY_MAX = 50
USABLE = 0.8              # fraction of the sample rate used for detection (filter roll-off at the edges)
SCAN_BLOCK = 8192         # samples per dwell (8 ms at 1.024 Msps)
SETTLE_BLOCKS = 1         # blocks discarded after each retune (stale samples in the driver's buffers)
PSD_SIZE = 1024
PREBUFFER_BLOCKS = 2


def psd_db(iq, size=PSD_SIZE, _w={}):
    """Averaged (Welch, non-overlapping) power spectrum, centred, dBFS per bin."""
    w = _w.get(size)
    if w is None:
        w = _w[size] = (np.hanning(size).astype(np.float32), float(np.sum(np.hanning(size)) ** 2))
    n = (len(iq) // size) * size
    if n == 0:
        iq, n = np.pad(iq, (0, size - len(iq))), size
    frames = iq[:n].reshape(-1, size) * w[0]
    p = np.mean(np.abs(np.fft.fft(frames, axis=1)) ** 2, axis=0) / w[1]
    return np.fft.fftshift(10 * np.log10(p + 1e-20)).astype(np.float32)


def band_power_db(db, bin_hz, offset_hz, bw_hz):
    n = len(db)
    c = n // 2 + int(round(offset_hz / bin_hz))
    half = max(1, int(round(bw_hz / 2 / bin_hz)))
    lo, hi = max(0, c - half), min(n, c + half + 1)
    if lo >= hi:
        return -150.0
    return float(10 * np.log10(np.sum(10 ** (db[lo:hi].astype(np.float64) / 10)) + 1e-20))


def vad(audio, rate):
    """-> True (voice-like), False (carrier/silence) or None (cannot tell: too short / not analysable).
    Voice: most energy in 300-3400 Hz AND the short-term envelope varies (syllables), unlike a steady tone."""
    a = np.asarray(audio, np.float64)
    if len(a) < rate // 20 or not np.all(np.isfinite(a)):
        return None
    if np.sqrt(np.mean(a ** 2)) < 1e-4:
        return False
    spec = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    f = np.fft.rfftfreq(len(a), 1 / rate)
    voice = spec[(f >= 300) & (f <= 3400)].sum() / (spec.sum() + 1e-20)
    seg = len(a) // 10
    env = np.sqrt(np.mean(a[:seg * 10].reshape(10, seg) ** 2, axis=1))
    var = np.std(env) / (np.mean(env) + 1e-12)
    flat = np.exp(np.mean(np.log(spec[1:] + 1e-20))) / (np.mean(spec[1:]) + 1e-20)   # ~1 = white noise
    return bool(voice > 0.6 and var > 0.15 and flat < 0.5)       # steady tones fail the envelope test


VOICE_MODES = {"NFM", "AM", "USB", "LSB"}

# (state, command) -> resulting state; anything not listed leaves the state unchanged.
# "paused/S" = paused from scanning, "paused/L" = paused from locked. Tested in test_scanner_022.py.
TRANSITIONS = {
    ("idle", "scan"): "scanning", ("scanning", "scan"): "scanning", ("locked", "scan"): "scanning",
    ("paused/S", "scan"): "scanning", ("paused/L", "scan"): "scanning",
    ("scanning", "stop"): "idle", ("locked", "stop"): "idle", ("paused/S", "stop"): "idle",
    ("paused/L", "stop"): "idle",
    ("scanning", "pause"): "paused/S", ("locked", "pause"): "paused/L",
    ("paused/S", "resume"): "scanning", ("paused/L", "resume"): "locked",
    ("scanning", "skip"): "scanning", ("locked", "skip"): "scanning", ("paused/S", "skip"): "scanning",
    ("paused/L", "skip"): "scanning",
    ("scanning", "activity"): "locked", ("locked", "hold expired"): "scanning",
}


@dataclass
class HistoryEntry:
    freq_hz: int
    mode: str
    first: float                  # wall clock (time.time) of detection
    last: float
    peak_dbfs: float
    voice: object = None          # True / False / None (squelch-only)
    pinned: bool = False
    note: str = ""
    duration_s: float = 0.0       # receive (sample) time from detection to last activity
    t_rx: float = 0.0             # receive (sample) time of detection


@dataclass
class ScanConfig:
    start_hz: int = 144_000_000
    stop_hz: int = 148_000_000
    step_hz: int = 12_500
    mode: str = "NFM"
    channel_bw_hz: int = 12_500
    channels: list = None         # explicit list (e.g. bookmarks) instead of start/stop/step
    snr_db: float = 10.0
    squelch_dbfs: float = None
    hold_s: float = HOLD_S
    use_vad: bool = True          # voice check: labels history entries; needed by the carrier timeout
    carrier_timeout_s: float = None   # OFF by default; seconds before a no-voice carrier is released

    def spacing_hz(self):
        """Smallest spacing between scanned channels (step, or the closest pair of listed channels)."""
        if self.channels:
            ch = sorted({int(c) for c in self.channels})
            gaps = [b - a for a, b in zip(ch, ch[1:])]
            return min(gaps) if gaps else None
        return int(self.step_hz)

    def channel_list(self, profile=None):
        if self.channels:
            ch = sorted({_hz(c, "scan channel") for c in self.channels})
        else:
            _hz(self.start_hz, "scan start"), _hz(self.stop_hz, "scan stop"), _hz(self.step_hz, "scan step", 1)
            if self.step_hz <= 0 or self.stop_hz < self.start_hz:
                raise ValueError("bad scan range")
            n = (self.stop_hz - self.start_hz) // self.step_hz + 1
            if n > 200_000:
                raise ValueError("too many channels")
            ch = [self.start_hz + i * self.step_hz for i in range(n)]
        if profile is not None:
            ch = [c for c in ch if profile.accepts(c)]
        if not ch:
            raise ValueError("no channels inside the receiver's range")
        return ch


def plan_chunks(channels, sample_rate, channel_bw, usable=USABLE, accepts=None):
    """Group sorted channels into [(centre_hz, [channels])] so every channel fits in the usable span."""
    span = sample_rate * usable - channel_bw
    chunks, cur = [], []
    for c in channels:
        if cur and c - cur[0] > span:
            chunks.append(cur)
            cur = []
        cur.append(c)
    if cur:
        chunks.append(cur)
    out = []
    for g in chunks:
        centre = (g[0] + g[-1]) // 2
        if len(g) == 1:
            centre = g[0] + int(channel_bw)       # keep the channel off the DC spike
            if accepts is not None and not accepts(centre):
                centre = g[0] - int(channel_bw)
        out.append((centre, g))
    return out


@dataclass
class IgnoreEntry:
    freq_hz: int
    tolerance_hz: int = 0         # 0 = exact frequency only
    persistent: bool = False      # True = "Always" (saved); False = this session only
    label: str = ""

    @property
    def kind(self):
        return "always" if self.persistent else "session"


def cap_for_spacing(spacing_hz):
    """Largest tolerance that can never reach an adjacent channel: strictly below half the spacing."""
    return None if not spacing_hz else max(0, (int(spacing_hz) - 1) // 2)


class IgnoreList:
    """Entries keyed by frequency. match() uses each entry's tolerance, capped by `cap_hz` (set from the scan's
    channel spacing). remove()/edit() act on ONE entry (by its frequency), never on neighbours."""

    MAX_TOLERANCE_HZ = 1_000_000

    def __init__(self, persistent=(), default_tolerance_hz=0):
        self.entries = {}
        self.default_tolerance_hz = int(default_tolerance_hz)
        self.cap_hz = None
        for e in persistent:
            e = self._coerce(e)
            self.entries[e.freq_hz] = e

    @staticmethod
    def _coerce(e):
        if isinstance(e, IgnoreEntry):
            return e
        if not isinstance(e, dict):       # 0.2.1 prefs: bare persistent frequencies -> exact (0 Hz), lossless
            return IgnoreEntry(_hz(e, "ignore"), 0, True)
        return IgnoreEntry(_hz(e["freq_hz"], "ignore"), _hz(e.get("tolerance_hz", 0), "tolerance", 0, 1_000_000),
                           True, str(e.get("label", "")))

    def _check_tol(self, t):
        t = _hz(t, "ignore tolerance")
        if not 0 <= t <= self.MAX_TOLERANCE_HZ:
            raise ValueError("ignore tolerance must be 0 Hz to 1 MHz")
        return t

    def add(self, freq_hz, persistent=False, tolerance_hz=None, label=""):
        t = self._check_tol(self.default_tolerance_hz if tolerance_hz is None else tolerance_hz)
        freq_hz = _hz(freq_hz, "ignore")
        old = self.entries.get(freq_hz)
        e = IgnoreEntry(freq_hz, t, bool(persistent) or bool(old and old.persistent), label or (old.label if old else ""))
        self.entries[e.freq_hz] = e
        return e

    def edit(self, freq_hz, tolerance_hz=None, persistent=None, label=None):
        e = self.entries[int(freq_hz)]
        if tolerance_hz is not None:
            e.tolerance_hz = self._check_tol(tolerance_hz)
        if persistent is not None:
            e.persistent = bool(persistent)
        if label is not None:
            e.label = str(label)
        return e

    def remove(self, freq_hz):
        return self.entries.pop(int(freq_hz), None) is not None

    def effective_tolerance(self, e):
        return e.tolerance_hz if self.cap_hz is None else min(e.tolerance_hz, self.cap_hz)

    def match(self, freq_hz):
        f = int(freq_hz)
        return any(abs(f - e.freq_hz) <= self.effective_tolerance(e) for e in self.entries.values())

    def review(self):
        """Sorted: persistent first, then session; each (freq, kind, tolerance, effective tolerance, label)."""
        es = sorted(self.entries.values(), key=lambda e: (not e.persistent, e.freq_hz))
        return [(e.freq_hz, e.kind, e.tolerance_hz, self.effective_tolerance(e), e.label) for e in es]

    @property
    def persistent(self):
        return sorted(f for f, e in self.entries.items() if e.persistent)

    @property
    def session(self):
        return sorted(f for f, e in self.entries.items() if not e.persistent)

    def to_prefs(self):
        """-> (entries for scan_ignore_entries, plain frequencies for the 0.2.1-compatible scan_ignores)."""
        es = [e for e in self.entries.values() if e.persistent]
        return ([{"freq_hz": e.freq_hz, "tolerance_hz": e.tolerance_hz, "label": e.label}
                 for e in sorted(es, key=lambda e: e.freq_hz)], sorted(e.freq_hz for e in es))


class History:
    def __init__(self, maxlen=HISTORY_MAX):
        self.maxlen, self.items = maxlen, []

    def add(self, e):
        self.items.insert(0, e)
        unpinned = [x for x in self.items if not x.pinned]
        if len(unpinned) > self.maxlen:
            drop = unpinned[self.maxlen:]
            self.items = [x for x in self.items if x not in drop]

    def pin(self, i, on=True):
        self.items[i].pinned = on

    def clear(self):
        self.items = [x for x in self.items if x.pinned]


class Scanner:
    """Driven by the engine worker: plan() -> centre to tune; feed(iq) after each read -> action dict.
    Thread-safe for the UI through self.lock. States: idle | scanning | locked | paused."""

    def __init__(self, sample_rate, profile=None, persistent_ignores=(), clock=None, wall=time.time,
                 audio_rate=48_000, default_tolerance_hz=0):
        self.rate, self.profile, self.wall, self.audio_rate = sample_rate, profile, wall, audio_rate
        self.sample_t = 0.0                     # seconds of IQ consumed: the hold timer runs on SAMPLE time
        self.clock = clock or (lambda: self.sample_t)
        self._abuf, self._alen = [], 0
        self.lock = threading.RLock()
        self.cfg = ScanConfig()
        self.ignores = IgnoreList(persistent_ignores, default_tolerance_hz)
        self.paused_from = None
        self.history = History()
        self.state = "idle"
        self.chunks, self.ci = [], 0
        self.floor = {}
        self.settle = 0
        self.locked = None                       # channel frequency while locked
        self.entry = None
        self.last_active = 0.0
        self.voice_seen = 0.0
        self.lock_t = 0.0
        self.prebuf = collections.deque(maxlen=PREBUFFER_BLOCKS)
        self.stats = collections.Counter()
        self._resume_after = None

    # ------------------------------------------------------------- UI
    def start(self, cfg: ScanConfig):
        """any state -> scanning (a fresh scan)."""
        with self.lock:
            ch = cfg.channel_list(self.profile)
            self.cfg = cfg
            self.ignores.cap_hz = cap_for_spacing(cfg.spacing_hz())
            self.chunks = plan_chunks(ch, self.rate, cfg.channel_bw_hz,
                                      accepts=self.profile.accepts if self.profile else None)
            self.ci, self.floor, self.locked, self.state, self.paused_from = 0, {}, None, "scanning", None
            self.settle = SETTLE_BLOCKS
            return self.chunks[0][0]

    def stop(self):
        """any state -> idle."""
        with self.lock:
            self._release("stopped")
            self.state, self.paused_from = "idle", None

    def pause(self):
        """scanning -> paused(from scanning; stays on the current span, no audio);
        locked -> paused(from locked; stays on the channel, audio continues, hold timer frozen).
        Anything else: no change. Returns True if the state changed."""
        with self.lock:
            if self.state in ("scanning", "locked"):
                self.paused_from, self.state = self.state, "paused"
                return True
            return False

    def resume(self):
        """paused -> the state it was paused from (locked: the 4 s hold restarts; scanning: same span).
        Anything else: no change. Returns the frequency to tune (or None)."""
        with self.lock:
            if self.state != "paused":
                return None
            self.state, self.paused_from = self.paused_from, None
            if self.state == "locked":
                self.last_active = self.clock()
                return self.locked
            self.settle = SETTLE_BLOCKS
            return self.chunks[self.ci][0]

    def skip(self):
        """locked / paused / scanning -> scanning the NEXT span (a locked channel is released as 'skipped'
        and not re-locked immediately). idle: no change. Returns the frequency to tune (or None)."""
        with self.lock:
            if self.state == "idle":
                return None
            self._release("skipped")
            self.state, self.paused_from = "scanning", None
            return self._goto_next()

    def ignore_current(self, persistent=False, tolerance_hz=None):
        """Ignore the locked channel (or the latest detection) and skip on."""
        with self.lock:
            f = self.locked or (self.entry.freq_hz if self.entry else None)
            if f is None:
                return None
            self.ignores.add(f, persistent, tolerance_hz)
            return self.skip() if self.state in ("locked", "paused") and self.locked == f else None

    def ignore_freq(self, freq_hz, persistent=False, tolerance_hz=None):
        """Ignore any frequency (e.g. from history). If it is the locked channel, skip on."""
        with self.lock:
            self.ignores.add(freq_hz, persistent, tolerance_hz)
            if self.locked is not None and self.ignores.match(self.locked):
                return self.skip()
            return None

    def unignore(self, freq_hz):
        with self.lock:
            return self.ignores.remove(freq_hz)

    def set_pin(self, index, on):
        with self.lock:
            if 0 <= index < len(self.history.items):
                self.history.items[index].pinned = bool(on)
                return True
            return False

    # ---------------------------------------------------------- worker
    def block_size(self):
        return SCAN_BLOCK

    def centre(self):
        with self.lock:
            if self.locked is not None:
                return self.locked
            return self.chunks[self.ci][0] if self.chunks else None

    def feed(self, iq):
        """-> {'tune': hz|None, 'listen': bool, 'prebuffer': [iq,...] (shifted to the channel)}."""
        with self.lock:
            self.sample_t += len(iq) / self.rate
            st = self.state
            if st in ("idle", "paused"):
                return {"tune": None, "listen": st == "paused" and self.locked is not None, "prebuffer": []}
            if self.settle > 0:
                self.settle -= 1
                self.stats["settle"] += 1
                return {"tune": None, "listen": False, "prebuffer": []}
            return self._feed_locked(iq) if st == "locked" else self._feed_scan(iq)

    def _thresh(self, f):
        t = self.floor.get(f, -150.0) + self.cfg.snr_db
        return max(t, self.cfg.squelch_dbfs) if self.cfg.squelch_dbfs is not None else t

    def _feed_scan(self, iq):
        self.stats["dwells"] += 1
        centre, chans = self.chunks[self.ci]
        db = psd_db(iq)
        bin_hz = self.rate / len(db)
        bw = self.cfg.channel_bw_hz
        levels = {c: band_power_db(db, bin_hz, c - centre, bw) for c in chans}
        med = float(np.median(list(levels.values())))
        best = None
        for c, lvl in levels.items():
            if c not in self.floor:
                self.floor[c] = min(lvl, med)
            if lvl >= self._thresh(c) and not self.ignores.match(c) and c != self._resume_after:
                if best is None or lvl - self._thresh(c) > best[1] - self._thresh(best[0]):
                    best = (c, lvl)
            elif lvl < self._thresh(c):
                self.floor[c] += (lvl - self.floor[c]) * 0.1
        self.stats["channels_measured"] += len(chans)
        self._resume_after = None
        if best is None:
            return {"tune": self._goto_next(), "listen": False, "prebuffer": []}
        c, lvl = best
        now = self.clock()
        self.locked, self.state, self.last_active, self.lock_t, self.voice_seen = c, "locked", now, now, now
        self.entry = HistoryEntry(c, self.cfg.mode, self.wall(), self.wall(), lvl, t_rx=now)
        self.history.add(self.entry)
        self.stats["detections"] += 1
        t = np.arange(len(iq)) / self.rate
        pre = [(iq * np.exp(-2j * np.pi * (c - centre) * t)).astype(np.complex64)]
        self.settle = SETTLE_BLOCKS
        return {"tune": c, "listen": True, "prebuffer": pre}

    def _feed_locked(self, iq, audio=None):
        db = psd_db(iq)
        lvl = band_power_db(db, self.rate / len(db), 0, self.cfg.channel_bw_hz)
        now = self.clock()
        if lvl >= self._thresh(self.locked):
            self.last_active = now
            self.entry.last = self.wall()
            self.entry.duration_s = now - self.lock_t
            self.entry.peak_dbfs = max(self.entry.peak_dbfs, lvl)
        if now - self.last_active >= self.cfg.hold_s:
            return {"tune": self._release_and_next("ended"), "listen": False, "prebuffer": []}
        if (self.cfg.carrier_timeout_s is not None and self.cfg.use_vad and self.cfg.mode in VOICE_MODES
                and self.entry.voice is False and now - self.voice_seen >= self.cfg.carrier_timeout_s):
            self.entry.note = f"carrier without voice, released after {self.cfg.carrier_timeout_s:g} s (timeout on)"
            return {"tune": self._release_and_next("carrier timeout"), "listen": False, "prebuffer": []}
        return {"tune": None, "listen": True, "prebuffer": []}

    def on_audio(self, audio):
        """Engine passes demodulated audio while locked; VAD result is recorded (None = squelch-only)."""
        with self.lock:
            if self.state != "locked" or not self.cfg.use_vad or self.cfg.mode not in VOICE_MODES:
                return None
            self._abuf.append(np.asarray(audio, np.float32))
            self._alen += len(audio)
            if self._alen < self.audio_rate * 0.3:
                return None
            v = vad(np.concatenate(self._abuf), self.audio_rate)
            self._abuf, self._alen = [], 0
            if v is True:
                self.voice_seen = self.clock()
                self.entry.voice = True
            elif v is False and self.entry.voice is None:
                self.entry.voice = False
            return v

    def _release(self, why):
        self._abuf, self._alen = [], 0
        if self.locked is not None:
            self.stats["released_" + why.replace(" ", "_")] += 1
            self._resume_after = self.locked
        self.locked = None

    def _release_and_next(self, why):
        self._release(why)
        self.state = "scanning"
        return self._goto_next()

    def _goto_next(self):
        if not self.chunks:
            return None
        self.ci = (self.ci + 1) % len(self.chunks)
        if self.ci == 0:
            self.stats["passes"] += 1
        self.settle = SETTLE_BLOCKS
        return self.chunks[self.ci][0]

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "locked": self.locked, "chunks": len(self.chunks), "chunk": self.ci,
                    "channels": sum(len(c) for _, c in self.chunks),
                    "hold_left": max(0.0, self.cfg.hold_s - (self.clock() - self.last_active))
                    if self.state == "locked" else None,
                    "paused_from": self.paused_from, "ignore_cap_hz": self.ignores.cap_hz,
                    "history": list(self.history.items), "ignores": self.ignores.review(),
                    "stats": dict(self.stats)}
