# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only host detection.

Everything here reads files (/proc, /sys, /etc/os-release, the dpkg status
database) or runs read-only query commands (``dpkg --print-architecture``)
via argv lists. It never opens /dev nodes, never talks to a radio, GPS or
SDR, never changes device ownership and never needs root. ``root`` lets tests
point it at a fake filesystem.
"""
from __future__ import annotations

import os
import platform as _platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

# USB IDs we can recognise WITHOUT opening the device. Generic USB-UART bridges
# are reported as "possible" matches only: the same chip is used by many boards.
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


@dataclass
class UsbDevice:
    usb_id: str
    product: str | None
    kind: str | None
    description: str | None


@dataclass
class HostFacts:
    model: str | None                 # device-tree model string, None if not a Pi / unknown
    pi_family: str | None             # "pi5", "pi4", "pi400", "pi3", "zero2w", ... or None
    kernel_machine: str               # uname -m (aarch64, armv7l, x86_64 ...)
    dpkg_arch: str | None             # userland architecture (arm64, armhf ...)
    os_id: str | None
    os_version_id: str | None
    os_codename: str | None
    os_pretty: str | None
    mem_total_mib: int | None
    disk_free_mib: int | None
    desktop: str | None
    session_type: str | None
    graphical: bool
    python_version: str
    usb: list[UsbDevice] = field(default_factory=list)
    bluetooth_adapters: list[str] = field(default_factory=list)
    installed_packages: dict[str, str] = field(default_factory=dict)  # name -> version
    simulated: bool = False

    @property
    def installed_task_packages(self) -> dict[str, str]:
        return {k: v for k, v in self.installed_packages.items()
                if k.startswith("task-") or k == "python3-task-comms"}


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


_FAMILY = [
    (r"Raspberry Pi 5\b", "pi5"), (r"Raspberry Pi 500\b", "pi500"),
    (r"Raspberry Pi Compute Module 5", "cm5"),
    (r"Raspberry Pi 4\b", "pi4"), (r"Raspberry Pi 400\b", "pi400"),
    (r"Raspberry Pi Compute Module 4", "cm4"),
    (r"Raspberry Pi 3\b", "pi3"), (r"Raspberry Pi Compute Module 3", "cm3"),
    (r"Raspberry Pi Zero 2", "zero2w"), (r"Raspberry Pi Zero", "zero"),
    (r"Raspberry Pi 2\b", "pi2"), (r"Raspberry Pi (Model [AB]|Compute Module\b)", "pi1"),
]


def pi_family(model: str | None) -> str | None:
    if not model:
        return None
    for pat, fam in _FAMILY:
        if re.search(pat, model):
            return fam
    return "pi-unknown" if model.startswith("Raspberry Pi") else None


def parse_os_release(text: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if not re.fullmatch(r"[A-Z0-9_]+", k):
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def parse_meminfo(text: str | None) -> int | None:
    m = re.search(r"^MemTotal:\s+(\d+)\s+kB", text or "", re.M)
    return int(m.group(1)) // 1024 if m else None


def parse_dpkg_status(text: str | None) -> dict[str, str]:
    pkgs: dict[str, str] = {}
    for stanza in (text or "").split("\n\n"):
        fields = {}
        for line in stanza.splitlines():
            if line and not line[0].isspace() and ":" in line:
                k, v = line.split(":", 1)
                fields[k] = v.strip()
        if fields.get("Status", "").endswith(" installed") and "Package" in fields:
            pkgs[fields["Package"]] = fields.get("Version", "")
    return pkgs


def scan_usb(root: Path) -> list[UsbDevice]:
    out: list[UsbDevice] = []
    base = root / "sys/bus/usb/devices"
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        vid, pid = _read(d / "idVendor"), _read(d / "idProduct")
        if not vid or not pid:
            continue
        uid = f"{vid.strip().lower()}:{pid.strip().lower()}"
        kind, desc = KNOWN_USB.get(uid, (None, None))
        prod = _read(d / "product")
        out.append(UsbDevice(uid, prod.strip() if prod else None, kind, desc))
    return out


Runner = Callable[[Sequence[str]], str | None]


def default_runner(argv: Sequence[str]) -> str | None:
    if not shutil.which(argv[0]):
        return None
    try:
        r = subprocess.run(list(argv), capture_output=True, text=True, timeout=10, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def detect(root: str | os.PathLike = "/", env: dict | None = None, runner: Runner | None = None,
           kernel_machine: str | None = None) -> HostFacts:
    root = Path(root)
    env = dict(os.environ) if env is None else env
    simulated = root != Path("/")
    runner = runner or default_runner
    model = _read(root / "proc/device-tree/model") or _read(root / "sys/firmware/devicetree/base/model")
    model = model.replace("\x00", "").strip() if model else None
    osr = parse_os_release(_read(root / "etc/os-release") or _read(root / "usr/lib/os-release"))
    try:
        st = os.statvfs(root)
        free = st.f_bavail * st.f_frsize // (1024 * 1024)
    except OSError:
        free = None
    bt = sorted(p.name for p in (root / "sys/class/bluetooth").glob("hci*")) if (root / "sys/class/bluetooth").is_dir() else []
    return HostFacts(
        model=model, pi_family=pi_family(model),
        kernel_machine=kernel_machine or _platform.machine(),
        dpkg_arch=runner(["dpkg", "--print-architecture"]),
        os_id=osr.get("ID"), os_version_id=osr.get("VERSION_ID"),
        os_codename=osr.get("VERSION_CODENAME"), os_pretty=osr.get("PRETTY_NAME"),
        mem_total_mib=parse_meminfo(_read(root / "proc/meminfo")),
        disk_free_mib=free,
        desktop=env.get("XDG_CURRENT_DESKTOP") or env.get("DESKTOP_SESSION"),
        session_type=env.get("XDG_SESSION_TYPE"),
        graphical=bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")),
        python_version=_platform.python_version(),
        usb=scan_usb(root), bluetooth_adapters=bt,
        installed_packages=parse_dpkg_status(_read(root / "var/lib/dpkg/status")),
        simulated=simulated)
