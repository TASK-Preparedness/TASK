# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Status bar (node count, DB status) and AT-22 touch metrics / 1024x600 layout."""

import pytest
from PySide6.QtWidgets import QAbstractButton, QCheckBox, QListWidget

from task_mesh.domain.models import NodeRecord, StateSnapshot
from task_mesh.services.status_service import StatusInfo, StatusService
from task_mesh.ui.main_window import MainWindow
from task_mesh.ui.node_table import NodeTableModel
from task_mesh.ui.status_bar import StatusBar
from task_mesh.ui.theme import COMPACT, TOUCH, metrics_for, stylesheet
from tests.fakes.fake_ports import candidate


def test_status_bar_renders_counts_and_db(qtbot):
    sb = StatusBar()
    qtbot.addWidget(sb)
    sb.render(StatusInfo(nodes_total=12, nodes_session=5, db_status="ok", db_path="/x/y.sqlite3", bad_packets=2))
    assert sb.nodes_label.text() == "Nodes: 12 known · 5 heard this session"
    assert sb.db_label.text() == "DB: OK" and "/x/y.sqlite3" in sb.db_label.toolTip()
    assert sb.bad_label.text() == "Bad packets: 2"
    sb.render(StatusInfo(db_status="error", db_detail="disk full"))
    assert sb.db_label.text() == "DB: ERROR" and "disk full" in sb.db_label.toolTip()
    sb.render(StatusInfo(db_status="backlog"))
    assert sb.db_label.text() == "DB: backlog"


class FakeWriter:
    def __init__(self, status="ok"):
        self.status = status

    def stats(self):
        from task_mesh.database.writer import WriterStats

        return WriterStats(self.status, "/p.sqlite3", 0, 10, 3 if self.status == "backlog" else 0, 0, None, None, 1)


def test_status_service_aggregates(qtbot):
    w = FakeWriter()
    s = StatusService(w, interval_ms=50)
    seen = []
    s.changed.connect(seen.append)
    s.start()
    s.on_counts(4, 2)
    s.on_counters({"bad_packets": 7})
    w.status = "backlog"
    qtbot.waitUntil(lambda: s.info.db_status == "backlog", timeout=1000)
    s.stop()
    assert s.info.nodes_total == 4 and s.info.bad_packets == 7 and "dropped" in s.info.db_detail
    assert StatusService(None).info.db_status == "starting"


def test_density_selection():
    assert metrics_for("auto", 600) is TOUCH and metrics_for("auto", 1080) is COMPACT
    assert metrics_for("touch", 1080) is TOUCH and metrics_for("compact", 600) is COMPACT
    assert TOUCH.target >= 48 and TOUCH.row >= 44


@pytest.fixture
def window(qtbot, qapp):
    qapp.setStyleSheet(stylesheet(TOUCH))
    m = NodeTableModel()
    w = MainWindow(m, TOUCH)
    qtbot.addWidget(w)
    m.apply([NodeRecord(i, 0, 0, long_name=f"Node {i}") for i in range(40)])
    w.resize(1024, 600)
    w.show()
    qtbot.waitExposed(w)
    yield w
    qapp.setStyleSheet("")


def _interactive(w):
    return [b for b in w.findChildren(QAbstractButton) if b.isVisible()]


@pytest.mark.parametrize("state", ["CONNECTED", "NO_DEVICE", "BACKOFF", "AWAITING_SELECTION", "IDLE",
                                   "PERMISSION_DENIED"])
def test_touch_targets_at_1024x600(window, state, qtbot):
    """AT-22: every visible button >= 48x48 px, rows >= 44 px, panel without horizontal scroll."""
    c = candidate("/dev/ttyUSB0", "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0")
    window.radio_panel.render(StateSnapshot(state=state, port=c, candidates=(c, candidate("/dev/ttyUSB1")),
                                            error_code="PERMISSION_DENIED" if state != "CONNECTED" else None,
                                            error_message="cannot open /dev/serial/by-id/usb-Silicon_Labs_CP2102_"
                                                          "USB_to_UART_Bridge_Controller_0001-if00-port0"))
    qtbot.wait(50)
    assert window.width() <= 1024 and window.height() <= 600
    buttons = _interactive(window)
    assert buttons
    for b in buttons:
        if isinstance(b, QCheckBox):
            assert b.height() >= 44, b.text()
            continue
        assert b.width() >= 48 and b.height() >= 48, (b.text(), b.size())
    sa = window.panel_scroll
    assert sa.horizontalScrollBar().maximum() == 0
    assert window.radio_panel.width() <= sa.viewport().width()
    vh = window.table.verticalHeader()
    assert vh.defaultSectionSize() >= 44
    assert window.table.horizontalHeader().height() >= 48
    for lw in window.findChildren(QListWidget):
        if lw.isVisible() and lw.count():
            assert lw.visualItemRect(lw.item(0)).height() >= 44


def test_kinetic_scroll_grabbed(window):
    from PySide6.QtWidgets import QScroller

    assert QScroller.hasScroller(window.table.viewport())


def test_fullscreen_toggle(window, qtbot):
    window.toggle_fullscreen()
    qtbot.waitUntil(window.isFullScreen, timeout=2000)
    window.toggle_fullscreen()
    qtbot.waitUntil(lambda: not window.isFullScreen(), timeout=2000)


def test_banner(window):
    assert not window.banner.isVisible()
    window.banner.show_message("Database damaged")
    assert window.banner.isVisible() and "Database damaged" in window.banner.label.text()
    window.banner.dismiss.click()
    assert not window.banner.isVisible()
