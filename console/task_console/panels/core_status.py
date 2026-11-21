# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Core status (public; identical for every role) (PHASE-2.md section 7.5)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFormLayout, QHeaderView, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from task_console.panels.base import DASH, UNAVAILABLE, Panel, dash, plain, title


def uptime_text(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return DASH
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours} h {minutes:02d} min {secs:02d} s"


def make_table(headers) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setTabKeyNavigation(False)
    return table


def fill(table: QTableWidget, rows, row_height: int) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            table.setItem(r, c, item)
        table.setRowHeight(r, row_height)
    header = table.horizontalHeader().sizeHint().height()
    table.setFixedHeight(header + row_height * max(1, len(rows)) + 4)


class CoreStatusPanel(Panel):
    key = "core"
    title_text = "Core status"

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        outer.addWidget(title(self.title_text))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        form = QFormLayout()
        self.fields = {}
        for key in ("Connection", "Socket", "Version", "Server uid", "Uptime", "Protocol versions", "Boot id",
                    "Last event seq", "Devices"):
            value = plain(DASH, selectable=True)
            self.fields[key] = value
            form.addRow(plain(key, wrap=False), value)
        layout.addLayout(form)
        layout.addWidget(plain("Capabilities", wrap=False))
        self.caps = make_table(["Name", "Kind", "Status"])
        layout.addWidget(self.caps)
        layout.addWidget(plain("Modules", wrap=False))
        self.modules = make_table(["Id", "State", "Reason"])
        layout.addWidget(self.modules)
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    def render(self, area: str = "all") -> None:
        c = self.ctx.controller
        live = c.live
        f = self.fields
        f["Connection"].setText(c.link_text())
        f["Socket"].setText(c.client.socket_path)
        health = c.health if live else None
        if health:
            f["Version"].setText(dash(health.get("version")))
            f["Server uid"].setText(dash(health.get("uid")))
            f["Uptime"].setText(f"{uptime_text(health.get('uptime_seconds'))} (reported at {c.health_at}; F5 refreshes)")
        else:
            for key in ("Version", "Server uid", "Uptime"):
                f[key].setText(UNAVAILABLE if not live else DASH)
        protocol = c.protocol if live else None
        if protocol:
            f["Protocol versions"].setText(dash(protocol.get("versions")))
            boot = protocol.get("boot_id")
            f["Boot id"].setText(f"{boot[:8]}\u2026" if isinstance(boot, str) and boot else DASH)
        else:
            f["Protocol versions"].setText(UNAVAILABLE if not live else DASH)
            f["Boot id"].setText(UNAVAILABLE if not live else DASH)
        f["Last event seq"].setText(dash(c.last_seq))
        counts = c.counts if live else None
        if counts:
            f["Devices"].setText(f"{counts.get('total', DASH)} total \u00b7 {counts.get('connected', DASH)} connected "
                                 f"\u00b7 {counts.get('disconnected', DASH)} disconnected")
        else:
            f["Devices"].setText(UNAVAILABLE if not live else DASH)
        row = self.ctx.metrics.row_height
        caps = c.capabilities or []
        fill(self.caps, [(dash(e.get("name")), dash(e.get("kind")), dash(e.get("status")) if live else UNAVAILABLE)
                         for e in caps], row)
        mods = c.modules or []
        fill(self.modules, [(dash(m.get("id")), dash(m.get("state")) if live else UNAVAILABLE, dash(m.get("reason")))
                            for m in mods], row)
