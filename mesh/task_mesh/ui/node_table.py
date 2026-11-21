# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Node table: QAbstractTableModel + sortable QTableView with kinetic touch scrolling."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScroller,
    QTableView,
    QVBoxLayout,
)

from task_mesh.domain.models import NodeRecord
from task_mesh.ui import formatters as fmt
from task_mesh.ui.theme import STALE, Metrics, TOUCH

COLUMNS = ("Long Name", "Short Name", "Node ID", "Hardware", "Last Heard", "RSSI", "SNR", "Hops",
           "Battery", "Latitude", "Longitude")
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
NUMERIC = {5, 6, 7, 8, 9, 10}
STALE_TIP = "Last known value from the database — not yet refreshed by the radio this session."


def cell(rec: NodeRecord, col: int, now: int) -> tuple[str, str, Any]:
    """(display, tooltip, sort key) for one cell. Sort key None sorts last."""
    if col == 0:
        return fmt.text(rec.long_name), "Source: radio (user.longName).", rec.long_name and rec.long_name.lower()
    if col == 1:
        return fmt.text(rec.short_name), "Source: radio (user.shortName).", rec.short_name and rec.short_name.lower()
    if col == 2:
        return fmt.text(rec.node_id), f"Node number {rec.node_num}.", rec.node_num
    if col == 3:
        return fmt.text(rec.hw_model), "Source: radio (user.hwModel).", rec.hw_model
    if col == 4:
        d, t = fmt.last_heard(rec, now)
        key = rec.last_heard_radio if rec.last_heard_radio is not None else rec.last_rx_local
        return d, t, key
    if col == 5:
        d, t = fmt.rssi(rec)
        return d, t, rec.rssi_last
    if col == 6:
        d, t = fmt.snr(rec)
        return d, t, rec.snr
    if col == 7:
        d, t = fmt.hops(rec)
        return d, t, rec.hops_away
    if col == 8:
        d, t = fmt.battery(rec)
        return d, t, rec.battery_level
    if col == 9:
        return fmt.coordinate(rec.latitude), fmt.position_tooltip(rec), rec.latitude
    if col == 10:
        return fmt.coordinate(rec.longitude), fmt.position_tooltip(rec), rec.longitude
    raise IndexError(col)


class NodeTableModel(QAbstractTableModel):
    def __init__(self, now: Callable[[], int] = lambda: int(time.time()), parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._rows: list[NodeRecord] = []
        self._index: dict[int, int] = {}
        self._now = now

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def record(self, row: int) -> NodeRecord:
        return self._rows[row]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        rec = self._rows[index.row()]
        col = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, SORT_ROLE):
            d, tip, key = cell(rec, col, self._now())
            if role == Qt.ItemDataRole.DisplayRole:
                return d
            if role == Qt.ItemDataRole.ToolTipRole:
                return f"{tip}\n{STALE_TIP}" if rec.stale else tip
            return key
        if role == Qt.ItemDataRole.ForegroundRole and rec.stale:
            return QBrush(QColor(STALE))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in NUMERIC:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def apply(self, rows: list[NodeRecord]) -> None:
        new = []
        for rec in rows:
            i = self._index.get(rec.node_num)
            if i is None:
                new.append(rec)
            else:
                self._rows[i] = rec
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLUMNS) - 1))
        if new:
            start = len(self._rows)
            self.beginInsertRows(QModelIndex(), start, start + len(new) - 1)
            for rec in new:
                self._index[rec.node_num] = len(self._rows)
                self._rows.append(rec)
            self.endInsertRows()

    def refresh_times(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, 4), self.index(len(self._rows) - 1, 4))


class NoneLastProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        a = left.data(SORT_ROLE)
        b = right.data(SORT_ROLE)
        asc = self.sortOrder() == Qt.SortOrder.AscendingOrder
        if a is None and b is None:
            return False
        if a is None:
            return not asc   # None always at the bottom
        if b is None:
            return asc
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class _LongPress(QObject):
    """Long-press on the table viewport (touch has no right click)."""

    triggered = Signal(QPoint)

    def __init__(self, view: QTableView, ms: int = 650) -> None:
        super().__init__(view)
        self._view = view
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(ms)
        self._timer.timeout.connect(lambda: self.triggered.emit(self._pos))
        self._pos = QPoint()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress:
            self._pos = ev.position().toPoint()
            self._timer.start()
        elif t == QEvent.Type.MouseMove:
            if (ev.position().toPoint() - self._pos).manhattanLength() > 12:
                self._timer.stop()
        elif t in (QEvent.Type.MouseButtonRelease, QEvent.Type.Leave):
            self._timer.stop()
        return False


class NodeDetailsDialog(QDialog):
    """Read-only view of every stored field for one node, with sources."""

    def __init__(self, rec: NodeRecord, now: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Node {rec.node_id or rec.node_num}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        for col, name in enumerate(COLUMNS):
            d, tip, _ = cell(rec, col, now)
            lab = QLabel(d)
            lab.setToolTip(tip)
            lab.setWordWrap(True)
            form.addRow(f"{name}:", lab)
            if tip and col in (4, 5, 6, 7, 8, 9):
                t = QLabel(tip)
                t.setObjectName("Dim")
                t.setWordWrap(True)
                form.addRow("", t)
        form.addRow("Role:", QLabel(fmt.text(rec.role)))
        form.addRow("Altitude:", QLabel(fmt.DASH if rec.altitude_m is None else f"{rec.altitude_m} m"))
        form.addRow("Via MQTT:", QLabel(fmt.DASH if rec.via_mqtt is None else ("yes" if rec.via_mqtt else "no")))
        if rec.stale:
            s = QLabel(STALE_TIP)
            s.setObjectName("Remedy")
            s.setWordWrap(True)
            form.addRow("", s)
        lay.addLayout(form)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close)


class NodeTableView(QTableView):
    def __init__(self, model: NodeTableModel, metrics: Metrics = TOUCH, parent=None) -> None:
        super().__init__(parent)
        self.source_model = model
        self.proxy = NoneLastProxy(self)
        self.proxy.setSourceModel(model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setDynamicSortFilter(True)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.sortByColumn(4, Qt.SortOrder.DescendingOrder)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.apply_metrics(metrics)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        hh.setHighlightSections(False)
        for col, w in enumerate((150, 70, 100, 110, 100, 85, 85, 70, 85, 95, 100)):
            self.setColumnWidth(col, max(w, hh.sectionSizeHint(col)))
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self._long = _LongPress(self)
        self.viewport().installEventFilter(self._long)
        self._long.triggered.connect(self._details_at)
        self.doubleClicked.connect(lambda idx: self.show_details(idx.row()))
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(30000)
        self._clock_timer.timeout.connect(model.refresh_times)
        self._clock_timer.start()
        self.last_dialog: Optional[NodeDetailsDialog] = None

    def apply_metrics(self, m: Metrics) -> None:
        self.verticalHeader().setDefaultSectionSize(m.row)
        self.verticalHeader().setMinimumSectionSize(m.row)
        self.horizontalHeader().setMinimumHeight(m.target)

    def _details_at(self, pos: QPoint) -> None:
        idx = self.indexAt(pos)
        if idx.isValid():
            self.show_details(idx.row())

    def show_details(self, proxy_row: int) -> None:
        src = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
        if not src.isValid():
            return
        rec = self.source_model.record(src.row())
        self.last_dialog = NodeDetailsDialog(rec, int(time.time()), self)
        self.last_dialog.open()
