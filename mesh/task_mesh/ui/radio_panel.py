# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Radio panel: state badge, local device, port, last error + remedy, actions, candidate picker."""

from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from task_mesh.core.errors import ErrorCode, remedy_for, title_for
from task_mesh.domain.models import PortCandidate, StateSnapshot
from task_mesh.domain.states import DESCRIPTIONS, ConnectionState, badge_for
from task_mesh.ui.formatters import DASH, local_time
from task_mesh.ui.theme import BADGE_COLOURS, BG

S = ConnectionState
# Which actions are offered in each state. "stop" = return to IDLE (cancel retries / attempt).
BUTTONS: dict[ConnectionState, frozenset[str]] = {
    S.IDLE: frozenset({"connect"}),
    S.SCANNING: frozenset({"stop"}),
    S.NO_DEVICE: frozenset({"rescan", "stop"}),
    S.AWAITING_SELECTION: frozenset({"rescan", "stop"}),
    S.PERMISSION_DENIED: frozenset({"retry", "stop"}),
    S.PORT_BUSY: frozenset({"stop"}),
    S.CONNECTING: frozenset({"stop"}),
    S.CONNECTED: frozenset({"disconnect"}),
    S.DEVICE_REBOOTING: frozenset({"disconnect"}),
    S.DISCONNECTING: frozenset({"disconnect"}),
    S.BACKOFF: frozenset({"retry", "stop"}),
    S.ERROR: frozenset({"retry", "stop"}),
}


ZWSP = "\u200b"


def breakable(text: str) -> str:
    """Allow word-wrap inside long device names (by-id paths have no spaces)."""
    for ch in ("_", "-", "/", ":", "."):
        text = text.replace(ch, ch + ZWSP)
    return text


def _value(text: Optional[str]) -> QLabel:
    lab = QLabel(text or DASH)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


