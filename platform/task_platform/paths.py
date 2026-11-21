# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Per-user configuration/data/cache/log locations.

Linux follows the XDG Base Directory spec (same locations the installed
modules use today, e.g. ~/.config/task-aprs, ~/.local/share/task-mesh).
Windows uses %APPDATA% (roaming config) and %LOCALAPPDATA% (data, cache, logs)
under a "TASK" folder. Windows paths are UNVERIFIED on real Windows.

All functions are pure: pass ``env``/``home``/``platform`` to test them.
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from . import LINUX, WINDOWS, current_platform

VENDOR_DIR = "TASK"


def _home(env, home):
    if home is not None:
        return Path(home)
    return Path(env.get("HOME") or os.path.expanduser("~"))


def _xdg(env, key, home, default_rel):
    v = env.get(key, "")
    # XDG spec: relative values are invalid and must be ignored
    if v and os.path.isabs(v):
        return Path(v)
    return _home(env, home) / default_rel


def _win_base(env, key, fallback_rel, home):
    v = env.get(key)
    if v:
        return PureWindowsPath(v)
    prof = env.get("USERPROFILE") or str(_home(env, home))
    return PureWindowsPath(prof) / fallback_rel


def config_dir(app: str, *, env=None, home=None, platform=None):
    env = os.environ if env is None else env
    plat = platform or current_platform()
    if plat == WINDOWS:
        return _win_base(env, "APPDATA", "AppData/Roaming", home) / VENDOR_DIR / app
    return _xdg(env, "XDG_CONFIG_HOME", home, ".config") / app


def data_dir(app: str, *, env=None, home=None, platform=None):
    env = os.environ if env is None else env
    plat = platform or current_platform()
    if plat == WINDOWS:
        return _win_base(env, "LOCALAPPDATA", "AppData/Local", home) / VENDOR_DIR / app / "data"
    return _xdg(env, "XDG_DATA_HOME", home, ".local/share") / app


def cache_dir(app: str, *, env=None, home=None, platform=None):
    env = os.environ if env is None else env
    plat = platform or current_platform()
    if plat == WINDOWS:
        return _win_base(env, "LOCALAPPDATA", "AppData/Local", home) / VENDOR_DIR / app / "cache"
    return _xdg(env, "XDG_CACHE_HOME", home, ".cache") / app


def log_dir(app: str, *, env=None, home=None, platform=None):
    env = os.environ if env is None else env
    plat = platform or current_platform()
    if plat == WINDOWS:
        return _win_base(env, "LOCALAPPDATA", "AppData/Local", home) / VENDOR_DIR / app / "logs"
    return _xdg(env, "XDG_STATE_HOME", home, ".local/state") / app / "log"


__all__ = ["config_dir", "data_dir", "cache_dir", "log_dir", "LINUX", "WINDOWS"]
