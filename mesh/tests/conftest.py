# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Shared fixtures: offscreen Qt, temporary XDG directories, logging reset, fake radios."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# python3-task-comms (Phase 4C shared library); in the deb it is a Depends: in /usr/lib/python3/dist-packages
COMMS = Path(os.environ.get("TASK_COMMS_SRC", "/workspace/task-phase4c-wt/comms"))
if COMMS.is_dir() and str(COMMS) not in sys.path:
    sys.path.append(str(COMMS))

import pytest  # noqa: E402


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    env = {}
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                     ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                     ("XDG_RUNTIME_DIR", "run")):
        p = tmp_path / sub
        p.mkdir(mode=0o700, exist_ok=True)
        monkeypatch.setenv(var, str(p))
        env[var] = str(p)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    env["HOME"] = str(tmp_path / "home")
    return env


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    from task_mesh.core import logging_setup

    root = logging.getLogger()
    for h in list(logging_setup._installed):
        root.removeHandler(h)
        h.close()
    logging_setup._installed.clear()


@pytest.fixture
def state_store(tmp_path):
    from task_mesh.core.config import StateStore

    return StateStore(tmp_path / "state.json")


@pytest.fixture
def pty_radio(tmp_path):
    from tests.fakes.pty_radio import PtyRadio

    r = PtyRadio(tmp_path / "by-id")
    r.plug()
    yield r
    r.unplug()


@pytest.fixture(autouse=True)
def _private_runtime_dir(tmp_path, monkeypatch):
    """Status cards and device locks of the app under test go to a temporary runtime dir."""
    run = tmp_path / "xdg-runtime"
    run.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    return run
