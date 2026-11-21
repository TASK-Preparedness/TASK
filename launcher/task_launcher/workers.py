# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Background polling threads. Each calls a plain function at an interval off the GUI thread and
delivers the result through a queued Qt signal. ``stop()`` ends and joins the thread (used on
window close and launcher exit, and checked by the worker-cleanup tests)."""

import logging
import threading

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("task_launcher")
_live = set()
_live_lock = threading.Lock()


def live_workers():
    with _live_lock:
        return [w for w in _live if w.isRunning()]


class PollWorker(QThread):
    result = Signal(object)

    def __init__(self, fn, interval_s: float, name: str, parent=None, once=False):
        super().__init__(parent)
        self.fn = fn
        self.interval_s = interval_s
        self.once = once
        self._stop = threading.Event()
        self._kick = threading.Event()
        self.setObjectName(name)
        with _live_lock:
            _live.add(self)

    def run(self):
        while not self._stop.is_set():
            try:
                value = self.fn()
            except Exception as exc:  # a collector must never kill the thread silently
                logger.warning("%s failed: %s", self.objectName(), type(exc).__name__)
                value = None
            if self._stop.is_set():
                break
            self.result.emit(value)
            if self.once:
                break
            self._kick.wait(self.interval_s)
            self._kick.clear()

    def poke(self):
        """Run again now (e.g. Refresh)."""
        self._kick.set()

    def stop(self, timeout_ms: int = 5000):
        self._stop.set()
        self._kick.set()
        if self.isRunning():
            self.wait(timeout_ms)
        with _live_lock:
            _live.discard(self)
