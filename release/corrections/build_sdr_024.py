#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4G corrections: build task-sdr 0.2.4 (audio-pipeline repair) only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_release as br  # noqa: E402

REPO = br.REPO
if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    p = br.Pkg("task-sdr", "0.2.4",
               f"{br.PY}, {br.QT}, python3-pyside6.qtmultimedia (>= 6.8), python3-numpy, python3-scipy, "
               "librtlsdr0 (>= 2.0.2), python3-task-comms (>= 0.3.0)",
               "T.A.S.K. SDR Studio (receive only)\n"
               " Native RTL-SDR (librtlsdr; RTL-SDR Blog V4 aware) receiver with digit tuner, spectrum and\n"
               " waterfall, AM/NFM/WFM/USB/LSB/CW, bandwidth, gain/AGC, squelch, S-meter, bookmarks and\n"
               " presets, a Smart Scanner, and a frequency-overlay framework (format only; no frequency data is\n"
               " included). SoapySDR is optional. No transmit capability.", "hamradio",
               {"Suggests": "python3-soapysdr, soapysdr0.8-module-rtlsdr, rtl-sdr"})
    p.tree(REPO / "sdr/task_sdr", "usr/lib/task-sdr/task_sdr")
    p.bin("usr/bin/task-sdr", "task_sdr.app:main", "/usr/lib/task-sdr")
    p.file(REPO / "sdr/packaging/task-sdr.desktop", "usr/share/applications/task-sdr.desktop")
    # overlay FORMAT only. No dataset is shipped; the example fixtures stay in sdr/tests (never packaged)
    p.file(REPO / "sdr/overlays/schema/overlay-v1.schema.json", "usr/share/task-sdr/schema/overlay-v1.schema.json")
    p.docs(br.changelog("task-sdr", "0.2.4", [
        "Audio-pipeline repair (quiet, choppy WFM). IQ reading and DSP now run in separate threads, so the dongle is",
        "read back to back (0.2.3 read and demodulated serially and lost IQ while demodulating). Audio goes through a",
        "bounded, thread-safe ring (150 ms target, 500 ms cap) to a pull-mode QAudioSink that is independent of the",
        "GUI timer; partial writes (push mode) are retried, never discarded; under/overruns are counted. WFM",
        "discriminator scaled to 75 kHz deviation; AGC rewritten (RMS target, attack/release, no per-block gain",
        "steps, peak limiter); overlap-save channel FIR (about 3.5x less DSP time); resampler continuity fixed. Sink",
        "restart after device loss. Optional --diag-log JSON diagnostics. Receive only; hardware UNVERIFIED."]),
        [REPO / "sdr/README.md", REPO / "docs/phase4g/SDR-STUDIO.md", REPO / "docs/phase4g-022/SMART-SCANNER.md",
         REPO / "docs/phase4g-m3/OVERLAY-FRAMEWORK.md", REPO / "docs/phase4g-m3/FREQUENCY-AUDIT.md",
         REPO / "docs/phase4g-024/AUDIO-PIPELINE.md"])
    print(p.build(out).name)
