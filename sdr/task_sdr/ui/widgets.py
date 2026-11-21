# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SDR Studio widgets (original QPainter drawing; no code or assets from other SDR programs)."""

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QInputDialog, QWidget

from task_sdr.tuner import DIGITS, DigitTuner

BG, ACCENT, PANEL = "#101722", "#78dce8", "#27374b"


def palette_lut():
    """256-entry RGB ramp BG -> PANEL -> ACCENT -> white (our own ramp)."""
    stops = [(0.0, (0x10, 0x17, 0x22)), (0.35, (0x27, 0x37, 0x4b)), (0.75, (0x78, 0xdc, 0xe8)), (1.0, (255, 255, 255))]
    x = np.linspace(0, 1, 256)
    out = np.zeros((256, 3), np.uint8)
    for c in range(3):
        out[:, c] = np.interp(x, [s[0] for s in stops], [s[1][c] for s in stops])
    return out


LUT = palette_lut()


class TunerWidget(QWidget):
    """Digits GG.MMM.kkk.hhh. Click top half of a digit = +1 in that place, bottom half = -1 (carry/borrow);
    wheel over a digit; keyboard: Left/Right select, Up/Down step, 0-9 type, Enter/F = type a frequency."""
    changed = Signal(object)        # Hz as a Python int; Signal(int) would be 32-bit
    rejected = Signal(str)

    def __init__(self, hz, accepts, why, parent=None):
        super().__init__(parent)
        self.t = DigitTuner(hz, accepts, why)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(64)
        self.setMinimumWidth(460)
        self.setAccessibleName("Frequency tuner")
        self._rects = []

    @property
    def hz(self):
        return self.t.hz

    def set_hz(self, hz, emit=False):
        ok = self.t.set_hz(hz)
        self.update()
        if ok and emit:
            self.changed.emit(self.t.hz)
        elif not ok:
            self.rejected.emit(self.t.last_rejection)
        return ok

    def set_range(self, accepts, why):
        self.t.accepts, self.t.why = accepts, why

    def _layout(self):
        w, h = self.width(), self.height()
        n_sep = 3
        digit_w = min(36.0, (w - 20) / (DIGITS + n_sep * 0.35))
        sep_w = digit_w * 0.35
        x = (w - (DIGITS * digit_w + n_sep * sep_w)) / 2
        rects, seps = [], []
        for i in range(DIGITS):                    # i = 0 is the leftmost (10 GHz) digit
            rects.append(QRectF(x, 4, digit_w, h - 8))
            x += digit_w
            if i in (1, 4, 7):
                seps.append(QRectF(x, 4, sep_w, h - 8))
                x += sep_w
        return rects, seps

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        rects, seps = self._layout()
        self._rects = rects
        f = QFont("monospace")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(int(rects[0].height() * 0.75))
        p.setFont(f)
        text = self.t.text.replace(".", "")
        lead = True
        for i, r in enumerate(rects):
            k = DIGITS - 1 - i
            ch = text[i]
            if ch != "0" or k <= 6:
                lead = False
            if k == self.t.cursor and self.hasFocus():
                p.fillRect(r, QColor(PANEL))
            p.setPen(QColor("#4a5a70" if lead else ACCENT))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, ch)
        small = QFont(f)
        small.setPixelSize(max(8, int(f.pixelSize() * 0.45)))
        p.setFont(small)
        p.setPen(QColor("#6b7d95"))
        for r in seps:
            p.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, "·")
        p.end()

    def digit_at(self, pos):
        if not self._rects:
            self._rects = self._layout()[0]
        for i, r in enumerate(self._rects):
            if r.left() <= pos.x() < r.right():
                return DIGITS - 1 - i, pos.y() < r.center().y()
        return None, None

    def _after(self, ok):
        self.update()
        if ok:
            self.changed.emit(self.t.hz)
        else:
            self.rejected.emit(self.t.last_rejection)
        return ok

    def mousePressEvent(self, e):
        k, top = self.digit_at(e.position())
        if k is None:
            return
        self.t.cursor = k
        self.setFocus()
        self._after(self.t.step(k, +1 if top else -1))

    def wheelEvent(self, e):
        k, _ = self.digit_at(e.position())
        if k is None:
            k = self.t.cursor
        d = e.angleDelta().y()
        if d:
            self._after(self.t.step(k, +1 if d > 0 else -1))

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Left:
            self.t.move_cursor(-1)
            self.update()
        elif key == Qt.Key.Key_Right:
            self.t.move_cursor(+1)
            self.update()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._after(self.t.step(self.t.cursor, +1 if key == Qt.Key.Key_Up else -1))
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self._after(self.t.type_digit(key - Qt.Key.Key_0))
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F):
            self.prompt()
        else:
            super().keyPressEvent(e)

    def prompt(self, text=None):
        if text is None:
            text, ok = QInputDialog.getText(self, "Tune", "Frequency (e.g. 146.52M, 1.2G, 162550000):")
            if not ok:
                return False
        return self._after(self.t.enter(text))


