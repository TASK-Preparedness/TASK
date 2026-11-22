#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SIMULATED Windows smoke test of the launcher, run on Linux. NOT a Windows test.

    /usr/bin/python3 installers/windows/tools/simulate_windows_launcher.py LAUNCHER_DIR

After Qt has loaded, it removes POSIX-only ``os`` functions (getuid, geteuid, getgid, statvfs, uname,
getpwuid), sets ``sys.platform = "win32"`` and points APPDATA/LOCALAPPDATA/USERPROFILE at a temp folder.
Then it imports every launcher module and builds the main window offscreen (no event loop, no core
socket, nothing launched). It catches import-time and construction-time POSIX assumptions only; real
Windows APIs, file locking, Qt platform plugins, fonts and drivers are NOT exercised.
"""
import importlib
import json
import os
import pkgutil
import sys
import tempfile
from pathlib import Path


def main():
    launcher = Path(sys.argv[1]).resolve()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    tmp = Path(tempfile.mkdtemp(prefix="simwin-"))
    for k in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA"):
        (tmp / k).mkdir()
        os.environ[k] = str(tmp / k)
    os.environ["HOME"] = str(tmp / "USERPROFILE")
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        os.environ.pop(k, None)
    from PySide6.QtWidgets import QApplication
    app = QApplication(["task-launcher"])
    removed = [n for n in ("getuid", "geteuid", "getgid", "statvfs", "uname", "getpwuid") if hasattr(os, n)]
    for n in removed:
        delattr(os, n)
    sys.platform = "win32"
    sys.path.insert(0, str(launcher))
    result = {"removed_os_functions": removed, "import_failures": [], "window": None}
    import task_launcher
    for m in pkgutil.walk_packages(task_launcher.__path__, "task_launcher."):
        if m.name.endswith("__main__"):
            continue
        try:
            importlib.import_module(m.name)
        except Exception as e:  # noqa: BLE001
            result["import_failures"].append([m.name, repr(e)])
    try:
        from task_launcher import app as lapp, paths
        result["paths"] = {"config": str(paths.config_dir()), "state": str(paths.state_dir()),
                           "user_apps": str(paths.user_apps_dir()), "system_apps": [str(p) for p in paths.SYSTEM_APPS_DIRS],
                           "instance": paths.instance_name(), "privileged": paths.is_privileged()}
        window, link, _client = lapp.build("C:/nonexistent/core.sock")
        result["window"] = {"class": type(window).__name__, "title": window.windowTitle(),
                            "tiles": len(getattr(window, "tiles", []) or [])}
        window.shutdown() if hasattr(window, "shutdown") else None
    except Exception as e:  # noqa: BLE001
        import traceback
        result["window_error"] = traceback.format_exc().splitlines()[-6:]
    del app
    print(json.dumps(result, indent=2))
    return 0 if not result["import_failures"] and result["window"] else 1


if __name__ == "__main__":
    sys.exit(main())
