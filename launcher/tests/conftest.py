# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-launcher tests: pytest-qt, offscreen, real task-core server (tests/p2fixtures.py).

Everything runs in an isolated HOME/XDG tree. Any attempt to open an IPv4/IPv6 connection or to
resolve a host name fails the test (the launcher makes no external network contact)."""

import os
import socket
import stat
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LAUNCHER = Path(__file__).resolve().parents[1]
REPO = LAUNCHER.parent
for path in (str(LAUNCHER), str(REPO), str(REPO / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest  # noqa: E402

from p2fixtures import p2env  # noqa: E402,F401  (fixture re-export)

REAL_HOME = Path(os.path.expanduser("~"))
NETWORK_ATTEMPTS = []

_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


LOCAL_ALLOWED_PORTS = set()   # loopback ports of test servers started by a test (local_port fixture)


def _guard(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        if address[0] in ("127.0.0.1", "::1") and address[1] in LOCAL_ALLOWED_PORTS:
            return
        NETWORK_ATTEMPTS.append(address)
        raise AssertionError(f"network connection attempted: {address!r}")


def _connect(self, address):
    _guard(self, address)
    return _orig_connect(self, address)


def _connect_ex(self, address):
    _guard(self, address)
    return _orig_connect_ex(self, address)


def _getaddrinfo(host, *a, **k):
    if host not in (None, "localhost", "127.0.0.1", "::1"):
        NETWORK_ATTEMPTS.append(host)
        raise AssertionError(f"name resolution attempted: {host!r}")
    return _orig_getaddrinfo(host, *a, **k)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo


def _world_writable_chain(p: Path) -> bool:
    for d in [p, *p.parents]:
        try:
            if os.stat(d).st_mode & stat.S_IWOTH:
                return True
        except OSError:
            return True
    return False


@pytest.fixture
def safe_dir(tmp_path):
    """A directory whose whole path is not world-writable (executables in /tmp are refused by
    design, see registry/execcheck.py)."""
    if not _world_writable_chain(tmp_path):
        return tmp_path
    base = REAL_HOME / ".cache" / "task-launcher-tests"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    d = Path(tempfile.mkdtemp(prefix="t", dir=base))
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    runtime = tmp_path / "run"
    sysdata = tmp_path / "sysdata"
    home.mkdir()
    runtime.mkdir(mode=0o700)
    (sysdata / "applications").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(sysdata))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "labwc:wlroots")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    (home / ".local" / "share" / "applications").mkdir(parents=True)
    NETWORK_ATTEMPTS.clear()
    yield home
    assert NETWORK_ATTEMPTS == [], f"network contact attempted: {NETWORK_ATTEMPTS}"


@pytest.fixture
def local_port():
    """allow(port): permit loopback connections to a port served by the test itself."""
    def allow(port):
        LOCAL_ALLOWED_PORTS.add(port)
        return port
    yield allow
    LOCAL_ALLOWED_PORTS.clear()


def write_desktop(directory: Path, desktop_id: str, **keys) -> Path:
    """Write a .desktop file. keys map Desktop Entry keys (Name=..., Exec=...)."""
    keys.setdefault("Type", "Application")
    path = Path(directory) / desktop_id.replace("-", "/", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[Desktop Entry]"] + [f"{k}={v}" for k, v in keys.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_exec(directory: Path, name: str, body: str = "exit 0") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(0o755)
    return p


@pytest.fixture
def launcher(qtbot, isolated_home, tmp_path):
    """launcher(socket_path=None, size=(1920, 1080), start=True, **MainWindow kwargs) -> MainWindow."""
    from task_launcher.core.client import CoreClient
    from task_launcher.core.link import CoreLink
    from task_launcher.ui.main_window import MainWindow

    made = []

    def make(socket_path=None, size=(1920, 1080), start=True, scan=True, **kwargs):
        client = CoreClient(str(socket_path or tmp_path / "no-core.sock"))
        link = CoreLink(client, rng=lambda: 0.5)
        kwargs.setdefault("start_workers", False)
        kwargs.setdefault("motion_hint_fn", None)
        kwargs.setdefault("probe_fn", lambda: {})       # Phase 4A readiness probes: stubbed by default
        w = MainWindow(link, **kwargs)
        qtbot.addWidget(w)
        made.append(w)
        w.resize(*size)
        w.show()
        qtbot.waitExposed(w)
        if scan:
            w.registry.set_desktop_entries(w.registry.scan_desktop())
            w.rebuild()
        if start:
            link.start()
        return w

    yield make
    for w in made:
        w.shutdown()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    for top in app.topLevelWidgets():       # sheets, dialogs, secondary windows of this test
        top.close()
        top.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
