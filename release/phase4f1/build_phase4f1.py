#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F.1: build task-mesh 0.3.1 only (comms 0.3.1 and launcher 0.3.3 are unchanged and not rebuilt)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase4f"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_phase4f as b4f  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    m = Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/task-mesh")
    print(b4f.mesh(out, m, "0.3.1", ("docs/phase4f", "docs/phase4f1")).name)
