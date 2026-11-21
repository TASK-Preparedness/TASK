# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-aprs entry point. Runs as the desktop user (refuses root). Never starts Direwolf."""

import argparse
import os
import sys

from task_aprs import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="task-aprs")
    ap.add_argument("--version", action="version", version=f"task-aprs {__version__}")
    ap.add_argument("--socket", default=None, help="T.A.S.K. Core socket (default: auto)")
    ap.add_argument("--gmrs-simulation", action="store_true",
                    help="use the SIMULATED GMRS radio (nothing is transmitted; for training/tests)")
    args = ap.parse_args(argv)
    if os.geteuid() == 0:
        print("task-aprs must not run as root", file=sys.stderr)
        return 2
    from PySide6.QtWidgets import QApplication
    from task_comms.auth import SessionGate
    from task_comms.core import CoreClient
    from task_aprs.history import History
    from task_aprs.service import AprsService
    from task_aprs.ui.main_window import MainWindow

    driver = None
    if args.gmrs_simulation:
        from task_aprs.gmrs.simulated import SimulatedGmrsDriver
        driver = SimulatedGmrsDriver()
        driver.open()
    app = QApplication(sys.argv[:1])
    client = CoreClient(args.socket)
    gate = SessionGate(client, idle_lock_s=15 * 60)
    svc = AprsService(session_role=lambda: client.role if gate.unlocked else None, gmrs_driver=driver)
    svc.connect()
    w = MainWindow(svc, gate, History)
    w.resize(1000, 700)
    w.show()
    rc = app.exec()
    svc.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
