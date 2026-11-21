# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Declared backend status per platform for each abstraction.

This table is documentation-as-code: the installer, the Windows build and
WINDOWS.md read it, so nothing is presented as working before it is.
Status values: "verified" (tested on real hardware/OS), "implemented"
(code exists, simulated tests only), "planned", "unavailable".
"""
from __future__ import annotations

UNVERIFIED = "UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST"

CAPABILITIES: dict[str, dict[str, str]] = {
    # area: {platform: status}
    "paths":            {"linux": "verified", "windows": "implemented"},
    "serial_discovery": {"linux": "implemented", "windows": "implemented"},
    "process":          {"linux": "verified", "windows": "implemented"},
    "logging":          {"linux": "verified", "windows": "planned"},
    "config":           {"linux": "verified", "windows": "planned"},
    "notifications":    {"linux": "verified", "windows": "planned"},
    "background_services": {"linux": "verified", "windows": "planned"},
    "usb_discovery":    {"linux": "implemented", "windows": "planned"},
    "bluetooth":        {"linux": "implemented", "windows": "planned"},
    "gps":              {"linux": "verified", "windows": "planned"},
    "sdr":              {"linux": "verified", "windows": "planned"},
    "permissions":      {"linux": "verified", "windows": "planned"},
}


def status(area: str, platform: str) -> str:
    return CAPABILITIES.get(area, {}).get(platform, "unavailable")
