# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only serial-port discovery.

Linux: walks /sys/class/tty and /dev/serial/by-id symlinks. It never opens a
/dev node, never toggles DTR/RTS (which would reset an ESP32 such as a Heltec
V3) and never changes ownership. Device ownership stays with task-core and the
owning service (e.g. task-mesh-service, gpsd).

Windows: uses pyserial's ``serial.tools.list_ports`` when installed, which
reads the device registry and does not open ports. UNVERIFIED on Windows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import WINDOWS, current_platform


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    by_id: str | None = None
    vid: int | None = None
    pid: int | None = None
    manufacturer: str | None = None
    product: str | None = None

    @property
    def usb_id(self) -> str | None:
        if self.vid is None or self.pid is None:
            return None
        return f"{self.vid:04x}:{self.pid:04x}"


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _usb_parent(dev: Path) -> Path | None:
    # walk up the resolved sysfs device path until a dir with idVendor appears
    try:
        cur = dev.resolve()
    except OSError:
        return None
    for _ in range(8):
        if (cur / "idVendor").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _hex(v: str | None) -> int | None:
    try:
        return int(v, 16) if v else None
    except ValueError:
        return None


def list_linux(root: str | os.PathLike = "/") -> list[SerialPortInfo]:
    root = Path(root)
    by_id: dict[str, str] = {}
    byid_dir = root / "dev/serial/by-id"
    if byid_dir.is_dir():
        for link in sorted(byid_dir.iterdir()):
            try:
                target = os.readlink(link)
            except OSError:
                continue
            by_id[Path(target).name] = str(Path("/dev/serial/by-id") / link.name)
    out: list[SerialPortInfo] = []
    tty = root / "sys/class/tty"
    if not tty.is_dir():
        return out
    for entry in sorted(tty.iterdir()):
        name = entry.name
        if not (name.startswith("ttyUSB") or name.startswith("ttyACM") or name.startswith("ttyAMA")):
            continue
        dev = entry / "device"
        usb = _usb_parent(dev) if dev.exists() else None
        out.append(SerialPortInfo(
            device=f"/dev/{name}", by_id=by_id.get(name),
            vid=_hex(_read(usb / "idVendor")) if usb else None,
            pid=_hex(_read(usb / "idProduct")) if usb else None,
            manufacturer=_read(usb / "manufacturer") if usb else None,
            product=_read(usb / "product") if usb else None))
    return out


def list_windows(comports=None) -> list[SerialPortInfo]:
    """COM ports from pyserial's registry/SetupAPI enumeration (ports are NOT opened).
    ``comports`` lets tests inject a fake enumerator; on Windows it defaults to pyserial's."""
    if comports is None:
        try:
            from serial.tools import list_ports  # pyserial
        except ImportError:
            return []
        comports = list_ports.comports
    out = []
    for p in comports():
        out.append(SerialPortInfo(device=getattr(p, "device", None) or getattr(p, "name", ""),
                                  vid=getattr(p, "vid", None), pid=getattr(p, "pid", None),
                                  manufacturer=getattr(p, "manufacturer", None), product=getattr(p, "product", None),
                                  by_id=getattr(p, "serial_number", None) and f"USB serial {p.serial_number}"))
    return sorted(out, key=lambda i: (len(i.device), i.device))


def list_serial_ports(root: str | os.PathLike = "/", platform: str | None = None, comports=None) -> list[SerialPortInfo]:
    if (platform or current_platform()) == WINDOWS:
        return list_windows(comports)
    return list_linux(root)
