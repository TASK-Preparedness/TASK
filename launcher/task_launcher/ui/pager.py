# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Horizontally paged tile grid (Android-home-screen style).

All pages live side by side in one *strip* widget inside a clipping viewport (this widget). Only the
strip's x position changes while paging, so the header, footer and controls never move, nothing is
re-laid-out per frame and no per-frame allocations happen (tile icons come from a pixmap cache).

* Drag / swipe: the strip follows the pointer 1:1 once the pointer moved more than DRAG_THRESHOLD px
  horizontally (smaller movements stay clicks; a drag never activates a tile). On release it snaps
  to the next/previous page if the drag covered >= SNAP_FRACTION of the page width, or if the
  release velocity is >= FLING_VELOCITY px/s in the drag direction (and the drag covered at least
  FLING_MIN_DISTANCE px); otherwise it springs back. One gesture moves at most one page. Beyond the
  first/last page the strip moves with RUBBER_BAND resistance and springs back.
* Arrows, dots, keyboard and wheel navigation animate the same way.
* Animations: QPropertyAnimation on the strip's ``pos`` inside a QParallelAnimationGroup,
  QEasingCurve.OutCubic, DURATION_MS. Grabbing mid-animation stops it and continues from the current
  offset; a new target retargets from the current position.
* Reduced motion: no slide; the strip is placed at the target and the grid fades in over
  REDUCED_FADE_MS (QGraphicsOpacityEffect), which is short but not a hard cut.
