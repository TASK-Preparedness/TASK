# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""End-to-end timing MODEL (not hardware): old 0.2.3 engine vs new 0.2.4 engine.
Device model: samples are produced in real time at 1.024 MS/s; when no read is in progress the device can hold
FIFO_SAMPLES, anything beyond is lost (rtlsdr_read_sync semantics: only an in-flight bulk transfer receives data).
DSP cost model: each 65536-sample block costs DSP_MS (Pi estimate from the user's 42-48 % single-core report).
Sink model (old): push QIODevice with SINK_BYTES buffer drained at 48 kHz*4 B; write() accepts min(free, len),
the 0.2.3 code ignores the return value. GUI tick 30 ms. Sink model (new): Qt pulls 10 ms every 10 ms from the ring."""
import sys, time, threading, json, tempfile
which, root = sys.argv[1], sys.argv[2]
DSP_MS = float(sys.argv[3]); FIFO = int(sys.argv[4]); SINK_BYTES = int(sys.argv[5]); SECS = float(sys.argv[6])
sys.path.insert(0, root); sys.path.insert(0, "/workspace/task-sdr-024-wt/comms")
import numpy as np
import task_sdr.dsp as dsp
from task_sdr import prefs as P
from task_sdr.engine import Engine
RATE = 1_024_000

class LossyDev:
    profile = None
    def __init__(self):
        self.t0 = None; self.pos = 0; self.lost = 0; self.reads = 0; self.last_end = None
    def configure(self, *a): pass
    def set_frequency(self, hz): pass
    def set_gain(self, g): pass
    def start(self): self.t0 = time.monotonic(); self.last_end = self.t0
    def close(self): pass
    def read(self, n):
        now = time.monotonic()
        avail_since_last = (now - self.last_end) * RATE
        if avail_since_last > FIFO:                      # gap longer than the FIFO -> samples lost
            lost = int(avail_since_last - FIFO); self.lost += lost; self.pos += lost
        produced = int((now - self.t0) * RATE)
        start = self.pos
        need_until = start + n
        wait = (need_until - produced) / RATE
        if wait > 0: time.sleep(wait)
        self.pos += n; self.reads += 1; self.last_end = time.monotonic()
        t = (np.arange(start, start + n)) / RATE
        return np.exp(1j * 75.0 * np.sin(2 * np.pi * 1000 * t)).astype(np.complex64)

orig = dsp.Demodulator.process
def slow(self, iq):
    t = time.perf_counter(); out = orig(self, iq)
    target = DSP_MS / 1000 * len(iq) / 65536
    rem = target - (time.perf_counter() - t)
    if rem > 0: time.sleep(rem)
    return out
dsp.Demodulator.process = slow
import task_sdr.engine as E; E.Demodulator.process = slow

dev = LossyDev()
tmp = tempfile.mkdtemp()
pr = P.Prefs(); pr.freq_hz = 95_500_000; pr.mode = "WFM"; pr.sample_rate = RATE; pr.agc = True; pr.volume = 1.0
e = Engine(pr, lambda: dev, status_dir=tmp + "/s", claim_dir=tmp + "/c")
played_real = 0; played_total = 0; gaps = 0; dropped_bytes = 0; stop = threading.Event()
lock = threading.Lock()
if which == "old":
    # sink: buffer level in bytes, drained continuously
    level = [0.0]; last = [time.monotonic()]; starving = [False]
    def drain():
        global played_real, played_total, gaps
        now = time.monotonic(); need = (now - last[0]) * 48000 * 4; last[0] = now
        take = min(level[0], need); level[0] -= take
        played_real += take / 4; played_total += need / 4
        if take < need * 0.99 and need > 0:
            if not starving[0]: gaps += 1
            starving[0] = True
        else: starving[0] = False
    def gui():
        global dropped_bytes
        while not stop.is_set():
            time.sleep(0.030)
            with lock:
                drain()
                a = e.take_audio()
                b = len(a) * 4
                acc = min(b, SINK_BYTES - level[0]); level[0] += acc; dropped_bytes += b - acc
    th = threading.Thread(target=gui); 
else:
    def gui():
        global played_real, played_total, gaps
        prev_under = 0
        while not stop.is_set():
            time.sleep(0.010)
            e.ring.pull(480, pad=True)
        return
    th = threading.Thread(target=gui)
e.start(); th.start(); time.sleep(SECS); stop.set(); th.join(); e.stop()
res = {"engine": which, "dsp_ms_per_64ms_block": DSP_MS, "fifo_samples": FIFO, "secs": SECS,
       "iq_captured_fraction": round(1 - dev.lost / max(1, dev.pos), 3), "device_lost_samples": dev.lost}
if which == "old":
    res.update({"sink_bytes": SINK_BYTES, "audio_played_fraction": round(played_real / max(1, played_total), 3),
                "audible_gaps": gaps, "audio_bytes_discarded_by_ignored_partial_write": int(dropped_bytes),
                "engine_dropped_audio_blocks": e.dropped_audio})
else:
    st = e.ring.stats(); d = e.diagnostics()
    res.update({"audio_played_fraction": round(st["accepted"] / max(1, st["accepted"] + st["underrun_samples"]), 3),
                "underrun_events": st["underrun_events"], "underrun_samples": st["underrun_samples"],
                "overrun_events": st["overrun_events"], "iq_dropped_blocks": d["iq_dropped_blocks"]})
print(json.dumps(res))
