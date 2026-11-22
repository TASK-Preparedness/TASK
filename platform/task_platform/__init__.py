# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. platform abstraction layer (EXPERIMENTAL, 0.2.0.dev0).

Shared, dependency-free interfaces that let T.A.S.K. modules run on Linux (the
verified platform) and, later, Windows 11 x64 (NOT YET BUILT OR TESTED).

Rules that every backend here follows:
* discovery is read-only: nothing in this package opens a serial port, a
  Bluetooth socket, an SDR or a GPS device, and nothing takes device ownership;
* nothing is enabled to start automatically;
* nothing runs through a shell (argv lists only, no shell=True);
* nothing transmits on any radio.
"""
from __future__ import annotations

import sys

__version__ = "0.2.0.dev0"

LINUX = "linux"
WINDOWS = "windows"
MACOS = "macos"
OTHER = "other"


def current_platform(sys_platform: str | None = None) -> str:
    p = sys.platform if sys_platform is None else sys_platform
    if p.startswith("linux"):
        return LINUX
    if p in ("win32", "cygwin"):
        return WINDOWS
    if p == "darwin":
        return MACOS
    return OTHER
