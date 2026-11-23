# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Filesystem locations (XDG). Nothing here is privileged; the launcher never writes outside $HOME
except its single-instance socket in $XDG_RUNTIME_DIR."""

import os
import re
import sys
import tempfile
from pathlib import Path

WINDOWS = sys.platform == "win32"   # EXPERIMENTAL Windows support: UNVERIFIED on real Windows


def _bundle_dir() -> Path:
    """Folder of a frozen (PyInstaller) build; the package's data directory otherwise."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent / "data"))


if WINDOWS:
    SYSTEM_APPS_DIRS = (_bundle_dir() / "apps.d",
                        Path(os.environ.get("PROGRAMDATA") or "C:/ProgramData") / "TASK" / "task-launcher" / "apps.d")
    SYSTEM_BRANDING_FILE = Path(os.environ.get("PROGRAMDATA") or "C:/ProgramData") / "TASK" / "task-launcher" / "branding.toml"
else:
    SYSTEM_APPS_DIRS = (Path("/usr/share/task-launcher/apps.d"), Path("/etc/task-launcher/apps.d"))
    SYSTEM_BRANDING_FILE = Path("/etc/task-launcher/branding.toml")

# On Windows the XDG names map to %APPDATA% (roaming config) and %LOCALAPPDATA% (state/data) under "TASK",
# the same layout as task_platform.paths.
_WIN_BASE = {"XDG_CONFIG_HOME": ("APPDATA", "AppData/Roaming"), "XDG_STATE_HOME": ("LOCALAPPDATA", "AppData/Local"),
             "XDG_DATA_HOME": ("LOCALAPPDATA", "AppData/Local"), "XDG_CACHE_HOME": ("LOCALAPPDATA", "AppData/Local")}


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    if value and os.path.isabs(value):
        return Path(value)
    if WINDOWS and var in _WIN_BASE:
        env, fallback = _WIN_BASE[var]
        base = os.environ.get(env)
        return (Path(base) if base else Path.home() / fallback) / "TASK"
    return Path.home() / default


def user_tag() -> str:
    """Per-user suffix for temporary names: the uid on POSIX, a sanitised user name on Windows."""
    if hasattr(os, "getuid"):
        return str(os.getuid())
    import getpass
    return re.sub(r"[^A-Za-z0-9_.-]", "_", getpass.getuser()) or "user"


def is_privileged() -> bool:
    """True when running as root (POSIX) or as an elevated administrator (Windows)."""
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


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
    return str(Path(tempfile.gettempdir()) / f"task-launcher-{user_tag()}.instance")
