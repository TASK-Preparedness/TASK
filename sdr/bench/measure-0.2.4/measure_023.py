# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Measurements against the UNMODIFIED 0.2.3 code (git HEAD 48ae110). Synthetic signals only, no hardware.
import sys, time, json, threading
sys.path.insert(0, sys.argv[1])
import numpy as np
from task_sdr.dsp import Demodulator, Agc
FS = 1_024_000; BLOCK = 65536
def wfm(n, dev=75e3, tone=1000.0, amp=1.0, snr_db=30, seed=1, t0=0):
    t = (np.arange(n) + t0) / FS
    ph = 2*np.pi*dev/ (2*np.pi*tone) * np.sin(2*np.pi*tone*t) * 2*np.pi / (2*np.pi)
    ph = (dev/tone) * np.sin(2*np.pi*tone*t)
    x = amp*np.exp(1j*ph)
    r = np.random.default_rng(seed); s = amp*10**(-snr_db/20)/np.sqrt(2)
    return (x + s*(r.standard_normal(n)+1j*r.standard_normal(n))).astype(np.complex64)
res = {}
for dev in (75e3, 22.5e3):  # full deviation and typical programme (~30%)
    d = Demodulator("WFM", FS); agc = Agc()
    outs=[]; gains=[]
    for k in range(30):
        a = d.process(wfm(BLOCK, dev=dev, t0=k*BLOCK))
        g = agc(a); gains.append(agc.gain); outs.append(g)
    raw = d.process(wfm(BLOCK, dev=dev, t0=31*BLOCK))
    o = np.concatenate(outs[10:])
    res[f"dev{int(dev)}"] = dict(demod_rms=float(np.sqrt(np.mean(raw**2))), demod_peak=float(np.max(abs(raw))),
        agc_out_rms=float(np.sqrt(np.mean(o**2))), agc_out_peak=float(np.max(abs(o))), agc_gain_final=gains[-1],
        agc_out_rms_dbfs=float(20*np.log10(np.sqrt(np.mean(o**2)))))
# AGC gain steps at block boundaries (one scalar gain per 64 ms block)
d = Demodulator("WFM", FS); agc = Agc(); steps=[]
for k in range(20):
    amp_dev = 75e3 if k % 4 < 2 else 15e3
    agc(d.process(wfm(BLOCK, dev=amp_dev, t0=k*BLOCK))); steps.append(round(agc.gain,3))
res["agc_gain_per_block_alt_dev"] = steps
# block processing time on this x86 box
d = Demodulator("WFM", FS); iq = wfm(BLOCK); ts=[]
for _ in range(20):
    t=time.perf_counter(); d.process(iq); ts.append(time.perf_counter()-t)
res["x86_demod_block_ms"] = dict(avg=1e3*float(np.mean(ts)), max=1e3*float(np.max(ts)), budget=1e3*BLOCK/FS)
# audio samples per block
res["audio_samples_per_block"] = int(len(Demodulator("WFM", FS).process(iq)))
print(json.dumps(res, indent=1))
