# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Discrete-time model of the 0.2.3 GUI push path when IQ is NOT lost: 3072 samples arrive every 64 ms (one block),
the 30 ms GUI tick writes everything queued; QIODevice accepts min(free, len); the return value is ignored."""
import json
def run(sink_bytes, jitter_ms=0, secs=20):
    dt = 0.001; t = 0; level = 0.0; next_blk = 0.064; next_tick = 0.030; q = 0; drop = 0; played = 0; need_total = 0; gaps = 0; starving = False
    while t < secs:
        t += dt
        need = 48000*4*dt; take = min(level, need); level -= take; played += take; need_total += need
        if take < need*0.99:
            if not starving: gaps += 1
            starving = True
        else: starving = False
        if t >= next_blk: q += 3072*4; next_blk += 0.064
        if t >= next_tick:
            acc = min(q, sink_bytes - level); level += acc; drop += q - acc; q = 0; next_tick += 0.030 + jitter_ms/1000
    return {"sink_bytes": sink_bytes, "gui_jitter_ms": jitter_ms, "played_fraction": round(played/need_total, 3), "gaps_per_s": round(gaps/secs, 2), "discarded_fraction": round(drop/(played+drop+level), 3)}
for b in (4096, 8192, 12288, 19200, 38400):
    for j in (0, 20):
        print(json.dumps(run(b, j)))
