# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Test 51: no device I/O in task_core or task_console (static scan, PHASE-2.md section 17.5).

task-core stays the sole hardware authority; the console and the admin CLI talk
to task-core only. The single allowed /dev path is /dev/tty in task_core/admin.py:
the controlling terminal for the confirmation prompt (opened the way getpass
opens it), not a device node.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "task_core"
CONSOLE = ROOT / "console" / "task_console"
ALLOWED_DEV = {("admin.py", "/dev/tty")}


def sources(package: Path):
    files = sorted(package.rglob("*.py"))
    assert files, package
    return [(path, path.read_text(encoding="utf-8")) for path in files]


def imports(text):
    names = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def opened_dev_paths(path, text):
    """Every open()/os.open()/io.open()/Path.open() call whose literal argument is under /dev/."""
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("open", "fdopen", "FileIO", "openpty") or name.startswith("open"):
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("/dev/"):
                        found.append((path.name, arg.value))
    return found


def test_51_no_serial_imports_and_no_dev_open():
    for package in (CORE, CONSOLE):
        for path, text in sources(package):
            mods = imports(text)
            assert not mods & {"serial", "pyserial"}, path
            assert not re.search(r"^\s*(import|from)\s+(py)?serial\b", text, re.M), path
            for entry in opened_dev_paths(path, text):
                assert package is CORE and entry in ALLOWED_DEV, (path, entry)


def test_51_console_has_no_udev_sysfs_or_state_access():
    for path, text in sources(CONSOLE):
        mods = imports(text)
        assert "pyudev" not in mods and "serial" not in mods, path
        for needle in ("/dev/", "/sys/", "/run/udev", "devices.json", "accounts.json", "/var/lib/task", "pyudev"):
            assert needle not in text, (path, needle)
        assert not mods & {"task_core", "subprocess", "fcntl", "termios"}, (path, mods)


def test_51_admin_cli_stays_off_hardware():
    """task-core-admin (D14) may mention devices.json in help text but never opens it, /sys or udev."""
    for name in ("admin_client.py", "admin.py"):
        path = CORE / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert not imports(text) & {"pyudev", "serial"}, name
        for needle in ("/sys/", "/run/udev"):
            assert needle not in text, (name, needle)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith("devices.json"):
                assert " " in node.value, (name, node.value)  # prose only, never a bare path literal
