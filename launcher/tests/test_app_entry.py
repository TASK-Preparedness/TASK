# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Entry point: refuses root before Qt, CLI options, single instance, no kiosk/autostart."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[1]


def test_refuses_root_before_importing_qt():
    code = ("import sys; from task_launcher import app; rc = app.main([], geteuid=lambda: 0); "
            "print(rc, any(m.startswith('PySide6') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=LAUNCHER, capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, PYTHONPATH=str(LAUNCHER)))
    assert out.stdout.split() == ["1", "False"], out
    assert "must not run as root" in out.stderr


def test_version_and_help():
    env = dict(os.environ, PYTHONPATH=str(LAUNCHER))
    out = subprocess.run([sys.executable, "-m", "task_launcher", "--version"], capture_output=True, text=True,
                         env=env, timeout=60)
    assert out.stdout.strip() == "task-launcher 0.3.7"
    out = subprocess.run([sys.executable, "-m", "task_launcher", "--help"], capture_output=True, text=True,
                         env=env, timeout=60)
    for opt in ("--socket", "--windowed", "--maximized", "--fullscreen", "--version"):
        assert opt in out.stdout
    assert "kiosk" not in out.stdout.lower()


def test_parse_args_defaults():
    from task_launcher.app import DEFAULT_SOCKET, parse_args

    a = parse_args([])
    assert a.socket is None and DEFAULT_SOCKET == "/run/task/core.sock" and a.start_mode is None  # resolved in main()
    assert parse_args(["--fullscreen"]).start_mode == "fullscreen"
    with pytest.raises(SystemExit):
        parse_args(["--windowed", "--fullscreen"])


def test_single_instance_raises_existing(qtbot, launcher):
    from task_launcher.app import SingleInstance

    w = launcher(start=False)
    first = SingleInstance()
    assert first.listen(w)
    w.showMinimized()
    second = SingleInstance()
    assert second.raise_existing() is True
    qtbot.waitUntil(lambda: not w.isMinimized(), timeout=3000)
    first.close()
    assert SingleInstance().raise_existing() is False


MAIN_SCRIPT = r"""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from task_launcher import app
from task_launcher.core.client import CoreClient
from task_launcher.core.link import CoreLink
from task_launcher.ui.main_window import MainWindow

def build(sock, **k):
    c = CoreClient(sock)
    link = CoreLink(c)
    return MainWindow(link, start_workers=False, motion_hint_fn=None), link, c

qapp = QApplication([])
app.build = build
QTimer.singleShot(800, qapp.quit)
rc = app.main(["--socket", sys.argv[1], "--windowed"], geteuid=lambda: 1000)
print("RC", rc)
"""


def test_main_runs_and_quits(isolated_home, tmp_path):
    """Full main() in a child process (QApplication.quit() must not affect the other tests)."""
    env = dict(os.environ, PYTHONPATH=str(LAUNCHER), QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-c", MAIN_SCRIPT, str(tmp_path / "none.sock")], capture_output=True,
                         text=True, env=env, timeout=60)
    assert "RC 0" in out.stdout, out
    assert "task-launcher 0.3.7 started" in out.stderr
    assert not (isolated_home / ".config/autostart").exists()       # no autostart unless chosen
    log = isolated_home / ".local/state/task-launcher/launcher.log"
    assert log.exists() and oct(log.stat().st_mode & 0o777) == "0o600"


def test_no_hardware_or_privilege_paths_in_source():
    """The launcher never opens device nodes, never elevates and never manages packages. (pkexec/sudo
    appear only in registry/desktop.py's detection list for administrative entries.)"""
    import re

    bad = re.compile(r"/dev/tty|/dev/bus|pyserial|import serial|apt-get|apt install|dpkg -i|"
                     r"os\.setuid|os\.seteuid|shell=True")
    for p in (LAUNCHER / "task_launcher").rglob("*.py"):
        text = p.read_text()
        for m in bad.finditer(text):
            line = text[:m.start()].count("\n") + 1
            raise AssertionError(f"{p.name}:{line}: {m.group(0)}")


def test_spdx_headers_on_all_files():
    for p in list((LAUNCHER / "task_launcher").rglob("*.py")) + list((LAUNCHER / "tests").glob("*.py")):
        head = p.read_text()[:300]
        assert "SPDX-License-Identifier: GPL-3.0-or-later" in head, p
        assert "SPDX-FileCopyrightText: 2026 Joshua Sturtz" in head, p
