# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Window-modal dialogs: sign in (6.4), assign (8.5), unassign (8.6).

Every dialog is Qt.WindowModal to the console window only (10.1), fits the
layout's dialog bounds and scrolls internally, and sends nothing on Cancel.
In confirmations that displace or remove, Cancel is the default button (7.3).
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from task_console import session as S
from task_console.widgets.password_field import PasswordField

LOGICALS = ("gps.primary", "mesh.primary", "sdr.primary", "radio.primary")
LOGICAL_CAPABILITY = {  # the Phase 1 capability each logical device backs (same table as task-core-admin)
    "gps.primary": "gps.position",
    "mesh.primary": "mesh.messaging",
    "sdr.primary": "radio.rx",
    "radio.primary": "radio.tx",
}
MAX_ALIAS = 64


def plain(text, parent=None, wrap=True) -> QLabel:
    label = QLabel(str(text), parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    return label


class ConsoleDialog(QDialog):
    """Base: window-modal, bounded size, internal scrolling, registered for lock cancellation.

    Ctrl+L also works while a console dialog has focus (the main window is modally
    blocked then); the lock cancels the dialog without sending anything.
    """

    lockRequested = Signal()

    def __init__(self, parent, title: str, max_size) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMaximumSize(*max_size)
        self.cancelled = False
        outer = QVBoxLayout(self)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        self.buttons = QHBoxLayout()
        outer.addLayout(self.buttons)
        self.rejected.connect(self._mark_cancelled)
        lock = QShortcut(QKeySequence("Ctrl+L"), self)
        lock.setContext(Qt.ShortcutContext.WindowShortcut)
        lock.activated.connect(self.lockRequested)

    def _mark_cancelled(self) -> None:
        self.cancelled = True

    def scrub(self) -> None:
        self.setWindowTitle("")
        for widget in self.findChildren(QLabel) + self.findChildren(QAbstractButton):
            widget.setText("")
            widget.setAccessibleName("")
        for edit in self.findChildren(QLineEdit):
            edit.clear()

    def fit(self, preferred) -> None:
        width = min(preferred[0], self.maximumWidth())
        height = min(preferred[1], self.maximumHeight())
        self.resize(width, height)


class SignInDialog(ConsoleDialog):
    def __init__(self, parent, controller, max_size) -> None:
        super().__init__(parent, "Sign in to T.A.S.K.", max_size)
        self.controller = controller
        form = QFormLayout(self.body)
        self.username = QLineEdit()
        self.username.setAccessibleName("Username")
        self.username.setInputMethodHints(Qt.InputMethodHint.ImhNoAutoUppercase
                                          | Qt.InputMethodHint.ImhNoPredictiveText)
        self.password = PasswordField()
        self.message = plain("")
        self.message.setAccessibleName("Sign-in message")
        form.addRow(plain("Username", wrap=False), self.username)
        form.addRow(plain("Password", wrap=False), self.password)
        form.addRow(self.message)
        self.cancel = QPushButton("Cancel")
        self.submit = QPushButton("Sign in")
        self.submit.setDefault(True)
        self.cancel.setAutoDefault(False)
        self.buttons.addStretch(1)
        self.buttons.addWidget(self.cancel)
        self.buttons.addWidget(self.submit)
        self.cancel.clicked.connect(self.reject)
        self.submit.clicked.connect(self._submit)
        self.finished.connect(lambda _code: self.password.clear())
        self._blocked = QTimer(self)
        self._blocked.setSingleShot(True)
        self._blocked.setTimerType(Qt.TimerType.PreciseTimer)
        self._blocked.timeout.connect(lambda: self.submit.setEnabled(True))
        self.busy = False
        self.fit((640, 360))
        self.username.setFocus()

    def _submit(self) -> None:
        if self.busy or not self.submit.isEnabled():
            return
        username = self.username.text()
        if S.password_too_long(self.password.text()):
            self.message.setText(S.MSG_TOO_LONG)  # nothing is sent
            return
        if not username or not self.password.text():
            self.message.setText("Enter a username and a password.")
            return
        self.busy = True
        self.submit.setEnabled(False)
        self.message.setText("Signing in\u2026")
        self.controller.login(username, self.password.text(), self._done, still_wanted=lambda: not self.cancelled)

    def _done(self, reply) -> None:
        self.busy = False
        if self.cancelled:
            return
        if reply.get("ok") is True:
            self.accept()
            return
        self.submit.setEnabled(True)
        error = reply.get("error") or {}
        if reply.get("transport"):
            self.message.setText(S.MSG_UNAVAILABLE)
        elif error.get("code") == "rate-limited":
            self.message.setText(error.get("message", ""))
            seconds = S.retry_seconds(error.get("message", ""))
            if seconds:
                self.submit.setEnabled(False)
                self._blocked.start(seconds * 1000)
        else:
            self.message.setText(f"task-core: {error.get('message', 'refused')}")


class AssignDialog(ConsoleDialog):
    """Step 1: choose the logical device and an alias. Step 2: the confirmation (8.5)."""

    continueRequested = Signal(str, str)  # logical, alias
    assignRequested = Signal(str, str, str, bool)  # logical, device_id, alias, confirm_displace

    def __init__(self, parent, device: dict, max_size) -> None:
        name = device.get("product") or device.get("manufacturer") or "\u2014"
        super().__init__(parent, f"Assign {name}", max_size)
        self.device = device
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self.body)
        layout.addWidget(plain(f"Assign {name} ({device.get('id')})"))
        layout.addWidget(self.stack)
        # step 1
        choose = QWidget()
        choose_layout = QVBoxLayout(choose)
        choose_layout.addWidget(plain("Logical device"))
        self.choices = QButtonGroup(self)
        potential = device.get("potential") or []
        ordered = sorted(LOGICALS, key=lambda lg: (LOGICAL_CAPABILITY[lg] not in potential, LOGICALS.index(lg)))
        self.radios = {}
        for logical in ordered:
            matches = LOGICAL_CAPABILITY[logical] in potential
            radio = QRadioButton(f"{logical} \u2014 matches device class" if matches else logical)
            self.radios[logical] = radio
            self.choices.addButton(radio)
            choose_layout.addWidget(radio)
        self.radios[ordered[0]].setChecked(True)
        choose_layout.addWidget(plain("Alias (optional, at most 64 characters)"))
        self.alias = QLineEdit()
        self.alias.setAccessibleName("Alias")
        choose_layout.addWidget(self.alias)
        self.alias_message = plain("")
        choose_layout.addWidget(self.alias_message)
        choose_layout.addStretch(1)
        self.stack.addWidget(choose)
        # step 2
        self.confirm_page = QWidget()
        self.confirm_layout = QVBoxLayout(self.confirm_page)
        self.stack.addWidget(self.confirm_page)
        self.message = plain("")
        layout.addWidget(self.message)
        self.cancel = QPushButton("Cancel")
        self.next = QPushButton("Continue")
        self.assign = QPushButton("Assign")
        self.buttons.addStretch(1)
        for button in (self.cancel, self.next, self.assign):
            self.buttons.addWidget(button)
        self.cancel.clicked.connect(self.reject)
        self.next.clicked.connect(self._continue)
        self.assign.clicked.connect(self._assign)
        self.assign.hide()
        self.next.setDefault(True)
        self.checks = []
        self.effects = None
        self.fit((820, 620))

    def selected_logical(self) -> str:
        for logical, radio in self.radios.items():
            if radio.isChecked():
                return logical
        return LOGICALS[0]

    def _continue(self) -> None:
        alias = self.alias.text()
        if len(alias) > MAX_ALIAS:
            self.alias_message.setText("Aliases are at most 64 characters.")
            return
        self.alias_message.setText("")
        self.next.setEnabled(False)
        self.message.setText("Checking the current assignments\u2026")
        self.continueRequested.emit(self.selected_logical(), alias)

    def show_confirmation(self, effects, note: str = None) -> None:
        """effects: dict(lines, displaced, warnings) from panels.devices.assign_effects."""
        self.effects = effects
        while self.confirm_layout.count():
            item = self.confirm_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.checks = []
        if note:
            self.confirm_layout.addWidget(plain(note))
        self.confirm_layout.addWidget(plain("This will:"))
        for line in effects["lines"]:
            self.confirm_layout.addWidget(plain("\u2022 " + line))
        for warning in effects["warnings"]:
            self.confirm_layout.addWidget(plain("\u26a0 " + warning))
            check = QCheckBox("I understand; continue anyway")
            check.setAccessibleName("Confirm: " + warning)
            check.toggled.connect(self._update_assign)
            self.checks.append(check)
            self.confirm_layout.addWidget(check)
        self.confirm_layout.addStretch(1)
        self.assign.setText("Assign and replace" if effects["displaced"] else "Assign")
        self.stack.setCurrentIndex(1)
        self.next.hide()
        self.next.setDefault(False)
        self.assign.show()
        self.assign.setAutoDefault(False)
        self.assign.setDefault(False)
        self.cancel.setAutoDefault(True)
        self.cancel.setDefault(True)  # Cancel is the default in confirmations (7.3)
        self.message.setText("")
        self._update_assign()
        self.cancel.setFocus()

    def _update_assign(self) -> None:
        self.assign.setEnabled(all(check.isChecked() for check in self.checks))

    def show_error(self, text: str) -> None:
        self.message.setText(text)
        self.next.setEnabled(True)
        self.assign.setEnabled(self.effects is not None and all(c.isChecked() for c in self.checks))

    def _assign(self) -> None:
        if self.effects is None or not all(check.isChecked() for check in self.checks):
            return
        self.assign.setEnabled(False)
        self.message.setText("Assigning\u2026")
        self.assignRequested.emit(self.effects["logical"], self.device.get("id"), self.alias.text(),
                                  bool(self.effects["displaced"]))


