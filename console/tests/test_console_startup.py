# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tests 53, 54, 55, 75 (single instance) and 76 (desktop non-takeover). TEST DATA only."""

import os
import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from helpers import fake_011_core
from p2fixtures import FakeClock

PKG = Path(__file__).resolve().parents[1] / "task_console"


def test_53_root_refusal_prints_and_exits_without_a_window(qtbot, capsys):
    from task_console import app

    before = set(map(id, QApplication.topLevelWidgets()))
    code = app.main(["--socket", "/nonexistent.sock"], geteuid=lambda: 0)
    assert code != 0
    assert capsys.readouterr().err.strip() == "task-console must not run as root"
    assert set(map(id, QApplication.topLevelWidgets())) == before


@pytest.mark.parametrize("jitter,factor", [(0.5, 1.0), (0.0, 0.8), (1.0, 1.2)])
def test_54_no_core_offline_backoff_then_connects(p2env, console, jitter, factor):
    core = p2env(do_open=False)
    clock = FakeClock(100)
    c = console(core.config.socket, connect=False, rng=lambda: jitter, clock=clock)
    qtbot = c.qtbot
    qtbot.waitUntil(lambda: len(c.controller.retry_delays) == 1, timeout=3000)
    assert c.controller.link == "offline"
    assert re.fullmatch(r"\u2715 Core offline \u2014 retry in \d+ s", c.window.strip.link.text())
    assert c.window.core.fields["Version"].text() == "\u2014 unavailable"
    assert c.window.home.status.text() == "Modules: \u2014 unavailable"
    for _ in range(6):
        count = len(c.controller.retry_delays)
        c.controller.retry_now()  # stands in for the timer; nothing sleeps for the real backoff
        qtbot.waitUntil(lambda: len(c.controller.retry_delays) == count + 1, timeout=3000)
    expected = [0.5, 1, 2, 4, 8, 10, 10]
    assert c.controller.retry_delays == pytest.approx([value * factor for value in expected])
    # the countdown is computed from the injected clock
    assert c.controller.retry_in() == round(10 * factor + 0.4999)
    clock.advance(3)
    assert c.controller.retry_in() == max(0, -(-(10 * factor - 3) // 1))
    core.open()
    c.controller.retry_now()
    c.wait_connected()
    assert c.window.strip.link.text() == "\u25cf Core connected \u00b7 0.2.1"


def test_55_too_old_core_probe_only_every_60_s(console, tmp_path):
    old = fake_011_core(tmp_path / "old.sock")
    try:
        c = console(tmp_path / "old.sock", connect=False)
        c.qtbot.waitUntil(lambda: c.controller.link == "too-old", timeout=3000)
        assert c.window.strip.link.text() == "\u26a0 Core too old (0.1.x)"
        assert "task-core 0.2.0 or later is required" in c.window.banner.text.text()
        assert c.controller.retry_delays == [60.0]
        c.controller.retry_now()
        c.qtbot.waitUntil(lambda: len(c.controller.retry_delays) == 2, timeout=3000)
        assert c.controller.retry_delays == [60.0, 60.0]
        c.settle(200)
        assert len(old.received) == 2
        for request in old.received:
            assert request["v"] == 2 and request["method"] == "core.protocol" and "session" not in request
    finally:
        old.close()


def test_75_single_instance_raises_the_first(qtbot, tmp_path):
    from task_console.app import SingleInstance

    class FakeWindow:
        def __init__(self):
            self.raised = 0

        def isMinimized(self):
            return False

        def raise_(self):
            self.raised += 1

        def activateWindow(self):
            pass

    first = SingleInstance()
    assert first.path == os.path.join(os.environ["XDG_RUNTIME_DIR"], "task-console.instance")
    window = FakeWindow()
    assert first.listen(window)
    try:
        second = SingleInstance()
        assert second.raise_existing() is True
        qtbot.waitUntil(lambda: window.raised == 1, timeout=3000)
    finally:
        first.close()
    assert SingleInstance().raise_existing() is False  # after the first exits, a new launch starts normally


FORBIDDEN_FLAGS = (Qt.WindowType.WindowStaysOnTopHint, Qt.WindowType.X11BypassWindowManagerHint,
                   Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowDoesNotAcceptFocus)


def _no_grabs():
    return QWidget.keyboardGrabber() is None and QWidget.mouseGrabber() is None


def test_76_desktop_non_takeover(p2env, console, isolated_home):
    core = p2env()
    c = console(core.config.socket)
    w = c.window
    w.showMaximized()
    c.settle()
    assert not w.isFullScreen() and w.windowState() & Qt.WindowState.WindowMaximized
    for flag in FORBIDDEN_FLAGS:
        assert not (w.windowFlags() & flag)
    assert _no_grabs()  # public
    dialog = w.request_sign_in()
    assert dialog.windowModality() == Qt.WindowModality.WindowModal and _no_grabs()
    dialog.reject()
    c.sign_in("dragon")
    assert _no_grabs()  # signed in
    w.show_panel("devices")
    w.devices.select_device("dev_ccbc25d5a4210a5a")
    assign = w.devices._open_assign()
    assert assign.windowModality() == Qt.WindowModality.WindowModal and _no_grabs()
    w.controller.lock("test")
    assert _no_grabs()  # locked
    assert not w.overlay.isWindow() and w.overlay.window() is w and w.overlay.parent() is w.body
    assert all(not tl.isVisible() or tl is w for tl in QApplication.topLevelWidgets())
    # F11 enters fullscreen and F11 leaves it
    from PySide6.QtTest import QTest

    w.activateWindow()  # offscreen has no compositor to hand focus back after the dialog closed
    c.qtbot.waitUntil(w.isActiveWindow, timeout=3000)
    QTest.keyClick(w, Qt.Key.Key_F11)
    assert w.isFullScreen()
    QTest.keyClick(w, Qt.Key.Key_F11)
    assert not w.isFullScreen()
    QTest.keyClick(w, Qt.Key.Key_F11)
    assert w.isFullScreen()
    w.close()  # closed while fullscreen: the state is not stored
    state = (isolated_home / ".local" / "state" / "task-console" / "state.toml").read_text()
    assert "full" not in state.lower()
    c2 = console(core.config.socket)
    c2.window.showMaximized()
    c2.settle()
    assert not c2.window.isFullScreen()
    for sub in ("autostart", "labwc", "systemd"):
        assert not (isolated_home / ".config" / sub).exists()


def test_76_static_scan_and_no_autostart_option():
    sources = {path: path.read_text() for path in PKG.rglob("*.py")}
    for path, text in sources.items():
        for word in ("grabKeyboard", "grabMouse", "KeyboardShortcutsInhibit", "keyboard_shortcuts_inhibit",
                     "keyboard-shortcuts-inhibit", "WindowStaysOnTopHint", "X11BypassWindowManagerHint",
                     "FramelessWindowHint", "ApplicationModal", "autostart"):
            assert word not in text or (word == "autostart" and path.name == "app.py" and
                                        "writes no autostart" in text), (path, word)
        for match in re.finditer(r"showFullScreen\(", text):
            enclosing = re.findall(r"def (\w+)\(", text[:match.start()])[-1]
            assert (path.name, enclosing) == ("shell.py", "_toggle_fullscreen"), (path, enclosing)
        for sequence in re.findall(r'QKeySequence\("([^"]+)"\)|\("((?:Ctrl|Alt|Meta|Super|Shift|F)[^"]*)",', text):
            key = "".join(sequence)
            assert not re.search(r"Meta|Super|Alt\+Tab|Alt\+F4|Ctrl\+Alt", key), (path, key)
    from task_console.app import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--enable-autostart"])
    with pytest.raises(SystemExit):
        parse_args(["--disable-autostart"])
