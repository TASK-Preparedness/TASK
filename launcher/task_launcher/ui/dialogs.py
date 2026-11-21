# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Sign-in dialog, information sheet and Settings dialog."""

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout)

from task_launcher import __version__, autostart, branding
from task_launcher.layout import describe
from task_launcher.settings import SCALES, Settings

MAX_PASSWORD = 256


class SignInDialog(QDialog):
    """Username + masked password. The password is read once, passed to session.login and the
    field is cleared immediately; it is never stored, logged or echoed."""

    submitted = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to task-core")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        heading = QLabel("Sign in")
        heading.setProperty("role", "heading")
        lay.addWidget(heading)
        form = QFormLayout()
        self.username = QLineEdit()
        self.username.setAccessibleName("Username")
        self.username.setMaxLength(64)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("Password")
        self.password.setMaxLength(MAX_PASSWORD + 1)
        self.password.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        lay.addLayout(form)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        note = QLabel("Accounts are managed on the Pi with task-core-admin. Nothing is remembered.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel = QPushButton("Cancel")
        self.submit = QPushButton("Sign in")
        self.submit.setDefault(True)
        row.addWidget(self.cancel)
        row.addWidget(self.submit)
        lay.addLayout(row)
        self.cancel.clicked.connect(self.reject)
        self.submit.clicked.connect(self._submit)
        self.busy = False
        self._unblock = QTimer(self)
        self._unblock.setSingleShot(True)
        self._unblock.timeout.connect(lambda: self.submit.setEnabled(True))
        self.resize(460, 0)

    def _submit(self):
        if self.busy:
            return
        user = self.username.text().strip()
        secret = self.password.text()
        self.password.clear()          # cleared from the widget before anything else happens
        if not user or not secret:
            self.show_error("Enter a username and a password.")
            return
        if len(secret) > MAX_PASSWORD:
            self.show_error("Passwords are at most 256 characters.")
            return
        self.busy = True
        self.submit.setEnabled(False)
        self.message.setProperty("role", "muted")
        self.message.setText("Signing in…")
        self.submitted.emit(user, secret)
        secret = None  # noqa: F841  (drop our reference; Python cannot guarantee memory wiping)

    def show_error(self, text, retry_seconds=None):
        self.busy = False
        self.message.setProperty("role", "error")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
        if retry_seconds:
            self.submit.setEnabled(False)
            self._unblock.start(int(retry_seconds * 1000))
        else:
            self.submit.setEnabled(True)
        self.password.setFocus()


def retry_seconds(message):
    m = re.search(r"retry in (\d+) s", message or "")
    return int(m.group(1)) if m else None


def login_error_text(reply):
    err = reply.get("error") or {}
    code, msg = err.get("code"), err.get("message", "")
    if reply.get("transport"):
        return "task-core is not reachable. Try again when the footer shows Connected."
    if code == "unauthenticated":
        return "Wrong username or password."
    if code == "rate-limited":
        return f"task-core: {msg}"
    if code == "forbidden":
        return ("task-core does not allow sign-in from this desktop account "
                "(it must be listed in /etc/task/sessions.toml [clients]; before migration /etc/rain/sessions.toml).")
    return f"task-core refused: {msg or code}"


class InfoSheet(QDialog):
    def __init__(self, title, lines, buttons=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        h = QLabel(title)
        h.setProperty("role", "heading")
        lay.addWidget(h)
        self.body = QLabel("\n\n".join(x for x in lines if x))
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.body)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons = {}
        for label, cb in buttons:
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, f=cb: (f(), self.accept()))
            row.addWidget(b)
            self.buttons[label] = b
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.resize(560, 0)


