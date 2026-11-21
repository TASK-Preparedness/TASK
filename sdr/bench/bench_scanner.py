#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Smart Scanner benchmark on synthetic IQ (no hardware). Drives the real Engine.scan_step path (PSD, demod,
spectrum, VAD) as fast as the CPU allows, and reports:
  * CPU: CPU seconds per second of received IQ (1.0 = one full core needed in real time)
  * memory: tracemalloc peak + process max RSS
  * scan rate: dwells/s and channels measured/s (receive time), full-band revisit interval
  * missed transmissions: of N random transmissions, how many produced a history entry; misses are split
    into "receiver busy on another channel" (inherent to one receiver) and "missed while sweeping".
Usage: bench_scanner.py [--seconds 300] [--count 60] [--latency-ms 0] [--json out.json]"""

import argparse
import json
import os
import platform
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_sdr import prefs as P  # noqa: E402
from task_sdr.backends import RTL_BLOG_V4  # noqa: E402
from task_sdr.engine import Engine  # noqa: E402
from task_sdr.scanner import ScanConfig, Scanner  # noqa: E402
from task_sdr.sim_band import BandDevice, random_traffic  # noqa: E402


def run(seconds=300.0, count=60, latency_ms=0.0, start=144_000_000, stop=148_000_000, step=12_500, seed=3):
    rate = 1_024_000
    cfg = ScanConfig(start_hz=start, stop_hz=stop, step_hz=step, mode="NFM", channel_bw_hz=12_500)
    chans = cfg.channel_list(RTL_BLOG_V4)
    traffic = random_traffic(chans, seconds, count, seed=seed)
    d = BandDevice(traffic, rate=rate, retune_latency_samples=int(rate * latency_ms / 1000))
    tmp = tempfile.mkdtemp()
    e = Engine(P.Prefs(), lambda: d, status_dir=tmp + "/s", claim_dir=tmp + "/c")
    e.profile, e.dev = RTL_BLOG_V4, d
    d.configure(rate, P.Prefs().freq_hz)
    sc = Scanner(rate, RTL_BLOG_V4, clock=lambda: d.t)     # device time incl. retune latency
    e.prefs.agc = True
    tracemalloc.start()
    c0, w0 = time.process_time(), time.perf_counter()
    e.start_scan(sc, cfg)
    while d.t < seconds:
        e.scan_step(sc, d.read(sc.block_size()))
        e.take_audio()                       # 0.2.4: drain the AudioRing (was a queue of blocks)
    cpu, wall = time.process_time() - c0, time.perf_counter() - w0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    hist = sc.history.items
    tol = step // 2
    locks = sorted((h.t_rx, h.t_rx + h.duration_s + cfg.hold_s, h.freq_hz) for h in hist)
    found, busy, swept = 0, 0, 0
    latency = []
    for t in traffic:
        hit = [h for h in hist if abs(h.freq_hz - t["freq"]) <= tol and t["start"] - 0.05 <= h.t_rx <= t["start"] + t["dur"]]
        if hit:
            found += 1
            latency.append(min(h.t_rx for h in hit) - t["start"])
            continue
        # was the (single) receiver locked on another channel while this transmission was on the air?
        if any(a < t["start"] + t["dur"] and b > t["start"] and abs(f - t["freq"]) > tol for a, b, f in locks):
            busy += 1
        else:
            swept += 1
    st = dict(sc.stats)
    latency.sort()
    return {
        "host": f"{platform.machine()} {platform.processor() or ''} {os.cpu_count()} cpus, python {platform.python_version()}",
        "receive_seconds": round(d.t, 2), "wall_seconds": round(wall, 2), "cpu_seconds": round(cpu, 2),
        "cpu_per_rx_second": round(cpu / d.t, 3),
        "realtime_headroom_x": round(d.t / cpu, 1),
        "tracemalloc_peak_mib": round(peak / 2**20, 2),
        "max_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "channels": len(chans), "chunks": len(sc.chunks), "retune_latency_ms": latency_ms,
        "dwells_per_rx_s": round(st.get("dwells", 0) / d.t, 1),
        "channels_measured_per_rx_s": round(st.get("channels_measured", 0) / d.t, 0),
        "full_band_passes": st.get("passes", 0),
        "revisit_ms_idle": round(1000 * len(sc.chunks) * 2 * (sc.block_size() / rate + latency_ms / 1000), 1),
        "traffic_airtime_fraction": round(sum(t["dur"] for t in traffic) / seconds, 2),
        "transmissions": len(traffic), "detected": found, "missed_receiver_busy": busy, "missed_while_sweeping": swept,
        "detect_latency_ms_median": round(1000 * latency[len(latency) // 2], 1) if latency else None,
        "detect_latency_ms_max": round(1000 * latency[-1], 1) if latency else None,
        "carrier_timeout_releases": st.get("released_carrier_timeout", 0),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--latency-ms", type=float, default=0.0)
    ap.add_argument("--json")
    a = ap.parse_args()
    r = run(a.seconds, a.count, a.latency_ms)
    print(json.dumps(r, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1))
