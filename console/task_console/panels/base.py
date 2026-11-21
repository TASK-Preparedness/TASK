# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Panel base and fault containment (PHASE-2.md section 7.12)."""

import functools
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

logger = logging.getLogger("task_console")
DASH = "\u2014"
WITHHELD = "Sign in to view"
UNAVAILABLE = f"{DASH} unavailable"


def dash(value) -> str:
    """Unknown, null or missing renders as an em dash (7.6 item 2)."""
    if value is None or value == "" or value == []:
        return DASH
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def plain(text="", wrap=True, selectable=False, mono=False) -> QLabel:
    """Text from task-core is always rendered as plain text, never rich text (7.6 item 5)."""
    label = QLabel(str(text))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                      | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    if mono:
        label.setProperty("mono", "true")
    return label


def title(text) -> QLabel:
    label = plain(text, wrap=False)
    label.setProperty("role", "title")
    return label


class Panel(QWidget):
    key = ""
    title_text = ""

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.host = None

    def render(self, area: str = "all") -> None:
        raise NotImplementedError

    def reset(self) -> None:
        """Called by Reload after a failure: rebuild from the controller state."""

    def apply_metrics(self, metrics) -> None:
        """Scale or compact mode changed."""

    def guarded(self, fn):
        """Wrap a slot so an exception is contained in this panel."""

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                if self.host is not None:
                    self.host.fail()
                else:
                    raise

        return wrapper


class PanelHost(QStackedWidget):
    """Shows the panel, or the panel error page with a Reload button."""

    def __init__(self, panel: Panel, parent=None) -> None:
        super().__init__(parent)
        self.panel = panel
        panel.host = self
        self.addWidget(panel)
        self.error_page = QWidget()
        layout = QVBoxLayout(self.error_page)
        layout.addWidget(title(panel.title_text))
        self.error_label = plain("This panel failed. Details are in the log.")
        layout.addWidget(self.error_label)
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload)
        layout.addWidget(self.reload_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.addWidget(self.error_page)
        self.failed = False

    def fail(self) -> None:
        logger.exception("panel %s failed", self.panel.key)
        self.failed = True
        self.setCurrentWidget(self.error_page)

    def safe(self, fn, *args) -> bool:
        if self.failed:
            return False
        try:
            fn(*args)
            return True
        except Exception:
            self.fail()
            return False

    def reload(self) -> None:
        self.failed = False
        self.setCurrentWidget(self.panel)
        if self.safe(self.panel.reset):
            self.safe(self.panel.render, "all")
