# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Messages tab: conversations (channels + DMs), history, compose. Locked until Core sign-in."""

from __future__ import annotations

import datetime
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from task_mesh.messaging.packets import MAX_TEXT_BYTES
from task_mesh.messaging.service import BROADCAST_PEER, MessageError

STATE_TEXT = {"queued": "queued", "sent": "sent (no ACK yet)", "relayed": "relayed (implicit ACK)",
              "delivered": "delivered (ACK from destination)", "failed": "failed", "no-ack": "no ACK",
              "received": "received"}


class _Bridge(QObject):
    """MessageService listeners may run on helper threads; hop to the GUI thread."""
    event = Signal(str, object)


class SignInDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in to task-core")
        form = QFormLayout(self)
        self.user = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Account", self.user)
        form.addRow("Password", self.secret)
        self.error = QLabel("")
        self.error.setObjectName("Remedy")
        form.addRow(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class MessagesPanel(QWidget):
    def __init__(self, service, channels_fn=lambda: [], nodes_fn=lambda: [], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.service = service
        self.channels_fn, self.nodes_fn = channels_fn, nodes_fn
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.conv = QComboBox()
        self.conv.setMinimumWidth(260)
        self.conv.currentIndexChanged.connect(self.reload)
        top.addWidget(QLabel("Conversation"))
        top.addWidget(self.conv, 1)
        self.session_label = QLabel("Locked")
        top.addWidget(self.session_label)
        self.sign_btn = QPushButton("Sign in")
        self.sign_btn.clicked.connect(self.toggle_session)
        top.addWidget(self.sign_btn)
        lay.addLayout(top)
        self.locked_note = QLabel("Messages are private. Sign in with your task-core account to view and send.")
        self.locked_note.setWordWrap(True)
        lay.addWidget(self.locked_note)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        lay.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        self.compose = QLineEdit()
        self.compose.setPlaceholderText("Type a message — sent only when you press Send")
        self.compose.textChanged.connect(self._count)
        self.compose.returnPressed.connect(self.send)
        bottom.addWidget(self.compose, 1)
        self.counter = QLabel(f"0/{MAX_TEXT_BYTES}")
        bottom.addWidget(self.counter)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send)
        bottom.addWidget(self.send_btn)
        lay.addLayout(bottom)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self._bridge = _Bridge()
        self._bridge.event.connect(self._on_event, Qt.ConnectionType.QueuedConnection)
        service.listeners.append(lambda k, d: self._bridge.event.emit(k, d))
        self.timer = QTimer(self)
        self.timer.timeout.connect(service.check_timeouts)
        self.timer.start(5000)
        self.refresh_conversations()
        self._apply_lock()

    # ------------------------------------------------------------------ session
    def toggle_session(self) -> None:
        if self.service.gate.unlocked:
            self.service.gate.sign_out()
            self._apply_lock()
            return
        dlg = SignInDialog(self)
        while dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.service.gate.sign_in(dlg.user.text().strip(), dlg.secret.text())
                self.service.unlock()
                break
            except Exception as exc:  # noqa: BLE001
                dlg.error.setText(f"Sign-in failed: {getattr(exc, 'code', type(exc).__name__)}")
                dlg.secret.clear()
        self._apply_lock()
        self.reload()

    def _apply_lock(self) -> None:
        on = self.service.gate.unlocked
        client = self.service.gate.client
        self.session_label.setText(f"{client.username} ({client.role})" if on else "Locked")
        self.sign_btn.setText("Sign out" if on else "Sign in")
        self.locked_note.setVisible(not on)
        self.list.setVisible(on)
        for w in (self.compose, self.send_btn):
            w.setEnabled(on)
        if not on:
            self.list.clear()

    # ------------------------------------------------------------------ conversations
    def refresh_conversations(self) -> None:
        cur = self.conv.currentData()
        self.conv.blockSignals(True)
        self.conv.clear()
        for idx, name, _role in self.channels_fn() or [(0, "Primary", "PRIMARY")]:
            self.conv.addItem(f"Channel {idx}: {name}", (idx, BROADCAST_PEER))
        for nid, label in self.nodes_fn():
            self.conv.addItem(f"DM {label} ({nid})", (0, nid))
        if cur is not None:
            i = self.conv.findData(cur)
            if i >= 0:
                self.conv.setCurrentIndex(i)
        self.conv.blockSignals(False)

    def reload(self) -> None:
        self.list.clear()
        data = self.conv.currentData()
        if data is None or not self.service.gate.unlocked:
            return
        try:
            rows = self.service.conversation(*data)
        except MessageError as exc:
            self.status.setText(str(exc))
            return
        for r in rows:
            self._add_row(r)

    def _row_text(self, r: dict) -> str:
        t = datetime.datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
        who = "me" if r["direction"] == "out" else r["from_id"]
        state = STATE_TEXT.get(r["state"], r["state"])
        if r["state"] == "failed" and r.get("detail"):
            state += f": {r['detail']}"
        if r["direction"] == "in" and r.get("detail"):
            state = r["detail"]
        return f"{t}  {who}: {r['text']}\n    [{state}]"

    def _add_row(self, r: dict) -> None:
        it = QListWidgetItem(self._row_text(r))
        it.setData(Qt.ItemDataRole.UserRole, r["local_id"])
        self.list.addItem(it)

    def _on_event(self, kind: str, data) -> None:
        if kind == "locked":
            self._apply_lock()
            self.status.setText("Session ended — messages locked")
            return
        if kind == "unread":
            self.status.setText(f"{data['count']} new message(s) — sign in to read")
            return
        if not self.service.gate.unlocked or not isinstance(data, dict):
            return
        cur = self.conv.currentData()
        if cur != (data["channel"], data["peer"]):
            if kind == "added" and data["direction"] == "in":
                self.status.setText(f"New message in {'channel ' + str(data['channel']) if data['peer'] == BROADCAST_PEER else data['peer']}")
            return
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == data["local_id"]:
                self.list.item(i).setText(self._row_text(data))
                return
        self._add_row(data)

    # ------------------------------------------------------------------ compose
    def _count(self, text: str) -> None:
        n = len(text.encode("utf-8"))
        self.counter.setText(f"{n}/{MAX_TEXT_BYTES}")
        self.send_btn.setEnabled(self.service.gate.unlocked and 0 < n <= MAX_TEXT_BYTES)

    def send(self) -> None:
        data = self.conv.currentData()
        if data is None:
            return
        channel, peer = data
        try:
            self.service.send(self.compose.text(), channel=channel, dest=None if peer == BROADCAST_PEER else peer)
        except (MessageError, ValueError) as exc:
            self.status.setText(f"Not sent: {exc}")
            return
        self.compose.clear()
        self.status.setText("")
