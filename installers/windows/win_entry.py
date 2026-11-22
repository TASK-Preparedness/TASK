# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Entry point of the EXPERIMENTAL Windows launcher build (PyInstaller). UNVERIFIED on Windows."""
import sys

from task_launcher.app import main

if __name__ == "__main__":
    sys.exit(main())
