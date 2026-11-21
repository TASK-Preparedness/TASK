# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Painted widgets of the home view: header chips and tiles (approved reference look)."""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from task_launcher import icons
from task_launcher.fonts import font
from task_launcher.theme import C
from task_launcher.ui.iconcache import paint_icon


class _FocusVisible:
    """':focus-visible' behaviour: the focus ring is drawn once the keyboard is used and hidden again
    after a mouse/touch press, so a mouse user does not see a ring on the start-up focus widget."""
    keyboard = False


def focus_visible(widget) -> bool:
    return widget.hasFocus() and _FocusVisible.keyboard


def set_keyboard_mode(on: bool):
    if _FocusVisible.keyboard != on:
        _FocusVisible.keyboard = on
        from PySide6.QtWidgets import QApplication

        fw = QApplication.focusWidget()
        if fw is not None:
            fw.update()


def rrect(p, r, radius, fill=None, pen=None):
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    if fill:
        p.fillPath(path, QColor(fill))
    if pen:
        p.setPen(pen)
        p.drawPath(path)


class ChipButton(QAbstractButton):
    """Header control: icon + optional text, rounded, focus ring, >= 48 px target."""

    def __init__(self, icon_name, text="", accessible="", filled=True, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.icon_colour = C["text"]
        self.text_colour = C["text"]
        self.filled = filled
        self.h = 56
        self.text_px = 18
        self.icon_px = 28
        self.setText(text)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(accessible or text)

    def set_metrics(self, h, text_px, icon_px):
        self.h, self.text_px, self.icon_px = h, text_px, icon_px
        self.updateGeometry()
        self.update()

    def set_content(self, icon_name, text, colour=None):
        self.icon_name = icon_name
        self.setText(text)
        self.text_colour = colour or C["text"]
        self.icon_colour = colour or C["text"]
        if text:
            self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def text_width(self):
        return QFontMetricsF(font(self.text_px)).horizontalAdvance(self.text()) if self.text() else 0

    def sizeHint(self):
        pad = round(self.h * 0.28)
        if not self.text():
            return QSize(self.h, self.h)
        return QSize(int(pad + self.icon_px + pad * 0.75 + self.text_width() + pad + 1), self.h)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = round(self.h * 0.25)
        fill = C["surface_hover"] if self.underMouse() or self.isDown() else (C["surface"] if self.filled else None)
        rrect(p, r, radius, fill=fill, pen=QPen(QColor(C["border"]), 1))
        if focus_visible(self):
            rrect(p, r, radius, pen=QPen(QColor(C["accent"]), 3))
        pad = round(self.h * 0.28)
        if not self.text():
            s = self.icon_px
            icons.paint(p, self.icon_name, QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s), self.icon_colour)
            return
        icons.paint(p, self.icon_name, QRectF(pad, (self.height() - self.icon_px) / 2, self.icon_px, self.icon_px),
                    self.icon_colour)
        p.setFont(font(self.text_px))
        p.setPen(QColor(self.text_colour))
        x = pad + self.icon_px + pad * 0.75
        p.drawText(QRectF(x, 0, self.width() - x, self.height()), int(Qt.AlignmentFlag.AlignVCenter), self.text())


STATE_STYLE = {
    # status: (state colour, icon colour, name colour, border colour, muted)
    "Installed": (C["text2"], C["text"], C["text"], C["border"], False),
    "Available": (C["text2"], C["text"], C["text"], C["border"], False),
    "Running": (C["ok"], C["text"], C["text"], C["running_border"], False),
    "Starting": (C["text2"], C["text"], C["text"], C["border"], False),
    "Planned": (C["muted"], C["muted_icon"], C["muted"], C["border_muted"], True),
    "Disabled": (C["muted"], C["muted_icon"], C["muted"], C["border_muted"], True),
    "Unavailable": (C["warn"], "#8A8F96", C["text2"], C["border"], False),
    "Error": (C["err"], C["text"], C["text"], C["error_border"], False),
    "SignIn": (C["text2"], "#8A8F96", C["text2"], C["border"], False),
}