* Resize: running animations are finished (snapped) and the strip is re-aligned to the current page.
"""

import time

from PySide6.QtCore import (QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt,
                            Signal)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

DURATION_MS = 300
REDUCED_FADE_MS = 120
DRAG_THRESHOLD = 12          # px before a press becomes a drag (clicks below this still activate)
SNAP_FRACTION = 0.25         # of the page width
FLING_VELOCITY = 800.0       # px/s
FLING_MIN_DISTANCE = 24      # px
RUBBER_BAND = 0.35           # resistance factor beyond the first/last page
VELOCITY_WINDOW = 0.1        # s of pointer history used for the release velocity


class Strip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)


class PagedGrid(QWidget):
    pageChanged = Signal(int, int)     # current page, page count (after a transition settles)
    tapped = Signal(object)            # widget tapped by touch (no drag)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.strip = Strip(self)
        self.page = 0
        self.pages = 1
        self.page_w = 1
        self.reduce_motion = False
        self.anim = QPropertyAnimation(self.strip, b"pos", self)
        self.anim.setDuration(DURATION_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.group = QParallelAnimationGroup(self)
        self.group.addAnimation(self.anim)
        self.group.finished.connect(self._settled)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self._effect.setEnabled(False)
        self.setGraphicsEffect(self._effect)
        self.fade = QPropertyAnimation(self._effect, b"opacity", self)
        self.fade.setDuration(REDUCED_FADE_MS)
        self.fade.setStartValue(0.35)
        self.fade.setEndValue(1.0)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade.finished.connect(lambda: self._effect.setEnabled(False))
        self._press = None           # (x, y, t, strip_x, source widget)
        self._dragging = False
        self._interrupted = False
        self._samples = []
        self.drags_started = 0
        self.frame_times = []        # monotonic timestamps of animation frames (tests / diagnostics)
        self.anim.valueChanged.connect(lambda _v: self.frame_times.append(time.perf_counter()))

    # ------------------------------------------------------------------ geometry
    def set_pages(self, pages, page_w, strip_h, keep_page=None):
        """Called by the home view after layout: page count, page width, strip height. A real geometry
        change finishes (snaps) a running animation and re-aligns the strip to the current page."""
        pages = max(1, pages)
        if (keep_page is None and pages == self.pages and page_w == self.page_w
                and strip_h == self.strip.height()):
            return
        self.finish_animation()
        self.cancel_gesture_silently()
        self.pages = max(1, pages)
        self.page_w = max(1, page_w)
        self.strip.resize(self.pages * self.page_w, strip_h)
        target = self.page if keep_page is None else keep_page
        self.page = max(0, min(self.pages - 1, target))
        self.strip.move(self._x_for(self.page), 0)

    def _x_for(self, page):
        return -page * self.page_w

    def offset_pages(self):
        """Current position in pages (fractional while dragging/animating)."""
        return -self.strip.x() / self.page_w

    def animating(self):
        return self.group.state() == QParallelAnimationGroup.State.Running

    def finish_animation(self):
        if self.animating():
            self.group.stop()
            self.strip.move(self._x_for(self.page), 0)
        if self.fade.state() == QPropertyAnimation.State.Running:
            self.fade.stop()
            self._effect.setEnabled(False)

    # ------------------------------------------------------------------ navigation
    def go_to(self, page, animate=True):
        """Animate (or, in reduced-motion mode, fade) to ``page``; retargets a running animation."""
        page = max(0, min(self.pages - 1, page))
        changed = page != self.page
        self.page = page
        target = QPoint(self._x_for(page), 0)
        self.group.stop()
        if self.reduce_motion or not animate:
            self.strip.move(target)
            if self.reduce_motion and changed and animate:
                self._effect.setEnabled(True)
                self.fade.stop()
                self.fade.start()
            self._settled()
            return
        if self.strip.pos() == target:
            self._settled()
            return
        self.anim.setStartValue(self.strip.pos())
        self.anim.setEndValue(target)
        self.anim.setDuration(DURATION_MS)
        self.group.start()

    def next(self):
        self.go_to(self.page + 1)

    def prev(self):
        self.go_to(self.page - 1)

    def _settled(self):
        self.pageChanged.emit(self.page, self.pages)

    # ------------------------------------------------------------------ gestures
    def press(self, x, y, source=None, t=None):
        t = time.monotonic() if t is None else t
        self._interrupted = self.animating()
        if self._interrupted:
            self.group.stop()        # grab mid-animation: continue from the current offset
        self._press = (x, y, t, self.strip.x(), source)
        self._dragging = False
        self._samples = [(t, x)]

    def move(self, x, y, t=None):
        """Returns True once the gesture is a drag (the caller then swallows the event)."""
        if self._press is None:
            return False
        t = time.monotonic() if t is None else t
        px, py, _t0, sx, _src = self._press
        dx = x - px
        if not self._dragging:
            if abs(dx) < DRAG_THRESHOLD or abs(dx) < abs(y - py):
                return False
            self._dragging = True
            self.drags_started += 1
        self._samples.append((t, x))
        self._samples = [s for s in self._samples if t - s[0] <= VELOCITY_WINDOW] or self._samples[-1:]
        # one gesture spans at most one page from where it started
        start_page = round(-sx / self.page_w)
        raw = sx + dx
        lo = self._x_for(min(self.pages - 1, start_page + 1))
        hi = self._x_for(max(0, start_page - 1))
        # beyond the adjacent page: hard stop; beyond the first/last page: rubber band
        if raw > hi:
            raw = hi + (raw - hi) * RUBBER_BAND if start_page == 0 else hi
        elif raw < lo:
            raw = lo + (raw - lo) * RUBBER_BAND if start_page >= self.pages - 1 else lo
        self.strip.move(int(round(raw)), 0)
        return True

    def velocity(self):
        if len(self._samples) < 2:
            return 0.0
        (t0, x0), (t1, x1) = self._samples[0], self._samples[-1]
        return (x1 - x0) / (t1 - t0) if t1 > t0 else 0.0

    def release(self, x, y, t=None):
        """End a gesture. Returns True if it was a drag (the caller must not treat it as a click)."""
        if self._press is None:
            return False
        if t is not None or x is not None:
            self.move(x, y, t)
        was_drag = self._dragging
        px, _py, _t0, sx, _src = self._press
        self._press, self._dragging = None, False
        if not was_drag:
            if self.strip.x() != self._x_for(self.page):
                self.go_to(self.page)       # a tap that stopped an animation: finish settling
            # a tap that only stopped a moving page is not a click on a tile
            return self._interrupted
        start_page = round(-sx / self.page_w)
        moved = self.strip.x() - sx           # >0 = dragged right = previous page
        v = self.velocity()
        target = start_page
        if abs(moved) >= SNAP_FRACTION * self.page_w or (abs(v) >= FLING_VELOCITY and abs(moved) >= FLING_MIN_DISTANCE
                                                          and (v > 0) == (moved > 0)):
            target = start_page - 1 if moved > 0 else start_page + 1
        self.go_to(target)
        return True

    def cancel_gesture_silently(self):
        self._press, self._dragging = None, False

    def cancel_gesture(self):
        if self._press is not None:
            self._press, self._dragging = None, False
            self.go_to(self.page)

    # ------------------------------------------------------------------ event plumbing
    def watch(self, widget):
        """Route mouse/touch gestures that start on a tile (or the strip) through the pager."""
        widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            p = ev.globalPosition()
            self.press(p.x(), p.y(), obj)
            return False
        if et == QEvent.Type.MouseMove and self._press is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            p = ev.globalPosition()
            if self.move(p.x(), p.y()):
                if hasattr(obj, "setDown"):
                    obj.setDown(False)
                return True
            return False
        if et == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            p = ev.globalPosition()
            if self.release(p.x(), p.y()):
                if hasattr(obj, "setDown"):
                    obj.setDown(False)
                return True      # a drag never becomes a click
            return False
        if et in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            return self._touch(obj, ev)
        if et == QEvent.Type.Wheel:
            return self._wheel(ev)
        return False

    def _touch(self, obj, ev):
        pts = ev.points()
        if not pts:
            return True
        p = pts[0].globalPosition()
        et = ev.type()
        if et == QEvent.Type.TouchBegin:
            self.press(p.x(), p.y(), obj)
        elif et == QEvent.Type.TouchUpdate:
            self.move(p.x(), p.y())
        elif et == QEvent.Type.TouchEnd:
            src = self._press[4] if self._press else None
            if not self.release(p.x(), p.y()) and src is not None and src is not self.strip:
                self.tapped.emit(src)
        else:
            self.cancel_gesture()
        ev.accept()
        return True

    _wheel_acc = 0

    def _wheel(self, ev):
        d = ev.angleDelta()
        delta = d.x() if abs(d.x()) > abs(d.y()) else (d.y() if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0)
        if not delta or self.pages <= 1:
            return False
        self._wheel_acc += delta
        if abs(self._wheel_acc) >= 120:
            step = -1 if self._wheel_acc > 0 else 1
            self._wheel_acc = 0
            self.go_to(self.page + step)
        return True

    def mousePressEvent(self, ev):
        self.eventFilter(self, ev)

    def mouseMoveEvent(self, ev):
        self.eventFilter(self, ev)

    def mouseReleaseEvent(self, ev):
        self.eventFilter(self, ev)

    def event(self, ev):
        if ev.type() in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd,
                         QEvent.Type.TouchCancel):
            return self._touch(self, ev)
        if ev.type() == QEvent.Type.Wheel:
            if self._wheel(ev):
                return True
        return super().event(ev)
