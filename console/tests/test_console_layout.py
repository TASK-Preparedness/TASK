# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Test 71: layout at 1920x1080 (scale 1.0 default, 1.25, 1.5) and 1024x600 (scale 1.0). TEST DATA only."""

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QApplication, QLabel, QLineEdit,
                               QListWidget, QScrollBar, QTableView)

from p2fixtures import CP2102_ID

MIN = 48
GAP = 8


def window_rect(widget, root):
    top_left = widget.mapTo(root, QPoint(0, 0))
    return QRect(top_left, widget.size())


def interactive(root):
    """(name, rect) for every visible target: buttons, line edits, tiles, rail items."""
    from task_console.panels.home import Tile

    targets = []
    for widget in root.findChildren(QAbstractButton) + root.findChildren(QLineEdit) + root.findChildren(Tile):
        if not widget.isVisible() or isinstance(widget.parent(), QScrollBar) or widget.window() is not root:
            continue
        if widget.objectName() == "qt_scrollarea_hcontainer":
            continue
        targets.append((f"{type(widget).__name__}:{getattr(widget, 'text', lambda: '')()}", window_rect(widget, root)))
    for rail in root.findChildren(QListWidget):
        if rail.isVisible() and rail.window() is root:
            for index in range(rail.count()):
                rect = rail.visualItemRect(rail.item(index))
                targets.append((f"rail:{index}", QRect(rail.viewport().mapTo(root, rect.topLeft()), rect.size())))
    return targets


def visible_in_viewport(root, rect):
    return root.rect().intersects(rect)


def check_targets(root, label):
    targets = [(n, r) for n, r in interactive(root) if visible_in_viewport(root, r)]
    assert targets, label
    for name, rect in targets:
        assert rect.width() >= MIN and rect.height() >= MIN, (label, name, rect)
    for i, (name_a, a) in enumerate(targets):
        for name_b, b in targets[i + 1:]:
            if a.contains(b) or b.contains(a):
                continue  # a target inside another (e.g. a line edit's own clear button) is one target
            dx = max(b.left() - a.right(), a.left() - b.right()) - 1
            dy = max(b.top() - a.bottom(), a.top() - b.bottom()) - 1
            assert max(dx, dy) >= GAP, (label, name_a, a, name_b, b)


def check_no_horizontal_scroll(root, label):
    for area in root.findChildren(QAbstractScrollArea):
        if area.isVisible() and area.window() is root:
            assert not area.horizontalScrollBar().isVisible(), (label, area)
            if isinstance(area, QTableView):
                header = area.horizontalHeader()
                used = sum(header.sectionSize(c) for c in range(header.count()) if not header.isSectionHidden(c))
                assert used <= area.viewport().width() + 1, (label, used, area.viewport().width())


def check_rows(root, label):
    for table in root.findChildren(QTableView):
        if table.isVisible() and table.window() is root:
            for row in range(table.model().rowCount()):
                assert table.rowHeight(row) >= MIN, (label, row)


