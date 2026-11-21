# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Receiver engine (0.2.4): a READER thread keeps the device read continuously, a DSP thread demodulates,
computes the spectrum and pushes audio into a bounded AudioRing that the Qt audio sink pulls from.
Holds a DeviceClaim so the other T.A.S.K. apps see who owns the SDR; releases everything on stop/close.
Unplug: reports 'disconnected' and retries opening every 2 s until stopped.

Why two threads (0.2.4): 0.2.3 did read(65536) -> demodulate -> read in ONE thread. rtlsdr_read_sync only has a USB
transfer in flight while it is called, so every millisecond of DSP was a millisecond in which the dongle had nowhere
to put samples. Now reads are back to back; IQ that cannot be processed in time is dropped (oldest first) and COUNTED.
Receive only."""

import collections
import json
import os
import threading
import time

import numpy as np

from task_comms.ownership import DeviceClaim
from task_comms.status import StatusWriter

from task_sdr.audioring import AudioRing
from task_sdr.device import DeviceBusy, DeviceError
from task_sdr.backends import SIMULATED, RangeError
from task_sdr.dsp import (Agc, Demodulator, Spectrum, Squelch, audio_levels, channel_power_dbfs, dbfs,
                          power_dbfs)

BLOCK = 65_536            # DSP block (spectrum/waterfall/squelch cadence unchanged from 0.2.3: ~64 ms at 1.024 Msps)
READ_BLOCK = 16_384       # device read size (~16 ms): reads are back to back in the reader thread
IQ_QUEUE = 48             # reader->DSP queue in READ_BLOCKs (~0.77 s); full -> oldest dropped and counted
REOPEN_S = 2.0
FRAME_QUEUE = 3           # spectrum frames kept for the GUI (oldest dropped): the worker never waits on Qt
AUDIO_QUEUE = 24          # kept for compatibility (0.2.3 block count); the audio FIFO is now AudioRing (latency-bounded)
DIAG_ENV = "TASK_SDR_DIAG_LOG"


class _Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.t0 = time.monotonic()
        self.iq_blocks = self.iq_samples = self.iq_dropped_blocks = self.iq_dropped_samples = 0
        self.stale_blocks = self.read_errors = self.short_reads = 0
        self.dsp_blocks = 0
        self.dsp_time_sum = self.dsp_time_max = 0.0
        self.dsp_over_budget = 0
        self.clipped_samples = 0
        self.rms = self.peak = self.demod_rms = 0.0
        self.rate_window = collections.deque(maxlen=64)   # (t, samples)


class Engine:
    def __init__(self, prefs, opener, audio=None, status_dir=None, claim_dir=None, on_update=None,
                 device_key="rtlsdr-0", ring=None, diag_log=None):
        self.prefs, self.opener, self.audio = prefs, opener, audio
        self.on_update = on_update or (lambda kind, data: None)
        self.status = StatusWriter("task-sdr", status_dir)
        self.claim = DeviceClaim(device_key, "task-sdr", claim_dir)
        self.spectrum = Spectrum()
        self.dev = None
        self.state = "stopped"
        self.error = None
        self.level = None
        self._stop = threading.Event()
        self._thread = None
        self._dsp_thread = None
        self._diag_thread = None
        self._lock = threading.RLock()
        self.demod = None
        self.squelch = Squelch(prefs.squelch_dbfs)
        self.profile = SIMULATED              # replaced by the opened device's profile
        self.frames = collections.deque(maxlen=FRAME_QUEUE)
        self.ring = ring or AudioRing()
        self.audio_q = self.ring              # 0.2.3 name (qsize()/empty() still work; units are samples now)
        self.agc = Agc()
        self.chan_level = None
        self.scanner = None            # task_sdr.scanner.Scanner while scanning (worker-driven)
        self.squelch_open = True
        self.gen = 0                   # bumped on every retune: IQ read before it is stale and never demodulated
        self._iq = collections.deque()
        self._iq_cv = threading.Condition()
        self._acc = []
        self._acc_n = 0
        self.stats = _Stats()
        self.sink_info = None          # the Qt audio output (stats only; it pulls from self.ring itself)
        self.diag_log = diag_log if diag_log is not None else os.environ.get(DIAG_ENV) or None

    @property
    def dropped_audio(self):
        """0.2.3 name: audio overrun events (oldest audio dropped to bound latency)."""
        return self.ring.overrun_events

    # -------------------------------------------------------------- control
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.claim.acquire():
            self._set("busy", f"SDR claimed by {self.claim.holder() or 'another T.A.S.K. app'}")
            return
        self._stop.clear()
        self.stats.reset()
        self._flush_iq()
        self.ring.clear()
        self._thread = threading.Thread(target=self._run, name="task-sdr-rx", daemon=True)
        self._dsp_thread = threading.Thread(target=self._dsp_run, name="task-sdr-dsp", daemon=True)
        self._thread.start()
        self._dsp_thread.start()
        if self.diag_log:
            self._diag_thread = threading.Thread(target=self._diag_run, name="task-sdr-diag", daemon=True)
            self._diag_thread.start()

    def stop(self):
        self._stop.set()
        with self._iq_cv:
            self._iq_cv.notify_all()
        for t in (self._thread, self._dsp_thread, self._diag_thread):
            if t:
                t.join(timeout=3)
        self._thread = self._dsp_thread = self._diag_thread = None
        self._close_dev()
        self._flush_iq()
        self.ring.clear()
        self.claim.release()
        self._set("stopped", None)

    def retune_checked(self, freq_hz):
        """Validate (strict integer Hz, this receiver's range) and retune; returns the Hz value."""
        freq_hz = self.profile.check(freq_hz)
        self.retune(freq_hz=freq_hz)
        return freq_hz

    def retune(self, freq_hz=None, mode=None, gain_db="keep", ppm=None, squelch="keep", bandwidth="keep"):
        """Raises RangeError (and changes nothing) if freq_hz is outside the device's verified range."""
        with self._lock:
            if freq_hz is not None:
                freq_hz = self.profile.check(freq_hz)        # strict integer Hz + this receiver's range
            if bandwidth != "keep":
                self.prefs.bandwidth_hz = None if bandwidth is None else int(bandwidth)
            if freq_hz is not None:
                self.prefs.freq_hz = int(freq_hz)
            if mode is not None:
                self.prefs.mode = mode
            if gain_db != "keep":
                self.prefs.gain_db = gain_db
            if ppm is not None:
                self.prefs.ppm = int(ppm)
            if squelch != "keep":
                self.prefs.squelch_dbfs = squelch
                self.squelch = Squelch(squelch)
            self.prefs.validate()
            if self.dev is not None:
                self.dev.set_frequency(self.prefs.freq_hz)
                self.dev.set_gain(self.prefs.gain_db)
            self.gen += 1
            self.demod = self._demod()

    def _demod(self):
        return Demodulator(self.prefs.mode, self.prefs.sample_rate, bandwidth=self.prefs.bandwidth_hz)

    # -------------------------------------------------------------- worker
    def _open(self):
        dev = self.opener()
        self.profile = getattr(dev, "profile", None) or self.profile
        if not self.profile.accepts(self.prefs.freq_hz):
            dev.close()
            raise RangeError(f"saved frequency {self.prefs.freq_hz / 1e6:.6f} MHz is outside the "
                             f"{self.profile.name} range ({self.profile.min_hz / 1e6:g}–{self.profile.max_hz / 1e6:g}"
                             " MHz); tune inside the range")
        dev.configure(self.prefs.sample_rate, self.prefs.freq_hz, self.prefs.gain_db, self.prefs.ppm)
        dev.start()
        self.dev = dev
        self.demod = self._demod()
        self._set("connected", None)

    def _close_dev(self):
        d, self.dev = self.dev, None
        if d is not None:
            d.close()

    def _run(self):
        """READER thread: open/reopen the device and read back to back; never demodulates."""
        while not self._stop.is_set():
            if self.dev is None:
                try:
                    self._open()
                except DeviceBusy as exc:
                    self._set("busy", str(exc))
                    self._stop.wait(REOPEN_S)
                    continue
                except RangeError as exc:
                    self._set("error", str(exc))
                    self._stop.wait(REOPEN_S)
                    continue
                except DeviceError as exc:
                    self._set("disconnected", str(exc))
                    self._stop.wait(REOPEN_S)
                    continue
            sc = self.scanner
            scanning = sc is not None and sc.state != "idle"
            want = sc.block_size() if scanning else READ_BLOCK
            gen = self.gen
            dev = self.dev
            if dev is None:
                continue
            try:
                iq = dev.read(want)
            except DeviceError as exc:
                with self.stats.lock:
                    self.stats.read_errors += 1
                self._close_dev()
                self._flush_iq()
                self._set("disconnected", f"SDR unplugged or failed: {exc}")
                continue
            if len(iq) == 0:
                continue
            self._enqueue(iq, gen, scanning, want)

    def _enqueue(self, iq, gen, scanning, want):
        st = self.stats
        now = time.monotonic()
        with st.lock:
            st.iq_blocks += 1
            st.iq_samples += len(iq)
            if len(iq) < want:
                st.short_reads += 1
            st.rate_window.append((now, len(iq)))
        with self._iq_cv:
            while len(self._iq) >= IQ_QUEUE:
                old = self._iq.popleft()
                with st.lock:
                    st.iq_dropped_blocks += 1
                    st.iq_dropped_samples += len(old[0])
            self._iq.append((iq, gen, scanning))
            self._iq_cv.notify()

    def _flush_iq(self):
        with self._iq_cv:
            self._iq.clear()
        self._acc, self._acc_n = [], 0

    def _dsp_run(self):
        """DSP thread: demodulate in order; audio -> AudioRing (thread-safe), spectrum -> frames deque."""
        while not self._stop.is_set():
            with self._iq_cv:
                while not self._iq and not self._stop.is_set():
                    self._iq_cv.wait(0.2)
                if self._stop.is_set():
                    return
                iq, gen, scanning = self._iq.popleft()
            self.handle_block(iq, gen, scanning)

    def handle_block(self, iq, gen=None, scanning=None):
        """Process one reader block (also used directly by tests)."""
        if gen is not None and gen != self.gen:
            with self.stats.lock:
                self.stats.stale_blocks += 1          # read before a retune: never demodulated (expected, counted)
            self._acc, self._acc_n = [], 0
            return
        sc = self.scanner
        if scanning is None:
            scanning = sc is not None and sc.state != "idle"
        t = time.perf_counter()
        if scanning and sc is not None and sc.state != "idle":
            self._acc, self._acc_n = [], 0
            self.scan_step(sc, iq)
            n = len(iq)
        else:
            self._acc.append(iq)
            self._acc_n += len(iq)
            if self._acc_n < BLOCK:
                return
            blk = np.concatenate(self._acc) if len(self._acc) > 1 else self._acc[0]
            self._acc, self._acc_n = [], 0
            self.process(blk)
            n = len(blk)
        dt = time.perf_counter() - t
        budget = n / float(self.prefs.sample_rate or 1)
        st = self.stats
        with st.lock:
            st.dsp_blocks += 1
            st.dsp_time_sum += dt
            st.dsp_time_max = max(st.dsp_time_max, dt)
            if dt > budget:
                st.dsp_over_budget += 1

    # ------------------------------------------------------------- scanner
    def start_scan(self, scanner, cfg):
        """Start the Smart Scanner (receive only). Sets the scan mode/bandwidth, tunes the first chunk."""
        with self._lock:
            scanner.profile = self.profile
            centre = scanner.start(cfg)
            self.prefs.mode, self.prefs.bandwidth_hz = cfg.mode, int(cfg.channel_bw_hz)
            self.demod = self._demod()
            self.scanner = scanner
            self._tune_raw(centre)

    def stop_scan(self):
        with self._lock:
            if self.scanner is not None:
                self.scanner.stop()
            self.scanner = None

    def request_tune(self, hz):
        """UI-thread retune for the scanner (resume/skip/ignore); same range check as retune()."""
        if hz is None:
            return
        with self._lock:
            try:
                self._tune_raw(hz)
            except RangeError:
                return
            self.demod = self._demod()

    def _tune_raw(self, hz):
        hz = self.profile.check(hz)
        self.prefs.freq_hz = hz
        if self.dev is not None:
            self.dev.set_frequency(int(hz))
        self.gen += 1

    def scan_step(self, sc, iq):
        act = sc.feed(iq)
        if act["tune"] is not None:
            with self._lock:
                try:
                    self._tune_raw(act["tune"])
                except RangeError:
                    sc.stop()
                    self._set("error", "scan channel outside the receiver range")
                    return None
                self.demod = self._demod()          # fresh filter state for the new channel
        if not act["listen"]:
            db = self.spectrum.compute(iq)
            self.frames.append({"spectrum": db, "level": power_dbfs(iq), "chan": None, "squelch_open": False,
                                "t": time.monotonic(), "scan": sc.snapshot()})
            return None
        audio = None
        for pre in act["prebuffer"]:            # start of the transmission (captured while sweeping)
            a = self.demod.process(pre)
            sc.on_audio(a)
            self._emit(a)
        if not act["prebuffer"] and act["tune"] is None:
            audio = self.process(iq, scan=sc)
        return audio

    def _emit(self, audio):
        if self.prefs.agc:
            audio = self.agc(audio)
        self._output(audio)

    def _output(self, audio):
        """Volume, one counted hard limit at +-1, level metering, then the audio FIFO (or a legacy sink)."""
        audio = np.asarray(audio, np.float32) * float(self.prefs.volume)
        over = int(np.count_nonzero(np.abs(audio) > 1.0))
        if over:
            audio = np.clip(audio, -1.0, 1.0)
        audio = audio.astype(np.float32)
        rms, peak = audio_levels(audio)
        with self.stats.lock:
            self.stats.clipped_samples += over
            if len(audio):
                self.stats.rms, self.stats.peak = rms, peak
        if self.audio is not None:
            self.audio.write(audio)
        else:
            self._put_audio(audio)
        return audio

    def process(self, iq, scan=None):
        with self._lock:
            self.level = power_dbfs(iq)
            db = self.spectrum.compute(iq)
            bw = self.demod.bandwidth
            self.chan_level = channel_power_dbfs(db, self.prefs.sample_rate / len(db), 0, bw)
            audio = self.demod.process(iq)
            with self.stats.lock:
                self.stats.demod_rms = audio_levels(audio)[0]
            if scan is not None:
                scan.on_audio(audio)
            self.squelch_open = self.squelch.open(self.chan_level)
            if self.prefs.agc:
                audio = self.agc(audio)
            if not self.squelch_open:
                audio = np.zeros_like(audio)
        audio = self._output(audio)
        self.frames.append({"spectrum": db, "level": self.level, "chan": self.chan_level,
                            "squelch_open": self.squelch_open, "t": time.monotonic(),
                            "scan": scan.snapshot() if scan is not None else None})
        return audio

    def _put_audio(self, audio):
        self.ring.push(audio)                 # bounded; overruns drop the OLDEST audio and are counted

    def take_frame(self):
        """Newest spectrum frame or None (GUI timer); older frames are discarded."""
        f = None
        while self.frames:
            f = self.frames.popleft()
        return f

    def take_audio(self):
        """Everything queued (legacy push consumers/tests). The Qt sink normally pulls from self.ring directly."""
        return self.ring.pull(self.ring.level(), pad=False)

    # ------------------------------------------------------------- diagnostics
    def diagnostics(self):
        st = self.stats
        with st.lock:
            now = time.monotonic()
            win = [(t, n) for t, n in st.rate_window if now - t <= 5.0]
            eff = None
            if len(win) >= 2 and win[-1][0] > win[0][0]:
                eff = sum(n for _, n in win[1:]) / (win[-1][0] - win[0][0])
            d = {"t": round(now - st.t0, 3), "state": self.state, "freq_hz": int(self.prefs.freq_hz),
                 "mode": self.prefs.mode, "sample_rate": int(self.prefs.sample_rate),
                 "iq_blocks": st.iq_blocks, "iq_samples": st.iq_samples,
                 "iq_dropped_blocks": st.iq_dropped_blocks, "iq_dropped_samples": st.iq_dropped_samples,
                 "iq_stale_blocks": st.stale_blocks, "iq_short_reads": st.short_reads, "read_errors": st.read_errors,
                 "iq_rate_measured": round(eff, 1) if eff else None,
                 "iq_rate_ratio": round(eff / self.prefs.sample_rate, 4) if eff else None,
                 "dsp_blocks": st.dsp_blocks,
                 "dsp_avg_ms": round(1e3 * st.dsp_time_sum / st.dsp_blocks, 3) if st.dsp_blocks else None,
                 "dsp_max_ms": round(1e3 * st.dsp_time_max, 3), "dsp_over_budget": st.dsp_over_budget,
                 "dsp_budget_ms": round(1e3 * BLOCK / self.prefs.sample_rate, 1),
                 "audio_rms_dbfs": round(dbfs(st.rms), 1), "audio_peak_dbfs": round(dbfs(st.peak), 1),
                 "demod_rms_dbfs": round(dbfs(st.demod_rms), 1), "clipped_samples": st.clipped_samples,
                 "agc_on": bool(self.prefs.agc), "agc_gain_db": round(self.agc.gain_db, 2),
                 "volume": float(self.prefs.volume), "squelch_open": bool(self.squelch_open)}
        with self._iq_cv:
            d["iq_queue"] = len(self._iq)
        a = self.ring.stats()
        d.update({"audio_" + k: v for k, v in a.items()})
        out = self.sink_info or self.audio
        if out is not None and hasattr(out, "stats"):
            d.update({"sink_" + k if not k.startswith("sink_") else k: v for k, v in out.stats().items()})
        d["latency_ms_est"] = round(d.get("audio_queue_ms", 0) + (d.get("sink_buffer_ms") or 0), 1)  # ring + sink
        return d

    def _diag_run(self):
        """Optional JSON-lines diagnostics (TASK_SDR_DIAG_LOG=/path or --diag-log): one line per second."""
        try:
            fh = open(self.diag_log, "a", encoding="utf-8")
        except OSError:
            return
        with fh:
            while not self._stop.wait(1.0):
                try:
                    fh.write(json.dumps(self.diagnostics()) + "\n")
                    fh.flush()
                except (OSError, ValueError):
                    return

    def _set(self, state, error):
        self.state, self.error = state, error
        try:
            self.status.write({"connected": "rx-only"}.get(state, state if state in
                              ("busy", "disconnected", "stopped") else "error"),
                              device="RTL-SDR", summary=f"{self.prefs.freq_hz / 1e6:.4f} MHz {self.prefs.mode}"
                              if state == "connected" else (error or state)[:120], last_error=error)
        except (OSError, ValueError):
            pass
        self.on_update("state", {"state": state, "error": error})

    def wait_state(self, state, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.state == state:
                return True
            time.sleep(0.01)
        return False
