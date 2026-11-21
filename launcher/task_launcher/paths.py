# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Filesystem locations (XDG). Nothing here is privileged; the launcher never writes outside $HOME
except its single-instance socket in $XDG_RUNTIME_DIR."""

import os
import tempfile
from pathlib import Path

SYSTEM_APPS_DIRS = (Path("/usr/share/task-launcher/apps.d"), Path("/etc/task-launcher/apps.d"))
SYSTEM_BRANDING_FILE = Path("/etc/task-launcher/branding.toml")


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "task-launcher"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "task-launcher"


def user_apps_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "task-launcher" / "apps.d"


def autostart_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart"


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value and os.path.isdir(value):
        return Path(value)
    return Path(tempfile.gettempdir())


def instance_name() -> str:
    run = os.environ.get("XDG_RUNTIME_DIR")
    if run and os.path.isdir(run):
        return str(Path(run) / "task-launcher.instance")
    return str(Path(tempfile.gettempdir()) / f"task-launcher-{os.getuid()}.instance")
