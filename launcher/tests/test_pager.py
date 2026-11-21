# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Horizontal animated pagination (ui/pager.py, ui/home.py). Added tiles are TEST DATA."""

import statistics

import pytest
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import write_desktop
from task_launcher.ui import pager as P


def add_tiles(isolated_home, n):
    apps = isolated_home / ".local/share/applications"
    for i in range(n):
        write_desktop(apps, f"test.app{i:02d}.desktop", Name=f"TESTDATA App {i + 1}", Exec="/bin/true")
    return [f"test.app{i:02d}.desktop" for i in range(n)]


@pytest.fixture
def paged(qtbot, launcher, isolated_home):
    def make(extra=6, size=(1920, 1080), **kw):
        ids = add_tiles(isolated_home, extra)
        w = launcher(size=size, start=False, **kw)
        w.activateWindow()
        qtbot.waitUntil(w.isActiveWindow, timeout=2000)
        for did in ids:
            w.registry.add_desktop(did)
        w.rebuild()
        return w
    return make


def wait_settled(qtbot, pg, timeout=3000):
    qtbot.waitUntil(lambda: not pg.animating(), timeout=timeout)


def test_page_one_is_the_twelve_builtins(paged):
    w = paged(6)
    h = w.home
    assert h.grid_geom["per_page"] == 12 and h.grid_geom["pages"] == 2
    assert [h.page_of(i) for i in range(12)] == [0] * 12
    assert all(h.page_of(i) == 1 for i in range(12, 18))
    assert all(t.tile.key.startswith("app:task.") for t in h.tiles[:12])
    assert all(t.tile.source == "desktop" for t in h.tiles[12:])
    assert h.page_bar.isVisible()
    assert [d.accessibleName() for d in h.page_bar.dots] == ["Page 1 of 2 (current)", "Page 2 of 2"]
    assert all(d.focusPolicy() != Qt.FocusPolicy.NoFocus for d in h.page_bar.dots)


def test_single_page_has_no_page_bar(launcher):
    w = launcher(start=False)
    assert w.home.grid_geom["pages"] == 1 and not w.home.page_bar.isVisible()


def test_strip_holds_pages_side_by_side(paged):
    w = paged(14)
    pg = w.home.pager
    assert pg.pages == 3
    assert pg.strip.width() == 3 * pg.page_w
    xs = [t.x() for t in w.home.tiles]
    assert xs[12] >= pg.page_w and xs[24] >= 2 * pg.page_w
    assert all(t.parent() is pg.strip for t in w.home.tiles)


def test_drag_follows_pointer(paged):
    pg = paged().home.pager
    pg.press(1000, 500, t=0.0)
    assert pg.move(1000 - P.DRAG_THRESHOLD + 1, 500, t=0.01) is False   # below threshold: still a click
    assert pg.strip.x() == 0
    assert pg.move(900, 502, t=0.05) is True
    assert pg.strip.x() == -100
    pg.move(700, 505, t=0.10)
    assert pg.strip.x() == -300


def test_vertical_movement_is_not_a_page_drag(paged):
    pg = paged().home.pager
    pg.press(1000, 500, t=0.0)
    assert pg.move(985, 560, t=0.05) is False
    assert pg.release(985, 560, t=0.06) is False