class UnassignDialog(ConsoleDialog):
    confirmed = Signal(str)

    def __init__(self, parent, logical: str, device: dict, max_size) -> None:
        super().__init__(parent, f"Unassign {logical}", max_size)
        self.logical = logical
        name = device.get("product") or device.get("manufacturer") or "\u2014"
        alias = f'alias "{device["alias"]}"' if device.get("alias") is not None else "no alias"
        layout = QVBoxLayout(self.body)
        layout.addWidget(plain(f"Unassign {logical}?"))
        layout.addWidget(plain(f"{logical} is held by {name} \u00b7 {device.get('id', chr(0x2014))} \u00b7 {alias}"))
        layout.addWidget(plain("The device record stays; only the assignment is removed."))
        self.message = plain("")
        layout.addWidget(self.message)
        layout.addStretch(1)
        self.cancel = QPushButton("Cancel")
        self.ok = QPushButton("Unassign")
        self.buttons.addStretch(1)
        self.buttons.addWidget(self.cancel)
        self.buttons.addWidget(self.ok)
        self.ok.setAutoDefault(False)
        self.cancel.setAutoDefault(True)
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self._confirm)
        self.fit((720, 360))
        self.cancel.setFocus()

    def _confirm(self) -> None:
        self.ok.setEnabled(False)
        self.message.setText("Unassigning\u2026")
        self.confirmed.emit(self.logical)

    def show_error(self, text: str) -> None:
        self.message.setText(text)
        self.ok.setEnabled(True)
