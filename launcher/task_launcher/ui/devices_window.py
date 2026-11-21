# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only device overview through task-core (used when task-console is not installed).

Public: device.counts only (Phase 2 D5 public view; task-core redacts). Operator and above:
device.list. No assign/unassign (that stays in task-console / task-core-admin)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

DASH = "—"
COLUMNS = ("Product", "Manufacturer", "Class", "Connected", "Logical", "Alias", "Device node")


class DevicesWindow(QWidget):
    def __init__(self, link, sign_in_cb, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Devices (read-only overview)")
        self.link = link
        self.resize(1000, 600)
        lay = QVBoxLayout(self)
        self.banner = QLabel("task-console is not installed. This is a read-only overview from task-core.")
        self.banner.setProperty("role", "warn")
        self.banner.setWordWrap(True)
        lay.addWidget(self.banner)
        self.counts = QLabel(DASH)
        self.counts.setProperty("role", "heading")
        lay.addWidget(self.counts)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.sign_in = QPushButton("Sign in to see devices")
        self.sign_in.clicked.connect(sign_in_cb)
        self.refresh = QPushButton("Refresh")
        self.refresh.clicked.connect(self.reload)
        row.addWidget(self.sign_in)
        row.addStretch(1)
        row.addWidget(self.refresh)
        lay.addLayout(row)
        link.changed.connect(self._changed)
        self.render()

    def _changed(self, what):
        if what in ("counts", "devices", "role", "link"):
            self.render()

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def reload(self):
        if self.link.signed_in:
            self.link.fetch_devices()
        elif self.link.live:
            self.link.retry_now()
        self.render()

    def render(self):
        link = self.link
        c = link.counts if link.live else None
        if not link.live:
            self.counts.setText("task-core unavailable")
        elif c:
            self.counts.setText(f"{c['connected']} connected · {c['disconnected']} disconnected · {c['total']} total")
        else:
            self.counts.setText(DASH)
        self.sign_in.setVisible(not link.signed_in)
        devices = (link.devices or {}).get("devices") if link.signed_in and isinstance(link.devices, dict) else None
        if not link.signed_in:
            self.hint.setText("Public view: task-core shows device counts only. Sign in as operator or administrator "
                              "to see the device list.")
        else:
            self.hint.setText(f"Signed in as {link.username} ({link.role}). Read-only.")
        self.table.setVisible(link.signed_in)
        self.table.setRowCount(0)
        for d in devices or []:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = (d.get("product"), d.get("manufacturer"), d.get("class"),
                    "yes" if d.get("connected") else "no" if d.get("connected") is False else None,
                    d.get("logical"), d.get("alias"), d.get("devnode"))
            for col, v in enumerate(vals):
                self.table.setItem(r, col, QTableWidgetItem(str(v) if v not in (None, "") else DASH))
