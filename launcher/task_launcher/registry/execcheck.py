# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Executable safety checks shared by manifests and desktop entries.

An executable is launchable only if it is an absolute path to an existing regular file that is
executable by us, the file is not world-writable, and no directory on its real path is
world-writable (a sticky world-writable directory such as /tmp is refused too).
"""

import os
import stat
from pathlib import Path

OK = "ok"


def check_executable(path: str):
    """Return (status, reason). status: ok | missing | unsafe | not-executable | invalid."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return "invalid", "executable path is empty or invalid"
    if not os.path.isabs(path):
        return "invalid", f"executable must be an absolute path: {path!r}"
    try:
        real = os.path.realpath(path)
        st = os.stat(real)
    except OSError:
        return "missing", f"executable not found: {path}"
    if not stat.S_ISREG(st.st_mode):
        return "invalid", f"not a regular file: {path}"
    if st.st_mode & stat.S_IWOTH:
        return "unsafe", f"refused: executable is world-writable: {real}"
    parent = Path(real).parent
    for d in [parent, *parent.parents]:
        try:
            dst = os.stat(d)
        except OSError:
            return "missing", f"cannot inspect directory {d}"
        if dst.st_mode & stat.S_IWOTH:
            return "unsafe", f"refused: executable is in a world-writable directory: {d}"
    if not os.access(real, os.X_OK):
        return "not-executable", f"not executable: {path}"
    return OK, ""


def find_in_path(name: str, path_env: str = None):
    """Absolute path of ``name`` on PATH (like which), only for names without a slash."""
    if not name or "/" in name or "\x00" in name:
        return None
    for d in (path_env if path_env is not None else os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")).split(":"):
        if not d or not os.path.isabs(d):
            continue  # never resolve relative PATH entries (e.g. "." or "")
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