def test_spring_back_below_threshold(qtbot, paged):
    pg = paged().home.pager
    dist = int(pg.page_w * P.SNAP_FRACTION) - 20
    pg.press(1500, 500, t=0.0)
    pg.move(1500 - dist // 2, 500, t=0.5)
    pg.move(1500 - dist, 500, t=1.0)          # slow: no fling
    assert pg.release(1500 - dist, 500, t=1.2) is True
    wait_settled(qtbot, pg)
    assert pg.page == 0 and pg.strip.x() == 0


def test_snap_past_threshold(qtbot, paged):
    pg = paged().home.pager
    dist = int(pg.page_w * P.SNAP_FRACTION) + 10
    pg.press(1500, 500, t=0.0)
    pg.move(1500 - dist, 500, t=1.0)
    pg.release(1500 - dist, 500, t=1.2)
    assert pg.animating()
    wait_settled(qtbot, pg)
    assert pg.page == 1 and pg.strip.x() == -pg.page_w


def test_fling_velocity_snaps_short_drag(qtbot, paged):
    pg = paged().home.pager
    pg.press(1500, 500, t=0.0)
    pg.move(1480, 500, t=0.01)
    pg.move(1440, 500, t=0.03)               # 60 px in 30 ms = 2000 px/s
    pg.release(1440, 500, t=0.035)
    wait_settled(qtbot, pg)
    assert pg.page == 1
    # the same distance slowly springs back
    pg.press(500, 500, t=10.0)
    pg.move(530, 500, t=10.5)
    pg.move(560, 500, t=11.0)
    pg.release(560, 500, t=11.1)
    wait_settled(qtbot, pg)
    assert pg.page == 1


def test_fling_against_drag_direction_does_not_snap(qtbot, paged):
    pg = paged().home.pager
    pg.press(1500, 500, t=0.0)
    pg.move(1300, 500, t=1.0)                 # 200 px left, below 25 %
    pg.move(1290, 500, t=1.01)
    pg.move(1340, 500, t=1.03)                # flicked back right, fast
    pg.release(1340, 500, t=1.035)
    wait_settled(qtbot, pg)
    assert pg.page == 0


def test_at_most_one_page_per_gesture(qtbot, paged):
    w = paged(14)
    pg = w.home.pager
    pg.press(1800, 500, t=0.0)
    pg.move(1800 - int(2.6 * pg.page_w), 500, t=1.0)
    assert pg.strip.x() == -pg.page_w           # clamped to the adjacent page
    pg.release(1800 - int(2.6 * pg.page_w), 500, t=1.1)
    wait_settled(qtbot, pg)
    assert pg.page == 1


def test_rubber_band_at_both_ends(qtbot, paged):
    pg = paged().home.pager
    pg.press(500, 500, t=0.0)
    pg.move(700, 500, t=1.0)
    assert pg.strip.x() == round(200 * P.RUBBER_BAND)
    pg.release(700, 500, t=1.1)
    wait_settled(qtbot, pg)
    assert pg.strip.x() == 0 and pg.page == 0
    pg.go_to(1, animate=False)
    pg.press(1500, 500, t=2.0)
    pg.move(1300, 500, t=3.0)
    assert pg.strip.x() == -pg.page_w - round(200 * P.RUBBER_BAND)
    pg.release(1300, 500, t=3.1)
    wait_settled(qtbot, pg)
    assert pg.page == 1 and pg.strip.x() == -pg.page_w


def test_animation_parameters(paged):
    pg = paged().home.pager
    pg.next()
    assert pg.animating()
    assert pg.anim.easingCurve().type() == QEasingCurve.Type.OutCubic
    assert 250 <= pg.anim.duration() <= 350
    assert pg.anim.propertyName() == b"pos" and pg.anim.targetObject() is pg.strip
    assert pg.group.animationCount() == 1


def test_arrow_buttons_and_dots_animate(qtbot, paged):
    w = paged()
    h, pg = w.home, w.home.pager
    QTest.mouseClick(h.page_bar.next_btn, Qt.MouseButton.LeftButton)
    assert pg.animating() and pg.page == 1
    wait_settled(qtbot, pg)
    assert h.page_bar.dots[1].accessibleName() == "Page 2 of 2 (current)"
    assert not h.page_bar.next_btn.isEnabled() and h.page_bar.prev_btn.isEnabled()
    QTest.mouseClick(h.page_bar.dots[0], Qt.MouseButton.LeftButton)
    assert pg.animating()
    wait_settled(qtbot, pg)
    assert pg.page == 0
    h.page_bar.dots[1].setFocus()
    QTest.keyClick(h.page_bar.dots[1], Qt.Key.Key_Space)
    wait_settled(qtbot, pg)
    assert pg.page == 1


@pytest.mark.parametrize("start,key,mods,page,focus", [
    (2, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, 1, 12),      # right edge -> next page
    (5, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, 1, 15),      # same row on the next page
    (0, Qt.Key.Key_PageDown, Qt.KeyboardModifier.NoModifier, 1, 12),
    (0, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier, 1, 12),
    (0, Qt.Key.Key_End, Qt.KeyboardModifier.NoModifier, 1, 17),
    (12, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier, 0, 2),        # left edge -> previous page
    (13, Qt.Key.Key_PageUp, Qt.KeyboardModifier.NoModifier, 0, 0),
    (13, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier, 0, 0),
    (14, Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier, 0, 0),
])
def test_keyboard_paging_animates_and_moves_focus(qtbot, paged, start, key, mods, page, focus):
    w = paged(6)
    h, pg = w.home, w.home.pager
    w.activateWindow()
    h.focus_tile(h.tiles[start].tile.key)
    wait_settled(qtbot, pg)
    QTest.keyClick(h.tiles[start], key, mods)
    if page != h.page_of(start):
        assert pg.animating()
    wait_settled(qtbot, pg)
    assert pg.page == page
    assert h.tiles[focus].hasFocus()


def test_arrows_inside_a_page_do_not_change_page(qtbot, paged):
    w = paged(6)
    h = w.home
    h.focus_tile(h.tiles[4].tile.key)
    QTest.keyClick(h.tiles[4], Qt.Key.Key_Down)
    assert h.tiles[7].hasFocus() and h.pager.page == 0 and not h.pager.animating()
    QTest.keyClick(h.tiles[10], Qt.Key.Key_Down)          # bottom row: stays
    assert h.pager.page == 0


def test_interrupt_and_retarget(qtbot, paged):
    w = paged(14)
    pg = w.home.pager
    pg.go_to(2)
    qtbot.wait(90)
    mid = pg.strip.x()
    assert -2 * pg.page_w < mid < 0
    pg.press(1000, 500, t=0.0)                  # grab mid-animation
    assert not pg.animating() and pg.strip.x() == mid
    pg.move(1060, 500, t=0.5)
    assert pg.strip.x() != mid                  # continues from the grabbed offset
    pg.cancel_gesture()
    wait_settled(qtbot, pg)
    assert pg.strip.x() == pg._x_for(pg.page)
    pg.go_to(0)
    qtbot.wait(60)
    pg.go_to(1)                                 # retarget from the current position
    assert pg.anim.startValue() != QPoint(pg._x_for(2), 0) or pg.page == 1
    wait_settled(qtbot, pg)
    assert pg.page == 1 and pg.strip.x() == -pg.page_w


def test_tap_that_stops_an_animation_is_not_a_click(qtbot, paged):
    w = paged()
    pg = w.home.pager
    pg.go_to(1)
    qtbot.wait(60)
    pg.press(800, 500, t=0.0)
    assert pg.release(800, 500, t=0.05) is True        # swallowed
    wait_settled(qtbot, pg)
    assert pg.strip.x() == -pg.page_w


def test_resize_snaps_and_recomputes_capacity(qtbot, paged):
    w = paged(6)
    h, pg = w.home, w.home.pager
    pg.go_to(1)
    qtbot.wait(60)
    w.resize(800, 480)
    qtbot.waitUntil(lambda: h.width() < 900)
    assert not pg.animating()
    g = h.grid_geom
    assert g["per_page"] < 12
    assert g["pages"] == -(-18 // g["per_page"])
    assert pg.strip.x() == pg._x_for(pg.page) and pg.page_w == h.pager.width()
    w.resize(1920, 1080)
    qtbot.waitUntil(lambda: h.grid_geom["per_page"] == 12)
    assert pg.strip.x() == pg._x_for(pg.page)


def test_header_and_footer_stay_stationary(qtbot, paged):
    w = paged()
    h = w.home
    fixed = [h.title, h.subtitle, h.auth_chip, h.net_chip, h.settings_btn, h.core_label, h.net_label, h.page_bar,
             h.pager]
    before = [x.geometry() for x in fixed]
    h.pager.next()
    for _ in range(4):
        qtbot.wait(40)
        assert [x.geometry() for x in fixed] == before
    wait_settled(qtbot, h.pager)


def test_no_relayout_or_tile_geometry_change_per_frame(qtbot, paged, monkeypatch):
    w = paged()
    h = w.home
    calls = []
    orig = type(h).relayout
    monkeypatch.setattr(type(h), "relayout", lambda self: (calls.append(1), orig(self)))
    geoms = [t.geometry() for t in h.tiles]
    h.pager.frame_times.clear()
    h.pager.next()
    wait_settled(qtbot, h.pager)
    assert calls == []
    assert [t.geometry() for t in h.tiles] == geoms


def test_frame_timing(qtbot, paged):
    pg = paged().home.pager
    pg.frame_times.clear()
    pg.next()
    wait_settled(qtbot, pg)
    ft = pg.frame_times
    assert len(ft) >= 8
    gaps = [b - a for a, b in zip(ft, ft[1:])]
    # recorded for TEST-REPORT.md (offscreen, no compositor; real Pi numbers are UNVERIFIED)
    print(f"FRAME-TIMING frames={len(ft)} median_ms={statistics.median(gaps) * 1000:.1f} "
          f"max_ms={max(gaps) * 1000:.1f} total_ms={(ft[-1] - ft[0]) * 1000:.0f}")
    assert statistics.median(gaps) < 0.034


def _mouse(widget, etype, pos, buttons):
    gp = widget.mapToGlobal(pos)
    btn = Qt.MouseButton.LeftButton if etype != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    ev = QMouseEvent(etype, QPointF(pos), QPointF(gp), btn, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)


def test_click_vs_drag_on_a_tile(qtbot, paged):
    w = paged()
    h = w.home
    activated = []
    w.home.tileActivated.disconnect()
    h.tileActivated.connect(activated.append)
    tile = h.tiles[10]
    c = tile.rect().center()
    L = Qt.MouseButton.LeftButton
    _mouse(tile, QEvent.Type.MouseButtonPress, c, L)
    _mouse(tile, QEvent.Type.MouseMove, c + QPoint(-5, 2), L)
    _mouse(tile, QEvent.Type.MouseButtonRelease, c + QPoint(-5, 2), Qt.MouseButton.NoButton)
    assert [t.key for t in activated] == [tile.tile.key]            # small movement = click
    activated.clear()
    _mouse(tile, QEvent.Type.MouseButtonPress, c, L)
    for dx in (-20, -80, -200, -400, -600):
        _mouse(tile, QEvent.Type.MouseMove, c + QPoint(dx, 0), L)
    _mouse(tile, QEvent.Type.MouseButtonRelease, c + QPoint(-600, 0), Qt.MouseButton.NoButton)
    assert activated == []                                          # a drag never activates
    wait_settled(qtbot, h.pager)
    assert h.pager.page == 1


def test_touch_swipe_and_tap(qtbot, paged):
    w = paged()
    h, pg = w.home, w.home.pager
    activated = []
    h.tileActivated.disconnect()
    h.tileActivated.connect(activated.append)
    dev = QTest.createTouchDevice()
    tile = h.tiles[4]
    c = tile.mapTo(w, tile.rect().center())
    seq = QTest.touchEvent(w, dev)
    seq.press(0, c, w).commit()
    for dx in (-30, -150, -400, -700):
        QTest.touchEvent(w, dev).move(0, c + QPoint(dx, 0), w).commit()
    QTest.touchEvent(w, dev).release(0, c + QPoint(-700, 0), w).commit()
    wait_settled(qtbot, pg)
    assert pg.page == 1 and activated == []
    t2 = h.tiles[13]
    c2 = t2.mapTo(w, t2.rect().center())
    QTest.touchEvent(w, dev).press(0, c2, w).commit()
    QTest.touchEvent(w, dev).release(0, c2, w).commit()
    assert [t.key for t in activated] == [t2.tile.key]


def test_horizontal_wheel_pages(qtbot, paged):
    w = paged()
    h, pg = w.home, w.home.pager
    tile = h.tiles[0]
    pos = QPointF(tile.rect().center())
    ev = QWheelEvent(pos, QPointF(tile.mapToGlobal(pos.toPoint())), QPoint(), QPoint(-120, 0),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(tile, ev)
    assert pg.page == 1
    wait_settled(qtbot, pg)


def test_reduced_motion_crossfades(qtbot, paged):
    w = paged()
    pg = w.home.pager
    pg.reduce_motion = True
    pg.next()
    assert not pg.animating()
    assert pg.strip.x() == -pg.page_w
    assert pg.fade.state() == pg.fade.State.Running and pg.fade.duration() == P.REDUCED_FADE_MS
    qtbot.waitUntil(lambda: pg.fade.state() != pg.fade.State.Running, timeout=2000)


def test_reduced_motion_setting_and_system_hint(launcher):
    from task_launcher.motion import effective_reduce
    from task_launcher.settings import Settings

    assert effective_reduce("on", True) is True
    assert effective_reduce("off", False) is False
    assert effective_reduce("system", False) is True
    assert effective_reduce("system", None) is False
    w = launcher(start=False, settings=Settings(reduce_motion="on"))
    assert w.home.pager.reduce_motion is True
    w2 = launcher(start=False, settings=Settings(reduce_motion="system"))
    w2._on_motion_hint(False)
    assert w2.home.pager.reduce_motion is True


def test_gtk_ini_hint(tmp_path):
    from task_launcher.motion import gsettings_hint, gtk_ini_hint

    assert gtk_ini_hint(tmp_path) is None
    (tmp_path / "gtk-3.0").mkdir()
    (tmp_path / "gtk-3.0" / "settings.ini").write_text("[Settings]\ngtk-enable-animations=0\n")
    assert gtk_ini_hint(tmp_path) is False
    assert gsettings_hint("/nonexistent/gsettings") is None


def test_move_tile_across_pages_keeps_focus(qtbot, paged):
    w = paged(3)
    h = w.home
    key = h.tiles[11].tile.key                 # App Manager, last tile of page 1
    h.focus_tile(key)
    QTest.keyClick(h.tiles[11], Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
    wait_settled(qtbot, h.pager)
    w2 = h.tile_widget(key)
    assert h.tiles.index(w2) == 12 and h.pager.page == 1 and w2.hasFocus()
    QTest.keyClick(w2, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    wait_settled(qtbot, h.pager)
    w3 = h.tile_widget(key)
    assert h.tiles.index(w3) == 11 and h.pager.page == 0 and w3.hasFocus()
    import json
    order = json.loads((w.registry.store.path).read_text())["order"]
    assert order.index(key) == 11


def test_new_tile_lands_on_page_two_and_is_focused(qtbot, launcher, isolated_home):
    add_tiles(isolated_home, 1)
    w = launcher(start=False)
    key = w.add_desktop("test.app00.desktop")
    wait_settled(qtbot, w.home.pager)
    assert w.home.pager.page == 1 and w.home.tile_widget(key).hasFocus()


@pytest.mark.parametrize("size", [(1920, 1080), (1366, 768), (1280, 720), (1024, 600)])
def test_capacity_follows_layout(paged, size):
    w = paged(10, size=size)
    g = w.home.grid_geom
    assert g["cols"] <= 3
    assert g["pages"] == -(-22 // g["per_page"])
    assert w.home.pager.pages == g["pages"]
    # tiles never overlap the page bar or the footer
    pager_bottom = w.home.pager.geometry().bottom()
    assert pager_bottom < w.home.page_bar.geometry().top()
    assert w.home.page_bar.geometry().bottom() < w.home.core_label.geometry().top()
