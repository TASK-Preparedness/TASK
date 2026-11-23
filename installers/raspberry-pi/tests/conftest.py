# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Fake /proc, /sys, /etc and dpkg roots for simulation-only installer tests."""
import pytest

from task_installer.detect import detect

TRIXIE = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nVERSION_ID="13"\nVERSION_CODENAME=trixie\nID=debian\n'
BOOKWORM = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\nID=debian\n'
DEBIAN_13_6 = ('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nVERSION_ID="13"\nVERSION="13 (trixie)"\n'
               'VERSION_CODENAME=trixie\nDEBIAN_VERSION_FULL=13.6\nID=debian\nHOME_URL="https://www.debian.org/"\n'
               'SUPPORT_URL="https://www.debian.org/support"\nBUG_REPORT_URL="https://bugs.debian.org/"\n')
UBUNTU = 'PRETTY_NAME="Ubuntu 24.04 LTS"\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\nID=ubuntu\n'

MODELS = {
    "pi5": "Raspberry Pi 5 Model B Rev 1.0",
    "pi4": "Raspberry Pi 4 Model B Rev 1.4",
    "pi3": "Raspberry Pi 3 Model B Plus Rev 1.3",
    "zero2w": "Raspberry Pi Zero 2 W Rev 1.0",
    "zero": "Raspberry Pi Zero W Rev 1.1",
    "pi1": "Raspberry Pi Model B Rev 2",
}
MEM = {"pi5": 8_000_000, "pi4": 4_000_000, "pi3": 950_000, "zero2w": 430_000, "zero": 430_000, "pi1": 430_000}


def make_root(tmp_path, model="pi5", os_release=TRIXIE, usb=(), bt=True, dpkg_status=""):
    import tempfile
    r = __import__("pathlib").Path(tempfile.mkdtemp(prefix="root-", dir=tmp_path))
    (r / "proc/device-tree").mkdir(parents=True)
    if model:
        (r / "proc/device-tree/model").write_text(MODELS.get(model, model) + "\x00")
    (r / "proc/meminfo").write_text(f"MemTotal:       {MEM.get(model, 2_000_000)} kB\n")
    (r / "etc").mkdir()
    (r / "etc/os-release").write_text(os_release)
    for i, (vid, pid, prod) in enumerate(usb):
        d = r / f"sys/bus/usb/devices/1-{i + 1}"
        d.mkdir(parents=True)
        (d / "idVendor").write_text(vid + "\n")
        (d / "idProduct").write_text(pid + "\n")
        (d / "product").write_text(prod + "\n")
    if bt:
        (r / "sys/class/bluetooth/hci0").mkdir(parents=True)
    (r / "var/lib/dpkg").mkdir(parents=True)
    (r / "var/lib/dpkg/status").write_text(dpkg_status)
    return r


def facts_for(tmp_path, model="pi5", arch="arm64", machine="aarch64", graphical=True, **kw):
    root = make_root(tmp_path, model, **kw)
    env = {"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "LXDE-pi", "XDG_SESSION_TYPE": "x11"} if graphical else {}
    return detect(root, env=env, runner=lambda argv: arch, kernel_machine=machine)


@pytest.fixture
def facts(tmp_path):
    return lambda *a, **k: facts_for(tmp_path, *a, **k)
