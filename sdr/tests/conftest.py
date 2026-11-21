# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "comms"))


@pytest.fixture(autouse=True)
def private_xdg(tmp_path, monkeypatch):
    for v in ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        d = tmp_path / v.lower()
        d.mkdir()
        monkeypatch.setenv(v, str(d))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
