# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""XDG paths. The package owns nothing here: maps, jobs and waypoints are user data and survive
upgrades and removal of the package."""

import os
from pathlib import Path

SYSTEM_SOURCES_DIR = Path("/usr/share/task-maps/sources.d")
BUNDLED_SOURCES_DIR = Path(__file__).resolve().parent / "data" / "sources.d"


def _xdg(var: str, default: str) -> Path:
    v = os.environ.get(var, "")
    return Path(v) if v.startswith("/") else Path.home() / default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "task-maps"


def default_data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "task-maps"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "task-maps"


def user_sources_dir() -> Path:
    return config_dir() / "sources.d"


def system_sources_dir() -> Path:
    return SYSTEM_SOURCES_DIR if SYSTEM_SOURCES_DIR.is_dir() else BUNDLED_SOURCES_DIR


def ensure_dir(p: Path, mode=0o700) -> Path:
    p.mkdir(parents=True, exist_ok=True, mode=mode)
    return p
