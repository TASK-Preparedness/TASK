# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# PyInstaller spec for the EXPERIMENTAL Windows launcher ("onedir"). Run only via build_windows.py,
# which stages a patched copy of launcher/ into build/windows-stage first. UNVERIFIED on Windows.
# -*- mode: python -*-
import os
from pathlib import Path

STAGE = Path(os.environ["TASK_WIN_STAGE"]).resolve()
LAUNCHER = STAGE / "launcher"

a = Analysis(
    [str(STAGE / "win_entry.py")],
    pathex=[str(LAUNCHER), str(STAGE / "platform")],
    datas=[
        (str(LAUNCHER / "task_launcher" / "data"), "task_launcher/data"),
        (str(LAUNCHER / "task_launcher" / "data" / "apps.d"), "apps.d"),
        (str(STAGE / "LICENSE"), "."),
        (str(STAGE / "THIRD_PARTY_NOTICES.md"), "."),
    ],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtNetwork", "task_platform"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TASK-Launcher", console=False,
          icon=str(STAGE / "task-launcher.ico") if (STAGE / "task-launcher.ico").exists() else None,
          uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TASK-Launcher")
