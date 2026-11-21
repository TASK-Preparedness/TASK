# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Reduced-motion preference.

Launcher setting ``reduce_motion``: ``system`` (default) | ``on`` | ``off``. With ``system`` the
launcher honours, where readable, the desktop hints that animations are disabled:

1. ``gtk-enable-animations`` in ~/.config/gtk-4.0/settings.ini or ~/.config/gtk-3.0/settings.ini
   (plain file read);
2. ``gsettings get org.gnome.desktop.interface enable-animations`` — only if /usr/bin/gsettings exists,
   run once in a worker thread with a 2 s timeout (never on the GUI thread).

No hint found = animations on.
"""

import configparser
import os
import subprocess
from pathlib import Path

GSETTINGS = "/usr/bin/gsettings"


def gtk_ini_hint(config_home=None):
    """False if a GTK settings.ini disables animations, True if it enables them, None if unset."""
    base = Path(config_home or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for sub in ("gtk-4.0", "gtk-3.0"):
        path = base / sub / "settings.ini"
        try:
            if path.stat().st_size > 65536:
                continue
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(path.read_text(encoding="utf-8"))
        except (OSError, configparser.Error, UnicodeDecodeError):
            continue
        if cp.has_option("Settings", "gtk-enable-animations"):
            v = cp.get("Settings", "gtk-enable-animations").strip().lower()
            return v not in ("0", "false", "no")
    return None


def gsettings_hint(gsettings=GSETTINGS, timeout=2.0):
    if not (os.path.isfile(gsettings) and os.access(gsettings, os.X_OK)):
        return None
    try:
        out = subprocess.run([gsettings, "get", "org.gnome.desktop.interface", "enable-animations"],
                             capture_output=True, text=True, timeout=timeout, shell=False, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    v = out.stdout.strip()
    return {"true": True, "false": False}.get(v)


def system_animations_enabled():
    """Blocking (gsettings subprocess); call from a worker. None = no hint."""
    hint = gtk_ini_hint()
    if hint is not None:
        return hint
    return gsettings_hint()


def effective_reduce(setting: str, system_enabled) -> bool:
    if setting == "on":
        return True
    if setting == "off":
        return False
    return system_enabled is False
