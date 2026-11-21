# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Idle lock (D11, PHASE-2.md section 6.4) and the in-window Lock overlay.

The idle timer counts input to console windows only (keyboard, mouse, wheel,
touch). It runs whether or not the window has focus and whether or not task-core
is reachable. The overlay is a child widget: never a top-level window, never a
screen locker, never an input grab (section 10.1).
"""

import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from task_console.prefs import clamp_idle

INPUT_EVENTS = {
    QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease,
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseMove,
    QEvent.Type.Wheel,
    QEvent.Type.TouchBegin,
    QEvent.Type.TouchUpdate,
    QEvent.Type.TouchEnd,
    QEvent.Type.TabletPress,
}


class IdleWatcher(QObject):
    idle = Signal()

    def __init__(self, minutes: int, clock=time.monotonic, check_ms: int = 1000, parent=None) -> None:
        super().__init__(parent)
        self.clock = clock
        self.minutes = clamp_idle(minutes)
        self.last_input = clock()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(check_ms)

    @property
    def limit_seconds(self) -> int:
        return self.minutes * 60

    def set_minutes(self, minutes) -> None:
        self.minutes = clamp_idle(minutes)

    def note_input(self) -> None:
        self.last_input = self.clock()

    def check(self) -> bool:
        if self.clock() - self.last_input >= self.limit_seconds:
            self.last_input = self.clock()
            self.idle.emit()
            return True
        return False

    def eventFilter(self, obj, event) -> bool:  # installed on the QApplication
        if event.type() in INPUT_EVENTS:
            self.note_input()
        return False


class LockOverlay(QFrame):
    """Covers the whole content area of the console window (rail and panels)."""

    signInRequested = Signal()
    publicRequested = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setObjectName("overlay")
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self.name = QLabel("T.A.S.K.")
        self.name.setProperty("role", "title")
        self.clock = QLabel("\u2014")
        self.clock.setProperty("role", "title")
        self.link = QLabel("\u2014")
        self.state = QLabel("\U0001f512 Locked \u2014 signed out")
        self.state.setProperty("role", "title")
        for label in (self.name, self.clock, self.link, self.state):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.sign_in = QPushButton("Sign in")
        self.public = QPushButton("Continue as public")
        self.sign_in.clicked.connect(self.signInRequested)
        self.public.clicked.connect(self.publicRequested)
        buttons.addWidget(self.sign_in)
        buttons.addSpacing(16)
        buttons.addWidget(self.public)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(2)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def show_locked(self) -> None:
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self.sign_in.setFocus()
