#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4G corrections: build task-sdr 0.2.2 (SDR Studio + Smart Scanner) only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_release as br  # noqa: E402

REPO = br.REPO
if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    p = br.Pkg("task-sdr", "0.2.2",
               f"{br.PY}, {br.QT}, python3-pyside6.qtmultimedia (>= 6.8), python3-numpy, python3-scipy, "
               "librtlsdr0 (>= 2.0.2), python3-task-comms (>= 0.3.0)",
               "T.A.S.K. SDR Studio (receive only)\n"
               " Native RTL-SDR (librtlsdr; RTL-SDR Blog V4 aware) receiver with digit tuner, spectrum and\n"
               " waterfall, AM/NFM/WFM/USB/LSB/CW, bandwidth, gain/AGC, squelch, S-meter, bookmarks and\n"
               " presets, and a Smart Scanner. SoapySDR is optional. No transmit capability.", "hamradio",
               {"Suggests": "python3-soapysdr, soapysdr0.8-module-rtlsdr, rtl-sdr"})
    p.tree(REPO / "sdr/task_sdr", "usr/lib/task-sdr/task_sdr")
    p.bin("usr/bin/task-sdr", "task_sdr.app:main", "/usr/lib/task-sdr")
    p.file(REPO / "sdr/packaging/task-sdr.desktop", "usr/share/applications/task-sdr.desktop")
    p.docs(br.changelog("task-sdr", "0.2.2", [
        "Corrections before Pi testing. Ignores: per-entry tolerance, exact (0 Hz) by default, Hz/kHz, capped",
        "below half the channel spacing (never suppresses an adjacent channel); Session/Always labelled; review,",
        "edit, remove; 0.2.1 ignores migrate losslessly as exact Always entries and the legacy list is still",
        "written for rollback. History: retune/ignore/un-ignore/bookmark add-remove/pin via buttons and context",
        "menu; retune never touches recording. Silent-carrier release is optional and OFF by default. Scan/",
        "Pause/Resume/Skip follow one tested state table. Receive only; hardware UNVERIFIED."]),
        [REPO / "sdr/README.md", REPO / "docs/phase4g/SDR-STUDIO.md", REPO / "docs/phase4g-022/SMART-SCANNER.md"])
    print(p.build(out).name)
