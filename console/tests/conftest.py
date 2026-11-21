# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-console tests: pytest-qt, offscreen, against the real task-core Core (PHASE-2.md 17.6).

The golden fixture (TEST DATA) comes from the task-core test helpers: u-blox 7,
RTL-SDR Blog V4 and CP2102, with gps.primary -> dev_74a462923d20f21e alias "smoke".
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CONSOLE = Path(__file__).resolve().parents[1]
REPO = CONSOLE.parent
for path in (str(CONSOLE), str(REPO), str(REPO / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest  # noqa: E402

from p2fixtures import p2env  # noqa: E402,F401  (fixture re-export)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Each test gets its own HOME and XDG directories; nothing touches the real profile."""
    home = tmp_path / "home"
    runtime = tmp_path / "run"
    home.mkdir()
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return home


@pytest.fixture
def console(qtbot):
    """console(socket_path, size=(1920, 1080), connect=True, **controller kwargs) -> Console handle."""
    from helpers import Console

    made = []

    def make(socket_path, size=(1920, 1080), connect=True, **kwargs):
        handle = Console(qtbot, socket_path, size=size, **kwargs)
        made.append(handle)
        if connect:
            handle.wait_connected()
        return handle

    yield make
    for handle in made:
        handle.close()
