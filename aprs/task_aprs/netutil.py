# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Network guard: task-aprs talks only to a Direwolf on this machine."""

import ipaddress


def ensure_loopback(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    try:
        if ipaddress.ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise ValueError("Direwolf must be reached on loopback (127.0.0.1 / ::1) only")
