# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import sys; sys.path.insert(0,sys.argv[1])
import numpy as np
from task_sdr.dsp import Demodulator
FS=1_024_000; n=FS
t=np.arange(n)/FS; iq=np.exp(1j*(75e3/1000)*np.sin(2*np.pi*1000*t)).astype(np.complex64)
for mode in ("WFM","NFM","AM","USB","CW"):
    ref=Demodulator(mode,FS).process(iq)
    r=np.random.default_rng(3); d=Demodulator(mode,FS); outs=[]; i=0
    while i<n:
        k=int(r.integers(1,40000)); outs.append(d.process(iq[i:i+k])); i+=k
    o=np.concatenate(outs); m=min(len(o),len(ref))
    print(mode, len(ref), len(o), float(np.max(np.abs(o[:m]-ref[:m]))))
