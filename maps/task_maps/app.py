# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-maps entry point."""

import argparse
import fcntl
import os
import sys

from task_maps import APP_ID, APP_NAME, __version__, paths


def acquire_lock(path=None):
    """Single instance per user: an exclusive flock on ``$XDG_STATE_HOME/task-maps/instance.lock``.
    Returns the open file (keep it) or None when another instance holds it."""
    path = path or (paths.ensure_dir(paths.state_dir()) / "instance.lock")
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def parse_args(argv):
    ap = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME}: offline maps, map downloads and GPS.")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    ap.add_argument("--data-dir", help="use this data folder for this run (default from settings or "
                                       "$XDG_DATA_HOME/task-maps)")
    ap.add_argument("--windowed", action="store_true", help="start in a normal window instead of maximized")
    ap.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    if a.version:
        print(f"{APP_ID} {__version__}")
        return 0
    if os.geteuid() == 0:
        print("task-maps must not run as root; start it as the desktop user.", file=sys.stderr)
        return 2
    if a.data_dir and not a.data_dir.startswith("/"):
        print("--data-dir must be an absolute path", file=sys.stderr)
        return 2
    lock = acquire_lock()
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([APP_ID])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    if lock is None:
        QMessageBox.information(None, APP_NAME, "T.A.S.K. Maps & GPS is already running. Use the window switcher "
                                "to bring it to the front.")
        return 1
    from task_maps.ui.main_window import MainWindow

    w = MainWindow(data_dir=a.data_dir)
    if a.fullscreen:
        w.showFullScreen()
    elif a.windowed:
        w.resize(1200, 760)
        w.show()
    else:
        w.showMaximized()
    rc = app.exec()
    w.shutdown()
    lock.close()
    return rc
