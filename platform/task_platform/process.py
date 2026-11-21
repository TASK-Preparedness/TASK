# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Detached process launching without a shell (argv list only)."""
from __future__ import annotations

import subprocess
from typing import Sequence

from . import WINDOWS, current_platform

# Windows creation flags (values from the Win32 API; constants exist only on Windows Python)
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def popen_kwargs(platform: str | None = None) -> dict:
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if (platform or current_platform()) == WINDOWS:
        kw["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return kw


def spawn_detached(argv: Sequence[str], platform: str | None = None) -> subprocess.Popen:
    if isinstance(argv, (str, bytes)) or not argv:
        raise TypeError("argv must be a non-empty list of strings (no shell strings)")
    return subprocess.Popen(list(argv), **popen_kwargs(platform))  # noqa: S603 - argv list, shell=False