class SettingsDialog(QDialog):
    """Per-user preferences only (no privileged settings)."""

    def __init__(self, settings: Settings, effective_layout_fn, about: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.src = settings
        self.effective_layout_fn = effective_layout_fn
        lay = QVBoxLayout(self)

        g = QGroupBox("Branding")
        gl = QVBoxLayout(g)
        self.brand_group = QButtonGroup(self)
        self.brand = {}
        for key, label in (("default", "System default"),
                           ("task", "T.A.S.K. — Tactical Access Support Kit"), ("custom", "Custom")):
            rb = QRadioButton(label)
            self.brand[key] = rb
            self.brand_group.addButton(rb)
            gl.addWidget(rb)
        self.brand["task" if settings.branding == "rain" else settings.branding].setChecked(True)
        form = QFormLayout()
        self.custom_title = QLineEdit(settings.custom_title)
        self.custom_title.setMaxLength(branding.MAX_TITLE)
        self.custom_subtitle = QLineEdit(settings.custom_subtitle)
        self.custom_subtitle.setMaxLength(branding.MAX_SUBTITLE)
        form.addRow("Custom title", self.custom_title)
        form.addRow("Custom subtitle", self.custom_subtitle)
        gl.addLayout(form)
        lay.addWidget(g)

        g = QGroupBox("Appearance")
        f = QFormLayout(g)
        self.layout_combo = QComboBox()
        for key, label in (("auto", "Automatic (Large, falls back)"), ("large", "Large (full-width)"),
                           ("standard", "Standard (1200 px)"), ("compact", "Compact")):
            self.layout_combo.addItem(label, key)
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(settings.layout)))
        self.scale_combo = QComboBox()
        for v in SCALES:
            self.scale_combo.addItem(f"{v:g}×", v)
        self.scale_combo.setCurrentIndex(max(0, self.scale_combo.findData(settings.scale)))
        self.effective = QLabel("")
        self.effective.setWordWrap(True)
        self.effective.setProperty("role", "muted")
        self.motion_combo = QComboBox()
        for key, label in (("system", "Follow the desktop setting"), ("on", "Reduce motion"),
                           ("off", "Always animate")):
            self.motion_combo.addItem(label, key)
        self.motion_combo.setCurrentIndex(max(0, self.motion_combo.findData(settings.reduce_motion)))
        self.show_planned = QCheckBox("Show planned apps")
        self.show_planned.setChecked(settings.show_planned)
        f.addRow("Layout", self.layout_combo)
        f.addRow("UI scale", self.scale_combo)
        f.addRow("", self.effective)
        f.addRow("Page animation", self.motion_combo)
        f.addRow("", self.show_planned)
        lay.addWidget(g)
        self.layout_combo.currentIndexChanged.connect(self._update_effective)
        self.scale_combo.currentIndexChanged.connect(self._update_effective)
        self._update_effective()

        g = QGroupBox("Launch behaviour")
        f = QFormLayout(g)
        self.start_combo = QComboBox()
        for key, label in (("maximized", "Maximized (default)"), ("windowed", "Windowed"),
                           ("fullscreen", "Fullscreen (F11 toggles, Esc leaves)")):
            self.start_combo.addItem(label, key)
        self.start_combo.setCurrentIndex(max(0, self.start_combo.findData(settings.start_mode)))
        self.idle = QSpinBox()
        self.idle.setRange(1, 10)
        self.idle.setSuffix(" min")
        self.idle.setValue(settings.idle_lock_minutes)
        self.autostart = QCheckBox("Start when I log in (writes ~/.config/autostart/task-launcher.desktop)")
        self.autostart.setChecked(autostart.is_enabled())
        self.autostart_note = QLabel("")
        self.autostart_note.setProperty("role", "warn")
        self.autostart_note.setWordWrap(True)
        if autostart.foreign_entry_exists():
            self.autostart.setEnabled(False)
            self.autostart_note.setText(f"{autostart.autostart_path()} exists and was not written by the launcher; "
                                        "it is left alone.")
        f.addRow("Start", self.start_combo)
        f.addRow("Lock after idle", self.idle)
        f.addRow("", self.autostart)
        f.addRow("", self.autostart_note)
        lay.addWidget(g)

        g = QGroupBox("About")
        al = QVBoxLayout(g)
        text = QLabel(
            f"task-launcher {__version__} · task-core {about.get('core') or '—'} · Qt {about.get('qt', '—')} · "
            f"PySide6 {about.get('pyside', '—')}\nFont: {about.get('font', '—')}\n"
            "Licence: GPL-3.0-or-later (© 2026 Joshua Sturtz). Icons: Lucide (ISC; some icons MIT, Feather). "
            "Font Inter: SIL OFL-1.1 via the Debian package fonts-inter (not bundled).\n"
            "Recovery without the GUI: task-core-admin (see the task-core documentation).")
        text.setWordWrap(True)
        text.setProperty("role", "muted")
        al.addWidget(text)
        lay.addWidget(g)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update_effective(self):
        self.effective.setText(self.effective_layout_fn(self.layout_combo.currentData(), self.scale_combo.currentData()))

    def result_settings(self) -> Settings:
        s = Settings(**{k: getattr(self.src, k) for k in self.src.__dataclass_fields__})
        s.branding = next(k for k, rb in self.brand.items() if rb.isChecked())
        s.custom_title = self.custom_title.text()
        s.custom_subtitle = self.custom_subtitle.text()
        s.layout = self.layout_combo.currentData()
        s.scale = self.scale_combo.currentData()
        s.reduce_motion = self.motion_combo.currentData()
        s.show_planned = self.show_planned.isChecked()
        s.start_mode = self.start_combo.currentData()
        s.idle_lock_minutes = self.idle.value()
        return s.normalized()

    def autostart_wanted(self):
        return self.autostart.isChecked() if self.autostart.isEnabled() else None


def effective_layout_text(window_w, window_h):
    from task_launcher.layout import layout

    def fn(mode, scale):
        return describe(mode, layout(window_w(), window_h(), scale, mode))
    return fn
