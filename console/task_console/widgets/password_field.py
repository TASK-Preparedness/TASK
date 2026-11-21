# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Password field (D4, PHASE-2.md section 6.5 item 8).

* single-line QLineEdit, EchoMode.Password (Qt keeps copy and cut disabled);
* paste allowed (Ctrl+V, Shift+Insert, context menu) and offered as a visible button;
* no maxLength is set (Qt's default is left untouched), so nothing is silently truncated;
* sensitive input-method hints; the text is sent unchanged (no trimming, no normalization).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

HINTS = (Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText
         | Qt.InputMethodHint.ImhNoAutoUppercase)


class PasswordField(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.edit = QLineEdit(self)
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setInputMethodHints(HINTS)
        self.edit.setAccessibleName("Password")
        self.paste_button = QPushButton("Paste", self)
        self.paste_button.setAccessibleName("Paste password")
        self.paste_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.paste_button.clicked.connect(self._paste)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.paste_button)
        self.setFocusProxy(self.edit)

    def _paste(self) -> None:
        self.edit.setFocus()
        self.edit.paste()

    def text(self) -> str:
        return self.edit.text()

    def clear(self) -> None:
        self.edit.clear()
