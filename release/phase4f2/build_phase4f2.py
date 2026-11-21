#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F.2: build task-launcher 0.3.4 only (task-mesh 0.3.1, comms 0.3.1 and task-resources are unchanged)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_release as br  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    br.run([sys.executable, str(REPO / "launcher/packaging/build_deb.py"), str(out), "--epoch", str(br.EPOCH)],
           stdout=subprocess.DEVNULL)
    print("task-launcher_0.3.4_all.deb")
