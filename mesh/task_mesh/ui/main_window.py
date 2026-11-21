# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Main window: banner (DB/config problems), radio panel, node table, status bar. Fits 1024×600."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QCheckBox,
    QVBoxLayout,
    QWidget,
)

from task_mesh import APP_NAME, __version__
from task_mesh.ui.node_table import NodeTableModel, NodeTableView
from task_mesh.ui.radio_panel import RadioPanel
from task_mesh.ui.status_bar import StatusBar
from task_mesh.ui.theme import TOUCH, Metrics

PANEL_WIDTH = 310


class Banner(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 4, 4)
        self.label = QLabel()
        self.label.setObjectName("Remedy")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.label, 1)
        self.dismiss = QPushButton("Dismiss")
        self.dismiss.clicked.connect(self.hide)
        lay.addWidget(self.dismiss)
        self.hide()

    def show_message(self, text: str) -> None:
        old = self.label.text()
        self.label.setText(text if not old or self.isHidden() else f"{old}\n{text}")
        self.show()


class MainWindow(QMainWindow):
    def __init__(self, model: NodeTableModel, metrics: Metrics = TOUCH, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(800, 480)
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 0)
        outer.setSpacing(6)
        self.banner = Banner()
        outer.addWidget(self.banner)
        body = QHBoxLayout()
        body.setSpacing(6)
        self.radio_panel = RadioPanel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.radio_panel)
        scroll.setFixedWidth(PANEL_WIDTH)
        self.panel_scroll = scroll
        body.addWidget(scroll)
        self.table = NodeTableView(model, metrics)
        self.tabs = QTabWidget()
        nodes_page = QWidget()
        nl = QVBoxLayout(nodes_page)
        nl.setContentsMargins(0, 0, 0, 0)
        self.map_toggle = QCheckBox("Show mesh nodes on Maps (off by default; positions stay on this computer)")
        nl.addWidget(self.map_toggle)
        nl.addWidget(self.table, 1)
        self.tabs.addTab(nodes_page, "Nodes")
        body.addWidget(self.tabs, 1)
        self.messages = None
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.status = StatusBar()
        self.setStatusBar(self.status)
        self.status.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self.toggle_fullscreen)

    def add_messages(self, panel: QWidget) -> None:
        self.messages = panel
        self.tabs.addTab(panel, "Messages")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
