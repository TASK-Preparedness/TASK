# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Fake pyserial ListPortInfo objects and helpers to build fake /dev/serial trees."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from task_mesh.domain.models import Classification, PortCandidate


@dataclass
class FakePortInfo:
    device: str
    vid: Optional[int] = None
    pid: Optional[int] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    product: Optional[str] = None
    description: str = "n/a"
    hwid: str = "n/a"
    location: Optional[str] = None
    interface: Optional[str] = None


HELTEC = dict(vid=0x10C4, pid=0xEA60, serial_number="0001", manufacturer="Silicon Labs",
              product="CP2102 USB to UART Bridge Controller")
ESP32S3 = dict(vid=0x303A, pid=0x1001, serial_number="F4:12:FA:00:11:22", manufacturer="Espressif",
               product="USB JTAG/serial debug unit")
UBLOX = dict(vid=0x1546, pid=0x01A8, serial_number=None, manufacturer="u-blox AG", product="u-blox GNSS receiver")
FTDI = dict(vid=0x0403, pid=0x6001, serial_number="A50285BI", manufacturer="FTDI", product="FT232R USB UART")


def make_tree(root: Path, links: dict[str, dict[str, str]]) -> Path:
    """links = {"by-id": {name: target_dev}, "by-path": {...}} -> creates symlinks under root."""
    for kind, entries in links.items():
        d = root / kind
        d.mkdir(parents=True, exist_ok=True)
        for name, target in entries.items():
            os.symlink(target, d / name)
    return root


def candidate(device: str, link: Optional[str] = None, likely: bool = True) -> PortCandidate:
    return PortCandidate(
        device=device, by_id=link, vid=0x10C4, pid=0xEA60, serial_number="0001", manufacturer="Silicon Labs",
        product="CP2102 USB to UART Bridge Controller",
        classification=Classification.LIKELY if likely else Classification.POSSIBLE,
        open_path=link or device,
    )
