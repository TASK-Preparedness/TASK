#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4G M1: build task-sdr 0.2.0 (SDR Studio) only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_release as br  # noqa: E402

REPO = br.REPO
if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    p = br.Pkg("task-sdr", "0.2.0",
               f"{br.PY}, {br.QT}, python3-pyside6.qtmultimedia (>= 6.8), python3-numpy, python3-scipy, "
               "librtlsdr0 (>= 2.0.2), python3-task-comms (>= 0.3.0)",
               "T.A.S.K. SDR Studio (receive only)\n"
               " Native RTL-SDR (librtlsdr; RTL-SDR Blog V4 aware) receiver with digit tuner, spectrum and\n"
               " waterfall, AM/NFM/WFM/USB/LSB/CW, bandwidth, gain/AGC, squelch, S-meter, bookmarks and\n"
               " presets. SoapySDR is optional. No transmit capability.", "hamradio",
               {"Suggests": "python3-soapysdr, soapysdr0.8-module-rtlsdr, rtl-sdr"})
    p.tree(REPO / "sdr/task_sdr", "usr/lib/task-sdr/task_sdr")
    p.bin("usr/bin/task-sdr", "task_sdr.app:main", "/usr/lib/task-sdr")
    p.file(REPO / "sdr/packaging/task-sdr.desktop", "usr/share/applications/task-sdr.desktop")
    p.docs(br.changelog("task-sdr", "0.2.0", [
        "Phase 4G M1: SDR Studio. Native librtlsdr backend (ctypes), RTL-SDR Blog V4 range 0.5-1766 MHz,",
        "pluggable receive-only backends (Soapy optional; Airspy/SDRplay/HackRF/Lime/Pluto/UHD/network stubs),",
        "safe discovery, digit tuner, CW mode, bandwidth, audio AGC, S-meter, bookmarks, bounded worker queues.",
        "python3-soapysdr is no longer a dependency (now Suggests)."]),
        [REPO / "sdr/README.md", REPO / "docs/phase4g/SDR-STUDIO.md"])
    print(p.build(out).name)
