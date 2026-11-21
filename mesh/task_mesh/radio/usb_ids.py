# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""USB IDs used to classify serial ports. Data, not logic.

LIKELY: USB-serial bridges / MCUs used on common Meshtastic boards (auto-connect if it is the only one).
NEVER:  debug probes / instruments (same list as meshtastic.util.blacklistVids) plus GNSS receivers,
        which must never be opened as a radio (gpsd owns them from v0.6).
"""

from __future__ import annotations

from typing import Optional

# (vid, pid) pairs; pid None = any product of that vendor
LIKELY_IDS: dict[tuple[int, Optional[int]], str] = {
    (0x10C4, 0xEA60): "Silicon Labs CP210x (Heltec V3, LILYGO T-Beam, ...)",
    (0x1A86, 0x55D4): "WCH CH9102 (LILYGO T-Beam v1.2, ...)",
    (0x1A86, 0x7523): "WCH CH340",
    (0x303A, None): "Espressif native USB (ESP32-S3/C3: LILYGO T-Deck, Heltec V3 native, ...)",
    (0x239A, None): "Adafruit/RAK nRF52 (RAK4631, ...)",
    (0x2886, None): "Seeed Studio",
}

NEVER_VIDS: dict[int, str] = {
    0x1366: "SEGGER J-Link",
    0x0483: "STMicroelectronics ST-LINK",
    0x1915: "Nordic Semiconductor PPK2",
    0x0925: "Lakeview/Saleae logic analyzer",
    0x04B4: "Cypress (Hantek oscilloscope)",
    0x1546: "u-blox GNSS receiver",
}


def is_never(vid: Optional[int]) -> bool:
    return vid is not None and vid in NEVER_VIDS


def is_likely(vid: Optional[int], pid: Optional[int]) -> bool:
    if vid is None:
        return False
    return (vid, pid) in LIKELY_IDS or (vid, None) in LIKELY_IDS
