# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Client-side Core socket discovery with the Phase 4C compatibility fallback.

Order: explicit --socket, then $TASK_CORE_SOCKET, then /run/task/core.sock if it
exists, then the legacy /run/rain/core.sock if it exists, else /run/task/core.sock.
"""

import os

TASK_SOCKET = "/run/task/core.sock"
LEGACY_SOCKET = "/run/rain/core.sock"


def resolve_socket(explicit=None, environ=None, exists=os.path.exists) -> str:
    environ = os.environ if environ is None else environ
    if explicit:
        return explicit
    env = environ.get("TASK_CORE_SOCKET")
    if env:
        return env
    for candidate in (TASK_SOCKET, LEGACY_SOCKET):
        if exists(candidate):
            return candidate
    return TASK_SOCKET
