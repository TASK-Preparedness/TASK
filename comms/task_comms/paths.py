# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""XDG locations used by the comms modules (never system paths)."""

import os
from pathlib import Path


def _xdg(var, default):
    v = os.environ.get(var)
    return Path(v) if v and os.path.isabs(v) else Path.home() / default


def runtime_dir() -> Path:
    v = os.environ.get("XDG_RUNTIME_DIR")
    return Path(v) if v and os.path.isabs(v) else Path("/tmp") / f"task-runtime-{os.getuid()}"


def status_dir() -> Path:
    return runtime_dir() / "task" / "status"


def data_dir(module: str) -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / module


def config_dir(module: str) -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / module


def state_dir(module: str) -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / module


def feeds_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "task-comms" / "feeds"


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path
