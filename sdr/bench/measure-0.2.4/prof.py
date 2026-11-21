# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import sys,time; sys.path.insert(0,sys.argv[1])
import numpy as np
from task_sdr.dsp import Demodulator, Spectrum, StatefulFir
from scipy import signal
iq=(np.exp(1j*np.linspace(0,9e3,65536))).astype(np.complex64)
d=Demodulator("WFM",1_024_000)
def t(f,n=20):
    ts=[];
    for _ in range(n):
        a=time.perf_counter(); f(); ts.append(time.perf_counter()-a)
    return round(1e3*np.mean(ts),2)
x=d.chan(iq)
print("chan_fir", t(lambda:d.chan(iq)))
print("fm", t(lambda:d._fm(x)))
a=np.real(d._fm(x))
print("audio_lp(complex)", t(lambda:d.audio_lp(a.astype(complex))))
print("deemph", t(lambda:signal.lfilter(d.de_b,d.de_a,a,zi=d.de_zi)))
print("resamp", t(lambda:d._to_audio(a)))
s=Spectrum(); print("spectrum", t(lambda:s.compute(iq)))
print("total", t(lambda:d.process(iq)))
