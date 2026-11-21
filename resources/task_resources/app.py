# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Entry point: task-resources [--viewer auto|webengine|lightweight] [--no-scan]."""

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="task-resources")
    ap.add_argument("--viewer", choices=("auto", "webengine", "lightweight"))
    ap.add_argument("--no-scan", action="store_true", help="do not scan the configured folders at start")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)
    from task_resources import __version__
    if a.version:
        print(f"task-resources {__version__}")
        return 0
    if os.geteuid() == 0:
        print("task-resources must not run as root", file=sys.stderr)
        return 2
    from task_resources import settings as settings_mod, viewer
    s = settings_mod.load()
    if a.viewer:
        s.viewer = a.viewer
    viewer.prepare_before_qapplication(s.viewer)      # scheme registration precedes QApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    app.setApplicationName("task-resources")
    app.setDesktopFileName("task-resources")
    from task_resources.library import Library
    from task_resources.ui.main_window import MainWindow
    lib = Library(s)
    from task_resources import paths
    from task_resources.viewer.guard import CrashGuard
    guard = CrashGuard(paths.state_dir() / "webengine-guard.json", host="task-resources")
    w = MainWindow(lib, scan_on_start=not a.no_scan, guard=guard)
    w.show()
    rc = app.exec()
    lib.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
