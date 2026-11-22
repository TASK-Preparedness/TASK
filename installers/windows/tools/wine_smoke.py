#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Smoke test of the patched launcher under a Windows CPython (e.g. Windows Python 3.12 under Wine).
WINE IS NOT WINDOWS: a pass here is NOT Windows validation.

    wine python.exe wine_smoke.py STAGE_DIR

Imports every launcher module plus task_platform with the real win32 CPython and PySide6 wheels and
builds the main window offscreen (no event loop, no core socket, nothing launched). Reports
paths.is_privileged() as observed (Wine's default user reports as an elevated administrator).
"""
import importlib
import json
import os
import pkgutil
import sys
from pathlib import Path


def main():
    stage = Path(sys.argv[1]).resolve()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path[:0] = [str(stage / "launcher"), str(stage / "platform")]
    from PySide6 import __version__ as pyside
    from PySide6.QtWidgets import QApplication
    app = QApplication(["task-launcher"])
    result = {"python": sys.version, "platform": sys.platform, "pyside6": pyside, "import_failures": [], "window": None}
    import task_launcher
    import task_platform
    for pkg in (task_launcher, task_platform):
        for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            if m.name.endswith("__main__"):
                continue
            try:
                importlib.import_module(m.name)
            except Exception as e:  # noqa: BLE001
                result["import_failures"].append([m.name, repr(e)])
    from task_platform import capabilities, paths as ppaths, serial_ports
    result["task_platform"] = {"config_dir": str(ppaths.config_dir("task")), "serial_ports": len(serial_ports.list_serial_ports())}
    try:
        from task_launcher import app as lapp, paths
        result["paths"] = {"config": str(paths.config_dir()), "state": str(paths.state_dir()),
                           "system_apps": [str(p) for p in paths.SYSTEM_APPS_DIRS],
                           "instance": paths.instance_name(), "privileged": paths.is_privileged()}
        window, _link, _client = lapp.build("C:/nonexistent/core.sock")
        result["window"] = {"class": type(window).__name__, "title": window.windowTitle()}
    except Exception:  # noqa: BLE001
        import traceback
        result["window_error"] = traceback.format_exc().splitlines()[-8:]
    del app
    print(json.dumps(result, indent=2))
    return 0 if not result["import_failures"] and result["window"] else 1


if __name__ == "__main__":
    sys.exit(main())
