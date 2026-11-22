# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Device discovery abstraction (read-only, both platforms).

Combines serial-port enumeration with a USB-ID table to *suggest* what a port might be. A generic
USB-UART bridge is only ever a "possible" match: the same chip sits on many boards. Nothing here opens
a port, toggles DTR/RTS (which resets ESP32 boards such as the Heltec V3), probes a radio, or takes
ownership: on the Pi, task-core and the owning service (task-mesh-service, gpsd) keep ownership.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .serial_ports import SerialPortInfo, list_serial_ports

# same identifications as the Raspberry Pi installer (installers/raspberry-pi/task_installer/detect.py)
KNOWN_USB: dict[str, tuple[str, str]] = {
    "10c4:ea60": ("usb-serial", "Silicon Labs CP210x USB-UART (used by Heltec V3 and others) — possible Meshtastic/MeshCore node"),
    "1a86:55d4": ("usb-serial", "WCH CH9102 USB-UART (used by some T-Beam boards) — possible Meshtastic/MeshCore node"),
    "1a86:7523": ("usb-serial", "WCH CH340 USB-UART (used by some T-Beam boards and others) — possible Meshtastic/MeshCore node"),
    "303a:1001": ("usb-serial", "Espressif ESP32-S3 native USB (used by T-Deck, Heltec V3.2 variants and others) — possible Meshtastic/MeshCore node"),
    "0bda:2838": ("sdr", "Realtek RTL2838 DVB-T / RTL-SDR (e.g. RTL-SDR Blog V4)"),
    "0bda:2832": ("sdr", "Realtek RTL2832U / RTL-SDR"),
    "1546:01a7": ("gps", "u-blox 7 GNSS receiver"),
    "1546:01a8": ("gps", "u-blox 8 GNSS receiver"),
    "1546:01a9": ("gps", "u-blox 9 GNSS receiver"),
    "067b:2303": ("gps", "Prolific PL2303 USB-serial (common in USB GPS pucks) — possible GPS"),
}


@dataclass(frozen=True)
class DiscoveredDevice:
    port: SerialPortInfo
    kind: str | None            # "usb-serial", "gps", "sdr" or None (unknown)
    description: str | None
    certainty: str              # "possible" (shared chip) or "likely" (device-specific ID) or "unknown"


def classify(port: SerialPortInfo) -> DiscoveredDevice:
    kind, desc = KNOWN_USB.get(port.usb_id or "", (None, None))
    if kind is None:
        return DiscoveredDevice(port, None, None, "unknown")
    certainty = "possible" if kind == "usb-serial" or "possible" in (desc or "") else "likely"
    return DiscoveredDevice(port, kind, desc, certainty)


def discover(root: str | os.PathLike = "/", platform: str | None = None, comports=None) -> list[DiscoveredDevice]:
    return [classify(p) for p in list_serial_ports(root, platform, comports)]
