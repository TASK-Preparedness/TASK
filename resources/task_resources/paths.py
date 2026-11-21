# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Per-user locations (XDG). Nothing here is created during import of this module."""

import os
from pathlib import Path

APP = "task-resources"


def _xdg(var, default):
    v = os.environ.get(var, "")
    return Path(v) if v.startswith("/") else Path.home() / default


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def private_dir(path: Path) -> Path:
    """Create path (and parents) with mode 0700 for the leaf; returns it."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def fallback_managed_root() -> Path:
    return data_dir() / "managed"


def state_dir() -> Path:
    """Small private state (WebEngine crash guard, 0.2.4)."""
    return _xdg("XDG_STATE_HOME", ".local/state") / "task-resources"
