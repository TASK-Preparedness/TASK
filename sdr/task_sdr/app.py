# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-sdr (SDR Studio) entry point: desktop user, refuses root, RECEIVE ONLY."""

import argparse
import os
import sys

from task_sdr import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="task-sdr")
    ap.add_argument("--version", action="version", version=f"task-sdr {__version__}")
    ap.add_argument("--simulate", action="store_true", help="SIMULATED receiver only (synthetic IQ, no hardware)")
    ap.add_argument("--diag-log", metavar="PATH", help="write one JSON line of receiver/audio diagnostics per second "
                    "(also TASK_SDR_DIAG_LOG=PATH)")
    ap.add_argument("--audio-mode", choices=("pull", "push"), help="Qt audio sink mode (default pull)")
    args = ap.parse_args(argv)
    if os.geteuid() == 0:
        print("task-sdr must not run as root", file=sys.stderr)
        return 2
    from PySide6.QtWidgets import QApplication
    from task_sdr import prefs
    from task_sdr.backends import registry
    from task_sdr.backends.simulated import SimulatedBackend
    from task_sdr.device import DeviceError
    from task_sdr.audioring import AudioRing
    from task_sdr.engine import Engine
    from task_sdr.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    p = prefs.load()
    backends = [SimulatedBackend()] if args.simulate else registry()

    def no_device():
        raise DeviceError("no receiver selected")
    ring = AudioRing()
    diag = args.diag_log or os.environ.get("TASK_SDR_DIAG_LOG") or None

    def log(msg):
        print(f"task-sdr: {msg}", file=sys.stderr)
    audio = None
    try:
        from task_sdr.audio import QtAudioOut
        audio = QtAudioOut(p.audio_device, ring=ring, mode=args.audio_mode, log=log)
    except (OSError, ImportError) as exc:
        log(f"audio output unavailable: {exc}")
        audio = None
    w = MainWindow(Engine(p, no_device, ring=ring, diag_log=diag), audio, backends=backends)
    w.resize(1280, 760)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
