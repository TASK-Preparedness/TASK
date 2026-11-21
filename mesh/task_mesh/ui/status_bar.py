# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Status bar: node counts, database status, bad-packet counter, fullscreen toggle."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QPushButton, QStatusBar, QWidget

from task_mesh.services.status_service import StatusInfo
from task_mesh.ui.theme import AMBER, GREEN, RED, TEXT_DIM

_DB_TEXT = {"ok": ("DB: OK", GREEN), "backlog": ("DB: backlog", AMBER), "error": ("DB: ERROR", RED),
            "starting": ("DB: starting…", TEXT_DIM), "stopped": ("DB: closed", TEXT_DIM)}


class StatusBar(QStatusBar):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.nodes_label = QLabel()
        self.db_label = QLabel()
        self.bad_label = QLabel()
        self.fullscreen_btn = QPushButton("Fullscreen")
        self.fullscreen_btn.setToolTip("Toggle fullscreen (F11)")
        self.addWidget(self.nodes_label)
        self.addWidget(self.db_label)
        self.addWidget(self.bad_label)
        self.addPermanentWidget(self.fullscreen_btn)
        self.render(StatusInfo())

    def render(self, info: StatusInfo) -> None:
        self.nodes_label.setText(f"Nodes: {info.nodes_total} known · {info.nodes_session} heard this session")
        self.nodes_label.setToolTip("Known = stored in the local database. Heard = updated by the radio since launch.")
        text, colour = _DB_TEXT.get(info.db_status, (f"DB: {info.db_status}", AMBER))
        self.db_label.setText(text)
        self.db_label.setStyleSheet(f"color: {colour}; font-weight: bold;")
        tip = f"Database: {info.db_path or '—'}"
        if info.db_detail:
            tip += f"\n{info.db_detail}"
        self.db_label.setToolTip(tip)
        self.bad_label.setText(f"Bad packets: {info.bad_packets}")
        self.bad_label.setToolTip("Malformed packets or node entries discarded (details in the log).")
