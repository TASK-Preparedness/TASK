# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-launcher entry point.

Refuses to run as root before any Qt object exists. One instance per user (a second launch raises
the first window). Writes no autostart or session file unless the user ticks the option in Settings.
Never replaces labwc, the session or the login manager; it is an ordinary decorated window.
"""

import argparse
import logging
import logging.handlers
import os
import sys

from task_launcher import __version__

logger = logging.getLogger("task_launcher")
ROOT_MESSAGE = "task-launcher must not run as root"
DEFAULT_SOCKET = "/run/task/core.sock"  # see core.client.resolve_socket for the legacy fallback


def setup_logging(to_file: bool) -> None:
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    logger.addHandler(h)
    if to_file:
        from task_launcher.paths import state_dir

        try:
            d = state_dir()
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = d / "launcher.log"
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
            fh = logging.handlers.RotatingFileHandler(path, maxBytes=1 << 20, backupCount=2, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError as exc:
            logger.warning("log file unavailable (%s)", type(exc).__name__)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="task-launcher", description="T.A.S.K. launcher (task-core client)")
    p.add_argument("--socket", default=None, help="task-core socket (default %(default)s)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--maximized", dest="start_mode", action="store_const", const="maximized",
                   help="start maximized (default unless changed in Settings)")
    g.add_argument("--windowed", dest="start_mode", action="store_const", const="windowed", help="start windowed")
    g.add_argument("--fullscreen", dest="start_mode", action="store_const", const="fullscreen",
                   help="start fullscreen (F11 toggles, Esc leaves)")
    p.add_argument("--version", action="version", version=f"task-launcher {__version__}")
    return p.parse_args(argv)


class SingleInstance:
    def __init__(self, path=None):
        from PySide6.QtNetwork import QLocalServer

        from task_launcher.paths import instance_name

        self.path = path or instance_name()
        self.server = QLocalServer()
        self.window = None

    def raise_existing(self) -> bool:
        from PySide6.QtNetwork import QLocalSocket

        probe = QLocalSocket()
        probe.connectToServer(self.path)
        if probe.waitForConnected(500):   # startup only, before any window exists
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

    def _on_connection(self):
        c = self.server.nextPendingConnection()
        if c is not None:
            c.disconnectFromServer()
        if self.window is not None:
            if self.window.isMinimized():
                self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def close(self):
        self.server.close()


def build(socket_path=DEFAULT_SOCKET, **window_kwargs):
    """Create client, link and window (used by main and by the tests)."""
    from task_launcher.core.client import CoreClient
    from task_launcher.core.link import CoreLink
    from task_launcher.ui.main_window import MainWindow

    client = CoreClient(socket_path)
    link = CoreLink(client)
    window = MainWindow(link, **window_kwargs)
    return window, link, client


def show_window(window, mode):
    if mode == "fullscreen":
        window.showFullScreen()
    elif mode == "windowed":
        from PySide6.QtGui import QGuiApplication

        geo = QGuiApplication.primaryScreen().availableGeometry()
        window.resize(min(1600, geo.width()), min(900, geo.height()))
        window.show()
    else:
        window.showMaximized()   # within the compositor's work area (labwc panel stays visible)


def main(argv=None, *, geteuid=None) -> int:
    from task_launcher import paths as _paths
    if (geteuid() == 0) if geteuid is not None else _paths.is_privileged():
        print(ROOT_MESSAGE, file=sys.stderr)
        return 1
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging(to_file=not (sys.stderr and sys.stderr.isatty()))
    from PySide6.QtWidgets import QApplication
    from task_launcher.services import resources_embed
    if QApplication.instance() is None:
        resources_embed.prepare_before_qapplication()     # 4F.3: embedded Medical reader (WebEngine schemes)

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "task-launcher"])
    app.setApplicationName("task-launcher")
    app.setDesktopFileName("task-launcher")
    instance = SingleInstance()
    if instance.raise_existing():
        logger.info("task-launcher is already running; raised the existing window")
        return 0
    sys.excepthook = lambda k, v, tb: logger.error("unhandled exception", exc_info=(k, v, tb))
    from task_launcher.core.client import resolve_socket
    args.socket = resolve_socket(args.socket)
    window, link, _client = build(args.socket)
    instance.listen(window)
    app.aboutToQuit.connect(window.shutdown)
    show_window(window, args.start_mode or window.settings.start_mode)
    link.start()
    logger.info("task-launcher %s started (socket %s, platform %s)", __version__, args.socket, app.platformName())
    try:
        return app.exec()
    finally:
        instance.close()
