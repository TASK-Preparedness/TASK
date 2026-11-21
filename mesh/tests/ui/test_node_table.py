# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import time

import pytest
from PySide6.QtCore import QPoint, Qt

from task_mesh.domain.models import NodeRecord, Source
from task_mesh.ui.node_table import COLUMNS, NodeTableModel, NodeTableView

NOW = int(time.time())
DASH = "—"
D = Qt.ItemDataRole.DisplayRole


def rows():
    return [
        NodeRecord(1, NOW, NOW, node_id="!00000001", long_name="Alpha", short_name="A", hw_model="TBEAM",
                   last_heard_radio=NOW - 60, rssi_last=-80, snr=5.5, snr_source=Source.PACKET, hops_away=1,
                   hops_source=Source.RADIO_NODEDB, battery_level=90, latitude=1.0, longitude=2.0),
        NodeRecord(3, NOW, NOW, node_id="!00000003"),
        NodeRecord(2, NOW, NOW, node_id="!00000002", long_name="Bravo", last_heard_radio=NOW - 5,
                   hops_away=3, hops_source=Source.CALCULATED, battery_level=101, voltage=5.0),
    ]


@pytest.fixture
def view(qtbot):
    m = NodeTableModel(now=lambda: NOW)
    v = NodeTableView(m)
    qtbot.addWidget(v)
    m.apply(rows())
    v.resize(900, 500)
    v.show()
    return v


def test_columns_exact():
    assert COLUMNS == ("Long Name", "Short Name", "Node ID", "Hardware", "Last Heard", "RSSI", "SNR", "Hops",
                       "Battery", "Latitude", "Longitude")


@pytest.mark.parametrize("col", range(len(COLUMNS)))
def test_em_dash_for_every_missing_column(col, qtbot):
    """AT-20: None renders as an em dash in every column, never 0 or empty."""
    m = NodeTableModel(now=lambda: NOW)
    m.apply([NodeRecord(9, NOW, NOW)])
    val = m.data(m.index(0, col), D)
    if COLUMNS[col] == "Node ID":
        assert val == DASH  # node_id unset in this synthetic record
    else:
        assert val == DASH, COLUMNS[col]
    assert val not in ("0", "", "Unknown")


def test_values_calc_and_powered(view):
    m = view.source_model
    r_b = next(i for i in range(3) if m.record(i).node_num == 2)
    assert m.data(m.index(r_b, COLUMNS.index("Hops")), D) == "3 calc"
    assert m.data(m.index(r_b, COLUMNS.index("Battery")), D) == "Powered"
    r_a = next(i for i in range(3) if m.record(i).node_num == 1)
    assert m.data(m.index(r_a, COLUMNS.index("RSSI")), D) == "-80 dBm"
    assert "last packet" in m.data(m.index(r_a, COLUMNS.index("SNR")), Qt.ItemDataRole.ToolTipRole)


def _column(view, name):
    p = view.proxy
    return [p.data(p.index(r, COLUMNS.index(name)), D) for r in range(p.rowCount())]


def test_sort_last_heard_none_last(view):
    view.sortByColumn(COLUMNS.index("Last Heard"), Qt.SortOrder.DescendingOrder)
    assert _column(view, "Long Name") == ["Bravo", "Alpha", DASH]
    view.sortByColumn(COLUMNS.index("Last Heard"), Qt.SortOrder.AscendingOrder)
    assert _column(view, "Long Name") == ["Alpha", "Bravo", DASH]


def test_sort_node_id(view):
    view.sortByColumn(COLUMNS.index("Node ID"), Qt.SortOrder.AscendingOrder)
    assert _column(view, "Node ID") == ["!00000001", "!00000002", "!00000003"]
    view.sortByColumn(COLUMNS.index("Node ID"), Qt.SortOrder.DescendingOrder)
    assert _column(view, "Node ID") == ["!00000003", "!00000002", "!00000001"]


def test_update_in_place_and_insert(view):
    m = view.source_model
    m.apply([NodeRecord(3, NOW, NOW, node_id="!00000003", long_name="Charlie"), NodeRecord(4, NOW, NOW)])
    assert m.rowCount() == 4
    assert "Charlie" in _column(view, "Long Name")


def test_stale_rows_dimmed_with_tooltip(qtbot):
    m = NodeTableModel(now=lambda: NOW)
    m.apply([NodeRecord(1, NOW, NOW, long_name="Old", stale=True)])
    assert m.data(m.index(0, 0), Qt.ItemDataRole.ForegroundRole) is not None
    assert "Last known" in m.data(m.index(0, 0), Qt.ItemDataRole.ToolTipRole)


def test_double_click_and_long_press_open_details(view, qtbot):
    view.show_details(0)
    d = view.last_dialog
    assert d is not None and d.isVisible()
    d.accept()
    view.last_dialog = None
    pos = view.visualRect(view.proxy.index(0, 0)).center()
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    qtbot.waitUntil(lambda: view.last_dialog is not None, timeout=2000)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    view.last_dialog.accept()


def test_details_dialog_read_only_content(qtbot):
    from PySide6.QtWidgets import QLabel, QLineEdit

    from task_mesh.ui.node_table import NodeDetailsDialog

    d = NodeDetailsDialog(NodeRecord(1, NOW, NOW, long_name="X", stale=True), NOW)
    qtbot.addWidget(d)
    texts = [w.text() for w in d.findChildren(QLabel)]
    assert "X" in texts and DASH in texts and d.findChildren(QLineEdit) == []