class RadioPanel(QFrame):
    connect_clicked = Signal()
    disconnect_clicked = Signal()
    rescan_clicked = Signal()
    retry_clicked = Signal()
    candidate_chosen = Signal(object, bool)  # PortCandidate, remember

    def __init__(self, now: Callable[[], int] = lambda: int(time.time()), parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._now = now
        self._snap: Optional[StateSnapshot] = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        title = QLabel("RADIO")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)
        self.badge = QLabel("DISCONNECTED")
        self.badge.setObjectName("Badge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.badge)
        self.state_label = QLabel(DESCRIPTIONS[S.IDLE])
        self.state_label.setWordWrap(True)
        lay.addWidget(self.state_label)
        self.retry_label = QLabel("")
        self.retry_label.setObjectName("Dim")
        self.retry_label.setWordWrap(True)
        lay.addWidget(self.retry_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.device_value = _value(None)
        self.port_value = _value(None)
        self.error_value = _value(None)
        self.error_value.setObjectName("Error")
        for r, (name, w) in enumerate((("Device", self.device_value), ("Port", self.port_value),
                                       ("Last error", self.error_value))):
            k = QLabel(name)
            k.setObjectName("Dim")
            k.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(k, r, 0)
            grid.addWidget(w, r, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.remedy_label = QLabel("")
        self.remedy_label.setObjectName("Remedy")
        self.remedy_label.setWordWrap(True)
        self.remedy_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.remedy_label)

        row1 = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("Primary")
        self.retry_btn = QPushButton("Retry now")
        self.retry_btn.setObjectName("Primary")
        self.disconnect_btn = QPushButton("Disconnect")
        self.rescan_btn = QPushButton("Rescan")
        for b in (self.connect_btn, self.retry_btn, self.disconnect_btn, self.rescan_btn):
            row1.addWidget(b)
        lay.addLayout(row1)
        self.connect_btn.clicked.connect(self.connect_clicked)
        self.retry_btn.clicked.connect(self.retry_clicked)
        self.disconnect_btn.clicked.connect(self.disconnect_clicked)
        self.rescan_btn.clicked.connect(self.rescan_clicked)

        self.picker = QFrame()
        pl = QVBoxLayout(self.picker)
        pl.setContentsMargins(0, 4, 0, 0)
        pt = QLabel("Choose the radio's port:")
        pl.addWidget(pt)
        self.cand_list = QListWidget()
        self.cand_list.setWordWrap(True)
        self.cand_list.setMinimumHeight(110)
        pl.addWidget(self.cand_list)
        self.remember = QCheckBox("Remember this radio")
        pl.addWidget(self.remember)
        self.use_btn = QPushButton("Connect to selected port")
        self.use_btn.setObjectName("Primary")
        self.use_btn.setEnabled(False)
        pl.addWidget(self.use_btn)
        self.cand_list.currentRowChanged.connect(lambda r: self.use_btn.setEnabled(r >= 0))
        self.use_btn.clicked.connect(self._choose)
        lay.addWidget(self.picker)
        self.picker.hide()
        lay.addStretch(1)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_retry)
        self._tick.start()
        self.render(StateSnapshot(state=S.IDLE.value))

    # ----- rendering ------------------------------------------------------------------------------
    def render(self, snap: StateSnapshot) -> None:
        self._snap = snap
        st = S(snap.state)
        badge = badge_for(st).value
        self.badge.setText(badge)
        self.badge.setStyleSheet(f"background: {BADGE_COLOURS[badge]}; color: {BG};")
        desc = DESCRIPTIONS[st]
        if st is S.BACKOFF and snap.error_code:
            desc = f"{desc} — {title_for(ErrorCode(snap.error_code))}"
        self.state_label.setText(f"{desc}\nState: {st.value}")

        ident = snap.identity
        if ident is not None and st in (S.CONNECTED, S.DEVICE_REBOOTING):
            name = ident.long_name or DASH
            if ident.short_name:
                name += f" ({ident.short_name})"
            lines = [name, f"{ident.node_id or DASH} · {ident.hw_model or DASH}",
                     f"Firmware: {ident.firmware_version or DASH}"]
            self.device_value.setText("\n".join(lines))
        else:
            self.device_value.setText(DASH)

        port = snap.port
        if port is not None and st not in (S.IDLE, S.NO_DEVICE, S.AWAITING_SELECTION):
            shown = port.by_id or port.by_path
            text = port.device if not shown else f"{breakable(shown.rsplit('/', 1)[-1])}\n{port.device}"
            self.port_value.setText(text)
            self.port_value.setToolTip(f"Opened as: {port.open_path}\nUSB {port.usb_id}")
        else:
            self.port_value.setText(DASH)
            self.port_value.setToolTip("")

        if snap.error_code:
            code = ErrorCode(snap.error_code)
            when = local_time(snap.error_at_local, self._now()) if snap.error_at_local else DASH
            self.error_value.setText(breakable(f"{title_for(code)} ({when})\n{snap.error_message or ''}".strip()))
            self.remedy_label.setText(remedy_for(code) if st not in (S.CONNECTED,) else "")
        else:
            self.error_value.setText(DASH)
            self.remedy_label.setText(remedy_for(ErrorCode.NO_DEVICE) if st is S.NO_DEVICE else "")
        self.remedy_label.setVisible(bool(self.remedy_label.text()))

        shown = BUTTONS[st]
        self.connect_btn.setVisible("connect" in shown)
        self.retry_btn.setVisible("retry" in shown)
        self.rescan_btn.setVisible("rescan" in shown)
        self.disconnect_btn.setVisible("disconnect" in shown or "stop" in shown)
        self.disconnect_btn.setText("Disconnect" if "disconnect" in shown else "Stop")
        self.disconnect_btn.setEnabled(st is not S.DISCONNECTING)

        show_picker = st is S.AWAITING_SELECTION and bool(snap.candidates)
        if show_picker:
            self._fill_candidates(snap.candidates)
        self.picker.setVisible(show_picker)
        self._update_retry()

    def _fill_candidates(self, cands: tuple[PortCandidate, ...]) -> None:
        current = [self.cand_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.cand_list.count())]
        if list(cands) == current:
            return
        self.cand_list.clear()
        for c in cands:
            label = c.label + ("" if c.classification.value == "likely" else "  (not a known radio chip)")
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, c)
            it.setToolTip(f"Will open: {c.open_path}")
            self.cand_list.addItem(it)
        self.use_btn.setEnabled(False)

    def _choose(self) -> None:
        it = self.cand_list.currentItem()
        if it is not None:
            self.candidate_chosen.emit(it.data(Qt.ItemDataRole.UserRole), self.remember.isChecked())

    def _update_retry(self) -> None:
        snap = self._snap
        if snap is not None and snap.state == S.BACKOFF.value and snap.retry_at_local:
            left = max(0, snap.retry_at_local - self._now())
            self.retry_label.setText(f"Retrying in {left} s")
        elif snap is not None and snap.state == S.PERMISSION_DENIED.value:
            self.retry_label.setText("Waiting for a USB change or Retry now")
        else:
            self.retry_label.setText("")
        self.retry_label.setVisible(bool(self.retry_label.text()))
