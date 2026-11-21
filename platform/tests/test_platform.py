# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import os
import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from task_platform import LINUX, WINDOWS, current_platform, paths, process, capabilities
from task_platform.serial_ports import list_linux, list_serial_ports


def test_current_platform():
    assert current_platform("linux") == LINUX
    assert current_platform("win32") == WINDOWS
    assert current_platform("darwin") == "macos"
    assert current_platform("sunos5") == "other"


def test_linux_paths_match_installed_layout():
    env = {"HOME": "/home/u"}
    assert paths.config_dir("task-aprs", env=env, platform=LINUX) == Path("/home/u/.config/task-aprs")
    assert paths.data_dir("task-mesh", env=env, platform=LINUX) == Path("/home/u/.local/share/task-mesh")
    assert paths.cache_dir("x", env=env, platform=LINUX) == Path("/home/u/.cache/x")


def test_linux_xdg_overrides_and_relative_ignored():
    env = {"HOME": "/home/u", "XDG_CONFIG_HOME": "/cfg", "XDG_DATA_HOME": "relative/bad"}
    assert paths.config_dir("a", env=env, platform=LINUX) == Path("/cfg/a")
    assert paths.data_dir("a", env=env, platform=LINUX) == Path("/home/u/.local/share/a")


def test_windows_paths():
    env = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    assert paths.config_dir("task-mesh", env=env, platform=WINDOWS) == PureWindowsPath(r"C:\Users\u\AppData\Roaming\TASK\task-mesh")
    assert paths.data_dir("task-mesh", env=env, platform=WINDOWS) == PureWindowsPath(r"C:\Users\u\AppData\Local\TASK\task-mesh\data")
    assert paths.log_dir("task-mesh", env=env, platform=WINDOWS).name == "logs"


def _fake_usb_tty(root: Path, tty: str, vid: str, pid: str, product: str, by_id: str | None):
    usb = root / "sys/devices/platform/usb1/1-1"
    (usb / f"1-1:1.0/{tty}").mkdir(parents=True)
    (usb / "idVendor").write_text(vid + "\n")
    (usb / "idProduct").write_text(pid + "\n")
    (usb / "product").write_text(product + "\n")
    cls = root / "sys/class/tty" / tty
    cls.mkdir(parents=True)
    os.symlink(usb / f"1-1:1.0/{tty}", cls / "device")
    if by_id:
        d = root / "dev/serial/by-id"
        d.mkdir(parents=True, exist_ok=True)
        os.symlink(f"../../{tty}", d / by_id)


def test_linux_serial_discovery_is_sysfs_only(tmp_path):
    _fake_usb_tty(tmp_path, "ttyUSB0", "10c4", "ea60", "CP2102 USB to UART Bridge Controller", "usb-Silicon_Labs_CP2102-if00-port0")
    (tmp_path / "sys/class/tty/tty0").mkdir(parents=True)  # virtual console ignored
    ports = list_serial_ports(tmp_path, platform=LINUX)
    assert len(ports) == 1
    p = ports[0]
    assert p.device == "/dev/ttyUSB0" and p.usb_id == "10c4:ea60"
    assert p.by_id == "/dev/serial/by-id/usb-Silicon_Labs_CP2102-if00-port0"


def test_linux_serial_discovery_empty_root(tmp_path):
    assert list_linux(tmp_path) == []


def test_spawn_rejects_shell_strings():
    with pytest.raises(TypeError):
        process.spawn_detached("echo hi")
    with pytest.raises(TypeError):
        process.spawn_detached([])


def test_popen_kwargs():
    lk = process.popen_kwargs(LINUX)
    assert lk["start_new_session"] is True and "creationflags" not in lk
    wk = process.popen_kwargs(WINDOWS)
    assert wk["creationflags"] == 0x208 and "start_new_session" not in wk
    assert "shell" not in lk and "shell" not in wk


def test_spawn_detached_runs_true():
    p = process.spawn_detached(["/bin/true"], platform=LINUX)
    assert p.wait(10) == 0


def test_capabilities_never_claim_windows_verified():
    for area, per in capabilities.CAPABILITIES.items():
        assert per.get("windows") != "verified", area
    assert capabilities.status("nope", "linux") == "unavailable"