def check_full_text(window, label):
    """Ids and states are never elided or clipped."""
    table = window.devices.table
    if table.isVisible():
        from PySide6.QtGui import QFontMetrics

        model = table.model()
        for column in range(model.columnCount()):
            if table.isColumnHidden(column) or model.headerData(column, Qt.Orientation.Horizontal) in (
                    "Name", "Logical / alias"):
                continue
            for row in range(model.rowCount()):
                index = model.index(row, column)
                font = index.data(Qt.ItemDataRole.FontRole) or table.font()
                text = index.data()
                assert QFontMetrics(font).horizontalAdvance(text) + 8 <= table.columnWidth(column), (label, text)
        id_column = [model.headerData(c, Qt.Orientation.Horizontal) for c in range(model.columnCount())].index("Id")
        assert not table.isColumnHidden(id_column)
        status = [model.headerData(c, Qt.Orientation.Horizontal) for c in range(model.columnCount())].index("Status")
        assert not table.isColumnHidden(status)
    from PySide6.QtGui import QFontMetrics

    rail = window.rail
    for index in range(rail.count()):
        item = rail.item(index)
        room = rail.visualItemRect(item).width() - 8
        for line in item.text().split("\n"):
            assert QFontMetrics(rail.font()).horizontalAdvance(line) <= room, (
                label, "rail", line)
    for name in ("link", "identity", "clock"):
        widget = getattr(window.strip, name)
        assert widget.width() >= widget.sizeHint().width(), (label, name)
    for tile in window.home.tiles:
        if tile.isVisible():
            assert tile.state.wordWrap() and tile.state.width() >= tile.state.minimumSizeHint().width()
    for label_widget in window.findChildren(QLabel):
        if label_widget.isVisible() and not label_widget.wordWrap() and label_widget.text():
            assert label_widget.width() >= label_widget.sizeHint().width() - 1, (label, label_widget.text())


def walk_states(c, label):
    w = c.window
    c.activate()
    for key in ("home", "core", "devices"):
        w.show_panel(key)
        c.settle(120)
        check_targets(w, f"{label}/{key}/public")
        check_no_horizontal_scroll(w, f"{label}/{key}/public")
        check_full_text(w, f"{label}/{key}/public")
    signin = w.request_sign_in()
    c.settle(80)
    assert signin.width() <= w.width() and signin.height() <= w.height()
    if w.metrics.compact:
        assert signin.width() <= 1000 and signin.height() <= 560
    check_targets(signin, f"{label}/signin")
    signin.reject()
    c.sign_in("dragon")
    for key in ("home", "core", "devices"):
        w.show_panel(key)
        c.settle(120)
        check_targets(w, f"{label}/{key}/admin")
        check_no_horizontal_scroll(w, f"{label}/{key}/admin")
        check_rows(w, f"{label}/{key}/admin")
        check_full_text(w, f"{label}/{key}/admin")
    assert w.devices.select_device(CP2102_ID)
    c.settle(80)
    if w.metrics.compact:
        w.devices._maybe_open_page()
        c.settle(80)
        assert w.devices.pages.currentIndex() == 2 and w.devices.back.isVisible()
        check_targets(w, f"{label}/detail-page")
    dialog = w.devices._open_assign()
    c.settle(80)
    dialog.radios["gps.primary"].setChecked(True)
    dialog.next.click()
    c.qtbot.waitUntil(lambda: dialog.stack.currentIndex() == 1, timeout=3000)
    c.settle(80)
    assert dialog.width() <= w.width() and dialog.height() <= w.height()
    if w.metrics.compact:
        assert dialog.width() <= 1000 and dialog.height() <= 560
    check_targets(dialog, f"{label}/assign-confirm")
    check_no_horizontal_scroll(dialog, f"{label}/assign-confirm")
    dialog.reject()
    c.controller.lock("test")
    c.settle(80)
    check_targets(w, f"{label}/locked")


@pytest.mark.parametrize("size,scale", [((1920, 1080), 1.0), ((1920, 1080), 1.25), ((1920, 1080), 1.5),
                                        ((1024, 600), 1.0)])
def test_71_layout(p2env, console, size, scale):
    core = p2env()
    c = console(core.config.socket, size=size)
    assert c.window.metrics.scale == 1.0  # a fresh profile starts at scale 1.0 (D8)
    if scale != 1.0:
        c.window.set_scale(scale)
    c.settle(150)
    assert c.window.size().width() == size[0] and c.window.size().height() == size[1]
    assert c.window.metrics.compact == (size == (1024, 600))
    if size == (1024, 600):
        assert c.window.rail.width() == 72 and c.window.home.columns() == 2
    else:
        assert c.window.rail.width() == round(104 * scale)
        if scale == 1.0:
            assert c.window.home.columns() == 4
    walk_states(c, f"{size[0]}x{size[1]}@{scale}")
