# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Milestone B platform additions. Windows code paths run here with injected fakes: NOT a Windows test."""
import hashlib
import os
import sys
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from task_platform import LINUX, WINDOWS, capabilities, config, discovery, resources
from task_platform.serial_ports import list_serial_ports

FAKE_COMPORTS = [SimpleNamespace(device="COM10", vid=0x1546, pid=0x01A7, manufacturer="u-blox AG", product="u-blox 7",
                                 serial_number=None),
                 SimpleNamespace(device="COM3", vid=0x10C4, pid=0xEA60, manufacturer="Silicon Labs", product="CP2102",
                                 serial_number="0001"),
                 SimpleNamespace(device="COM1", vid=None, pid=None, manufacturer=None, product=None, serial_number=None)]


def test_windows_serial_enumeration_with_injected_comports():
    ports = list_serial_ports(platform=WINDOWS, comports=lambda: FAKE_COMPORTS)
    assert [p.device for p in ports] == ["COM1", "COM3", "COM10"]
    assert ports[1].usb_id == "10c4:ea60" and ports[0].usb_id is None


def test_windows_without_pyserial_returns_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", None)
    monkeypatch.setitem(sys.modules, "serial.tools", None)
    assert list_serial_ports(platform=WINDOWS) == []


def test_discovery_classifies_without_opening(monkeypatch):
    opened = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError))
    devs = discovery.discover(platform=WINDOWS, comports=lambda: FAKE_COMPORTS)
    by = {d.port.device: d for d in devs}
    assert by["COM3"].kind == "usb-serial" and by["COM3"].certainty == "possible"
    assert by["COM10"].kind == "gps" and by["COM10"].certainty == "likely"
    assert by["COM1"].kind is None and by["COM1"].certainty == "unknown"
    assert opened == []


def test_discovery_table_matches_installer():
    inst = Path(__file__).resolve().parents[2] / "installers/raspberry-pi"
    sys.path.insert(0, str(inst))
    try:
        from task_installer.detect import KNOWN_USB
    finally:
        sys.path.remove(str(inst))
    assert KNOWN_USB == discovery.KNOWN_USB


def test_linux_discovery_from_sysfs(tmp_path):
    usb = tmp_path / "sys/devices/usb1/1-1"
    (usb / "1-1:1.0/ttyUSB0").mkdir(parents=True)
    (usb / "idVendor").write_text("10c4\n")
    (usb / "idProduct").write_text("ea60\n")
    (tmp_path / "sys/class/tty/ttyUSB0").mkdir(parents=True)
    os.symlink(usb / "1-1:1.0/ttyUSB0", tmp_path / "sys/class/tty/ttyUSB0/device")
    devs = discovery.discover(tmp_path, platform=LINUX)
    assert devs[0].port.device == "/dev/ttyUSB0" and devs[0].kind == "usb-serial"


def test_config_roundtrip_atomic(tmp_path):
    data = {"name": 'K"1\\x\n', "enabled": False, "n": 3, "f": 0.5, "list": ["a", 1],
            "radio": {"transmit": False, "path": "WIDE1-1,WIDE2-1"}}
    p = config.save(tmp_path / "a" / "config.toml", data)
    assert config.load(p) == data
    assert [f.name for f in p.parent.iterdir()] == ["config.toml"]   # no temp files left
    assert config.load(tmp_path / "missing.toml", {"x": 1}) == {"x": 1}
    with pytest.raises(TypeError):
        config.save(tmp_path / "b.toml", {"a": {"b": {"c": 1}}})
    with pytest.raises(ValueError):
        config.dumps({"x": float("nan")})


def test_config_file_paths_per_platform():
    assert config.config_file("task-aprs", env={"HOME": "/home/u"}, platform=LINUX) == Path("/home/u/.config/task-aprs/config.toml")
    w = config.config_file("task-aprs", env={"APPDATA": r"C:\Users\u\AppData\Roaming"}, platform=WINDOWS)
    assert PureWindowsPath(str(w)).parts[-3:] == ("TASK", "task-aprs", "config.toml")


def test_resources_scan_and_verify_read_only(tmp_path):
    lib = tmp_path / "lib"
    (lib / "sub").mkdir(parents=True)
    (lib / "a.zim").write_bytes(b"zim")
    (lib / "sub" / "m.MBTILES").write_bytes(b"tiles")
    (lib / "notes.txt").write_text("x")
    os.symlink(lib / "a.zim", lib / "link.zim")
    before = {p: p.stat().st_mtime_ns for p in lib.rglob("*")}
    found = resources.scan([lib, tmp_path / "missing"])
    assert sorted((Path(r.path).name, r.kind) for r in found) == [("a.zim", "zim"), ("m.MBTILES", "mbtiles")]
    man = f"{hashlib.sha256(b'zim').hexdigest()}  a.zim\n{'0' * 64}  sub/m.MBTILES\n{'1' * 64}  gone.pdf\n"
    assert resources.verify(lib, man) == {"a.zim": "ok", "sub/m.MBTILES": "mismatch", "gone.pdf": "missing"}
    assert {p: p.stat().st_mtime_ns for p in lib.rglob("*")} == before      # nothing modified
    for bad in (f"{'0' * 64}  ../x", f"{'0' * 64}  /etc/passwd", "short  a"):
        with pytest.raises(ValueError):
            resources.parse_manifest(bad)


def test_resource_roots_include_kiwix_library_read_only():
    roots = [str(r) for r in resources.default_roots(env={"HOME": "/home/u"}, platform=LINUX)]
    assert "/library" in roots and "/home/u/.local/share/task-resources" in roots
    w = resources.default_roots(env={"LOCALAPPDATA": r"C:\L", "USERPROFILE": r"C:\Users\u"}, platform=WINDOWS)
    assert any(str(r).endswith(r"Documents\TASK") for r in w)


def test_capabilities_new_areas_honest():
    assert capabilities.status("launcher", "windows") == "planned"
    assert all(v.get("windows") != "verified" for v in capabilities.CAPABILITIES.values())