class SpectrumWaterfall(QWidget):
    """Spectrum (top) + waterfall (bottom). Click/drag tunes; the tuned passband is shaded."""
    tuneRequested = Signal(object)  # Hz as a Python int (no 32-bit limit)
    overlayClicked = Signal(object)        # (dataset, item): the window asks for confirmation before tuning
    STRIP_Y0, STRIP_H, HIT_PX = 16, 14, 6

    def __init__(self, rows=240, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.rows = rows
        self.spec = None
        self.wf = None
        self.center_hz, self.rate, self.offset, self.bw = 0, 1, 0, 0
        self.lo, self.hi = -110.0, -20.0
        self.frames = 0
        self.overlay_items = []            # [(dataset, item)] currently in view; reference only

    def set_overlays(self, items):
        self.overlay_items = list(items)
        self.update()

    def hz_to_x(self, hz):
        return (0.5 + (hz - self.center_hz) / max(1, self.rate)) * self.width()

    def overlay_at(self, x, y):
        """(dataset, item) under the pointer in the overlay strip, markers preferred over ranges; else None."""
        if not (self.STRIP_Y0 <= y <= self.STRIP_Y0 + self.STRIP_H) or self.rate <= 1:
            return None
        best = None
        for d, it in self.overlay_items:
            if it.kind == "marker":
                dx = abs(self.hz_to_x(it.freq_hz) - x)
                if dx <= self.HIT_PX and (best is None or best[0] != 0 or dx < best[1]):
                    best = (0, dx, d, it)
            elif best is None and self.hz_to_x(it.start_hz) <= x <= self.hz_to_x(it.end_hz):
                best = (1, 0, d, it)
        return None if best is None else (best[2], best[3])

    def _paint_overlays(self, p, w):
        y0, sh = self.STRIP_Y0, self.STRIP_H
        for d, it in self.overlay_items:
            col = QColor(255, 196, 0) if d.origin == "user" else QColor(170, 140, 255)
            if it.kind == "range":
                x0, x1 = max(0.0, self.hz_to_x(it.start_hz)), min(float(w), self.hz_to_x(it.end_hz))
                c = QColor(col)
                c.setAlpha(70)
                p.fillRect(QRectF(x0, y0, max(1.0, x1 - x0), sh), c)
                p.setPen(col)
                p.drawText(int(x0) + 2, y0 + sh - 3, it.label[:40])
            else:
                x = self.hz_to_x(it.freq_hz)
                p.setPen(QPen(col, 2))
                p.drawLine(int(x), y0, int(x), y0 + sh)
                p.drawText(int(x) + 3, y0 + sh - 3, it.label[:24])

    def set_frame(self, db, center_hz, rate, bandwidth):
        n = len(db)
        if self.wf is None or self.wf.shape[1] != n:
            self.wf = np.zeros((self.rows, n), np.uint8)
        self.wf = np.roll(self.wf, 1, axis=0)
        self.wf[0] = (np.clip((db - self.lo) / (self.hi - self.lo), 0, 1) * 255).astype(np.uint8)
        self.spec, self.center_hz, self.rate, self.bw = db, center_hz, rate, bandwidth
        self.frames += 1
        self.update()

    def x_to_hz(self, x):
        return int(round(self.center_hz + (x / max(1, self.width()) - 0.5) * self.rate))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        w, h = self.width(), self.height()
        top = int(h * 0.35)
        p.setPen(QPen(QColor(PANEL), 1))
        for i in range(1, 6):
            y = top * i / 6
            p.drawLine(0, int(y), w, int(y))
        if self.bw and self.rate:
            bw_px = self.bw / self.rate * w
            p.fillRect(QRectF(w / 2 - bw_px / 2, 0, bw_px, h), QColor(120, 220, 232, 40))
        if self.spec is not None:
            n = len(self.spec)
            step = max(1, n // max(1, w))
            xs = np.arange(0, n, step) / (n - 1) * w
            ys = top - (np.clip(self.spec[::step], self.lo, self.hi) - self.lo) / (self.hi - self.lo) * top
            p.setPen(QPen(QColor(ACCENT), 1))
            p.drawPolyline(QPolygonF([QPointF(float(x), float(y)) for x, y in zip(xs, ys)]))
        if self.wf is not None:
            rgb = np.ascontiguousarray(LUT[self.wf])
            img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format.Format_RGB888)
            p.drawImage(QRectF(0, top, w, h - top), img)
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawLine(w // 2, 0, w // 2, h)
        p.setPen(QColor("#9fb3c8"))
        if self.rate > 1:
            for frac in (0.0, 0.25, 0.5, 0.75):
                x = frac * w
                p.drawText(int(x) + 3, 12, f"{self.x_to_hz(x) / 1e6:.3f}")
        if self.overlay_items:
            self._paint_overlays(p, w)
        p.end()

    def mousePressEvent(self, e):
        if self.rate > 1:
            hit = self.overlay_at(e.position().x(), e.position().y())
            if hit is not None:
                self.overlayClicked.emit(hit)
                return
            self.tuneRequested.emit(self.x_to_hz(e.position().x()))


class SMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 26)
        self.units, self.label, self.dbfs = 0.0, "S0", None

    def set_value(self, label, units, dbfs):
        self.units, self.label, self.dbfs = units, label, dbfs
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PANEL))
        frac = min(1.0, self.units / 15.0)
        p.fillRect(QRectF(0, 0, self.width() * frac, self.height()), QColor(ACCENT))
        p.setPen(QColor(BG if frac > 0.5 else "#ffffff"))
        txt = self.label + (f"  {self.dbfs:.1f} dBFS (uncalibrated)" if self.dbfs is not None else "")
        p.drawText(self.rect().adjusted(6, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, txt)
        p.end()
