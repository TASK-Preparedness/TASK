# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-console entry point (PHASE-2.md sections 7.11, 7.12, 10).

Refuses euid 0 before any window exists. One instance per user (a second launch
raises the first). Launched manually only; it writes no autostart or session file.
"""

import argparse
import logging
import logging.handlers
import os
import sys
import tempfile

from task_console import __version__
from task_console.core_client import DEFAULT_SOCKET, resolve_socket

logger = logging.getLogger("task_console")
ROOT_MESSAGE = "task-console must not run as root"


def instance_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return os.path.join(runtime, "task-console.instance")
    return os.path.join(tempfile.gettempdir(), f"task-console-{os.getuid()}.instance")


def setup_logging(to_file: bool) -> None:
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(formatter)
    logger.addHandler(stderr)
    if to_file:
        from task_console.prefs import state_dir

        try:
            directory = state_dir()
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / "console.log"
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
            os.chmod(path, 0o600)
            handler = logging.handlers.RotatingFileHandler(path, maxBytes=1 << 20, backupCount=3, encoding="utf-8")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except OSError as exc:
            logger.warning("console log file unavailable (%s)", type(exc).__name__)


class SingleInstance:
    """QLocalServer lock in $XDG_RUNTIME_DIR. A second launch asks the first to raise its window."""

    def __init__(self, path: str = None) -> None:
        from PySide6.QtNetwork import QLocalServer

        self.path = path or instance_path()
        self.server = QLocalServer()
        self.window = None

    def raise_existing(self) -> bool:
        from PySide6.QtNetwork import QLocalSocket

        probe = QLocalSocket()
        probe.connectToServer(self.path)
        if probe.waitForConnected(500):  # startup only, before any window exists
            probe.write(b"raise\n")
            probe.waitForBytesWritten(500)
            probe.disconnectFromServer()
            return True
        return False

    def listen(self, window) -> bool:
        from PySide6.QtNetwork import QLocalServer

        self.window = window
        QLocalServer.removeServer(self.path)
        ok = self.server.listen(self.path)
        self.server.newConnection.connect(self._on_connection)
        return ok

    def _on_connection(self) -> None:
        connection = self.server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
        if self.window is not None:
            if self.window.isMinimized():
                self.window.showMaximized()
            self.window.raise_()
            self.window.activateWindow()

    def close(self) -> None:
        self.server.close()


def build(socket_path: str = DEFAULT_SOCKET, *, idle_clock=None, controller_kwargs=None, client_kwargs=None):
    """Create the client, controller and window (used by main and by the tests)."""
    import time

    from task_console.controller import Controller
    from task_console.core_client import CoreClient
    from task_console.prefs import Prefs, WindowState
    from task_console.shell import MainWindow

    client = CoreClient(socket_path, **(client_kwargs or {}))
    controller = Controller(client, **(controller_kwargs or {}))
    window = MainWindow(controller, Prefs(), WindowState(), idle_clock=idle_clock or time.monotonic)
    window.client = client
    return window, controller, client


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="task-console", description="T.A.S.K. Console (task-core client)")
    parser.add_argument("--socket", default=resolve_socket(), help="task-core socket (default %(default)s)")
    parser.add_argument("--version", action="version", version=f"task-console {__version__}")
    return parser.parse_args(argv)


def main(argv=None, *, geteuid=os.geteuid) -> int:
    if geteuid() == 0:
        print(ROOT_MESSAGE, file=sys.stderr)
        return 1
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging(to_file=not (sys.stderr and sys.stderr.isatty()))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "task-console"])
    app.setApplicationName("task-console")
    app.setDesktopFileName("task-console")
    instance = SingleInstance()
    if instance.raise_existing():
        logger.info("task-console is already running; raised the existing window")
        return 0

    def hook(kind, value, tb):
        logger.error("unhandled exception", exc_info=(kind, value, tb))

    sys.excepthook = hook
    window, controller, _client = build(args.socket)
    instance.listen(window)
    window.showMaximized()  # maximized within the work area; never fullscreen at start
    controller.start()
    logger.info("task-console %s started (socket %s, platform %s, scale %s)", __version__, args.socket,
                app.platformName(), window.metrics.scale)
    try:
        return app.exec()
    finally:
        instance.close()