class TileButton(QAbstractButton):
    """One dashboard tile. The widget rect includes the focus-ring margin around the tile."""

    activated = Signal(object)
    menuRequested = Signal(object, object)   # tile widget, global pos (or None for keyboard)

    def __init__(self, tile, parent=None):
        super().__init__(parent)
        self.tile = tile
        self.status = tile.status
        self.state_line = ""
        self.ready_line = ""
        self.ready_level = "muted"
        self.style_key = "Available"
        self.t = None
        self.compact = False
        self.ring = 9
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.clicked.connect(lambda: self.activated.emit(self))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.menuRequested.emit(self, self.mapToGlobal(pos)))

    def set_state(self, style_key, line, ready=None):
        """ready: (text, level) secondary readiness line (Phase 4A) or None."""
        self.style_key, self.state_line = style_key, line
        self.ready_line, self.ready_level = (ready if ready else ("", "muted"))
        desc = line or self.tile.status
        if self.ready_line:
            desc += f"; {self.ready_line}"
        self.setAccessibleName(self.tile.name)
        self.setAccessibleDescription(f"{self.tile.name}, {desc}")
        self.setToolTip(f"{self.tile.name}" + (f" — {line}" if line else "") +
                        (f"\n{self.ready_line}" if self.ready_line else "") +
                        (f"\n{self.tile.description}" if self.tile.description else ""))
        self.update()

    def set_metrics(self, t: dict, compact: bool):
        self.t, self.compact = t, compact
        self.ring = t["focus_offset"] + 3
        self.update()

    def tile_rect(self):
        r = self.ring
        return QRectF(r, r, self.width() - 2 * r, self.height() - 2 * r)

    def name_font(self):
        return font(self.t["name"], QFont.Weight.DemiBold)

    def state_font(self):
        return font(self.t["state"])

    def fitted_state_line(self):
        """The state line, or for a too-long "Available — <variant>" line just the variant, so the
        important part (e.g. "FoxtrotGPS (fallback)") is never elided away. Full text stays in the
        tooltip and accessible description."""
        line = self.state_line
        if self.t is None or not line.startswith("Available — "):
            return line
        _, state_r, _ = self.text_rects()
        if state_r is None or QFontMetricsF(self.state_font()).horizontalAdvance(line) <= state_r.width():
            return line
        return line[len("Available — "):]

    def ready_font(self):
        return font(self.t["state"] - 2)

    def _ready_h(self):
        return self.t["state_line"] - 4 if self.ready_line else 0

    def ready_rect(self):
        """Rect of the readiness line (None without one)."""
        if not self.ready_line or self.t is None:
            return None
        name, state, icon = self.text_rects()
        below = state if state is not None else name
        return QRectF(below.left(), below.bottom() + 2, below.width(), self._ready_h())

    def text_rects(self):
        """(name rect, state rect or None, icon rect) in widget coordinates (used by clipping tests)."""
        t, r = self.t, self.tile_rect()
        isz = t["icon"]
        if self.compact:
            pad = round(isz * 0.4)
            icon = QRectF(r.left() + pad, r.center().y() - isz / 2, isz, isz)
            tx = icon.right() + t["icon_gap"]
            w = r.right() - tx - pad / 2
            rh = self._ready_h()
            if self.state_line or rh:
                total = t["name_line"] + ((2 + t["state_line"]) if self.state_line else 0) + ((2 + rh) if rh else 0)
                y = r.center().y() - total / 2
                name = QRectF(tx, y, w, t["name_line"])
                state = QRectF(tx, y + t["name_line"] + 2, w, t["state_line"]) if self.state_line else None
                return name, state, icon
            return QRectF(tx, r.top(), w, r.height()), None, icon
        block = isz + t["icon_gap"] + t["name_line"] + ((4 + t["state_line"]) if self.state_line else 0) + \
            ((2 + self._ready_h()) if self.ready_line else 0)
        y = r.center().y() - block / 2
        icon = QRectF(r.center().x() - isz / 2, y, isz, isz)
        y += isz + t["icon_gap"]
        name = QRectF(r.left() + 8, y, r.width() - 16, t["name_line"])
        state = QRectF(r.left() + 8, y + t["name_line"] + 4, r.width() - 16, t["state_line"]) if self.state_line else None
        return name, state, icon

    def elided_name(self):
        name_r, _, _ = self.text_rects()
        fm = QFontMetricsF(self.name_font())
        return fm.elidedText(self.tile.name, Qt.TextElideMode.ElideRight, name_r.width())

    def paintEvent(self, _e):
        if self.t is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        scol, icol, ncol, bcol, muted = STATE_STYLE.get(self.style_key, STATE_STYLE["Installed"])
        r = self.tile_rect()
        hover = self.underMouse() and not muted
        rrect(p, r, self.t["radius"], fill=C["surface_hover"] if hover or self.isDown() else C["surface"],
              pen=QPen(QColor(bcol), 1))
        if focus_visible(self):
            off = self.t["focus_offset"]
            rrect(p, r.adjusted(-off, -off, off, off), self.t["radius"] + off - 1, pen=QPen(QColor(C["accent"]), 3))
        name_r, state_r, icon_r = self.text_rects()
        paint_icon(p, self.tile.icon, icon_r, icol, muted=muted)
        align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if self.compact else Qt.AlignmentFlag.AlignHCenter)
        p.setFont(self.name_font())
        p.setPen(QColor(ncol))
        p.drawText(name_r, int(align), self.elided_name())
        if state_r is not None:
            p.setFont(self.state_font())
            p.setPen(QColor(scol))
            fm = QFontMetricsF(self.state_font())
            p.drawText(state_r, int(align), fm.elidedText(self.fitted_state_line(), Qt.TextElideMode.ElideRight,
                                                          state_r.width()))
        ready_r = self.ready_rect()
        if ready_r is not None:
            p.setFont(self.ready_font())
            p.setPen(QColor({"ok": C["ok"], "warn": C["warn"]}.get(self.ready_level, C["text2"])))
            fm = QFontMetricsF(self.ready_font())
            p.drawText(ready_r, int(align), fm.elidedText(self.ready_line, Qt.TextElideMode.ElideRight, ready_r.width()))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            self.activated.emit(self)
            return
        if e.key() == Qt.Key.Key_Menu or (e.key() == Qt.Key.Key_F10 and e.modifiers() == Qt.KeyboardModifier.ShiftModifier):
            self.menuRequested.emit(self, None)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.raise_()
        super().focusInEvent(e)


class Dot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.colour = C["text2"]

    def set_colour(self, colour):
        self.colour = colour
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.colour))
        d = min(self.width(), self.height())
        p.drawEllipse(QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d))
