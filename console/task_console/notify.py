# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Notification seam (PHASE-2.md section 7.10).

An in-window banner below the status strip. No desktop pop-ups, no focus stealing,
and no audio in Phase 2 (the sound id is accepted and recorded only).
"""

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

SEVERITIES = ("info", "warning", "error")
_ICONS = {"info": "\u2139", "warning": "\u26a0", "error": "\u2715"}


@dataclass
class Notice:
    severity: str
    text: str
    sound: str = None


class Notifier(QObject):
    posted = Signal(object)
    cleared = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history = []

    def post(self, severity: str, text: str, sound: str = None) -> Notice:
        notice = Notice(severity if severity in SEVERITIES else "info", str(text), sound)
        self.history.append(notice)
        del self.history[:-50]
        self.posted.emit(notice)
        return notice

    def clear(self) -> None:
        self.cleared.emit()


class Banner(QFrame):
    def __init__(self, notifier: Notifier, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 8, 4)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setWordWrap(True)
        self.dismiss = QPushButton("Dismiss")
        self.dismiss.clicked.connect(self.hide)
        layout.addWidget(self.icon)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.dismiss)
        notifier.posted.connect(self.show_notice)
        notifier.cleared.connect(self.hide)
        self.hide()

    def show_notice(self, notice: Notice) -> None:
        self.icon.setText(_ICONS[notice.severity] + " " + notice.severity.capitalize())
        self.text.setText(notice.text)
        self.show()
