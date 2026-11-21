# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""The home view: header (title, subtitle, identity chip, network chip, Settings), the tile grid
(3 columns at 1920×1080; further tiles go onto horizontally animated pages, ui/pager.py) and the footer
(task-core indicator left; internet status + 'Offline-first' motto right).

Geometry is computed by layout.layout() for the real widget size, so it follows the window's
actual client area (whatever labwc's panel and decorations leave), never a hard-coded size.
"""

import math

from PySide6.QtCore import QEvent, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from task_launcher import icons
from task_launcher.fonts import font
from task_launcher.layout import layout
from task_launcher.theme import C
from task_launcher.ui.pager import PagedGrid
from task_launcher.ui.widgets import ChipButton, Dot, TileButton, focus_visible

FIT_TILES = 12   # tiles are sized for the approved 3×4 page; more tiles go to further pages


class DotButton(QAbstractButton):
    """Page indicator dot: focusable, accessible name 'Page i of n'."""

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.current = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = 12 if self.current else 9
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["text"] if self.current else C["muted_icon"]))
        p.drawEllipse(QPointF(self.width() / 2, self.height() / 2), d / 2, d / 2)
        if focus_visible(self):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(C["accent"]), 2))
            p.drawEllipse(QPointF(self.width() / 2, self.height() / 2), 11, 11)


class PageBar(QWidget):
    """‹ previous · page dots · next › — every control animates the page change."""

    pageRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prev_btn = ChipButton("chevron-left", "", accessible="Previous page", filled=False, parent=self)
        self.next_btn = ChipButton("chevron-right", "", accessible="Next page", filled=False, parent=self)
        self.prev_btn.clicked.connect(lambda: self.pageRequested.emit(self.page - 1))
        self.next_btn.clicked.connect(lambda: self.pageRequested.emit(self.page + 1))
        self.dots = []
        self.page, self.pages = 0, 1

    def set_pages(self, page, pages, h):
        self.page, self.pages = page, pages
        while len(self.dots) < pages:
            d = DotButton(len(self.dots), self)
            d.clicked.connect(lambda _c=False, i=len(self.dots): self.pageRequested.emit(i))
            d.show()
            self.dots.append(d)
        while len(self.dots) > pages:
            self.dots.pop().deleteLater()
        dot_w = 28
        total = h + 8 + pages * dot_w + 8 + h
        x = (self.width() - total) // 2
        self.prev_btn.set_metrics(h, 16, round(h * 0.55))
        self.next_btn.set_metrics(h, 16, round(h * 0.55))
        self.prev_btn.setGeometry(x, 0, h, h)
        x += h + 8
        for i, d in enumerate(self.dots):
            d.current = i == page
            d.setAccessibleName(f"Page {i + 1} of {pages}" + (" (current)" if i == page else ""))
            d.setGeometry(x + i * dot_w, 0, dot_w, h)
            d.update()
        self.next_btn.setGeometry(x + pages * dot_w + 8, 0, h, h)
        self.prev_btn.setEnabled(page > 0)
        self.next_btn.setEnabled(page < pages - 1)


class HomeView(QWidget):
    tileActivated = Signal(object)                 # Tile
    tileMenu = Signal(object, object)              # TileButton, global pos or None
    moveRequested = Signal(str, int)               # tile key, delta (index positions)
    removeRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(C["bg"]))
        self.setPalette(pal)
        self.mode, self.scale = "auto", 1.0
        self.L = None
        self.title = QLabel("", self)
        self.subtitle = QLabel("", self)
        self.title.setStyleSheet(f"color: {C['text']}; background: transparent;")
        self.subtitle.setStyleSheet(f"color: {C['text2']}; background: transparent;")
        self.title.setAccessibleName("Title")
        self.auth_chip = ChipButton("circle-user", "Public · Sign in", parent=self)
        self.net_chip = ChipButton("wifi", "Network —", filled=False, parent=self)
        self.net_chip.icon_colour = self.net_chip.text_colour = C["text2"]
        self.settings_btn = ChipButton("settings", "", accessible="Settings", parent=self)
        self.pager = PagedGrid(self)
        self.grid = self.pager.strip
        self.pager.pageChanged.connect(self._on_page_changed)
        self.pager.tapped.connect(lambda w: self.tileActivated.emit(w.tile) if isinstance(w, TileButton) else None)
        self.page_bar = PageBar(self)
        self.page_bar.pageRequested.connect(self.pager.go_to)
        self.page_bar.hide()
        self.grid_geom = None
        self.dot = Dot(self)
        self.core_label = QLabel("T.A.S.K. Core · connecting…", self)
        self.core_label.setStyleSheet(f"color: {C['text']}; background: transparent;")
        self.db_icon = QLabel(self)
        self.db_icon.setStyleSheet("background: transparent;")
        self.net_label = QLabel(self)
        self.net_label.setStyleSheet("background: transparent;")
        self.net_label.setTextFormat(Qt.TextFormat.RichText)
        self.internet_text = "Internet: unknown"
        self.notice = QLabel(self)
        self.notice.setWordWrap(True)
        self.notice.hide()
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self.notice.hide)
        self.tiles = []             # TileButton list in display order
        self.set_internet("unknown")
        self.setTabOrder(self.auth_chip, self.net_chip)
        self.setTabOrder(self.net_chip, self.settings_btn)

    # ------------------------------------------------------------------ content
    def set_branding(self, title, subtitle):
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.title.setAccessibleName(title)
        self.relayout()

    def set_core(self, text, colour_token):
        self.core_label.setText(text)
        self.core_label.setAccessibleName(text)
        self.dot.set_colour(C.get(colour_token, C["text2"]))
        self.dot.setAccessibleName(text)
        self.relayout()

    def set_internet(self, state):
        self.internet_text = f"Internet: {state}"
        self.net_label.setText(f"<span style='color:{C['text2']}'>{self.internet_text}</span>"
                               f"<span style='color:{C['muted']}'> · Offline-first</span>")
        self.net_label.setAccessibleName(f"{self.internet_text} · Offline-first")
        self.relayout()

    def footer_right_plain(self):
        return f"{self.internet_text} · Offline-first"

    def show_notice(self, severity, text, ms=10000):
        colour = {"error": C["err"], "warning": C["warn"]}.get(severity, C["text"])
        self.notice.setText(text)
        self.notice.setStyleSheet(f"background: {C['surface']}; color: {colour}; border: 1px solid {C['border']};"
                                  f" border-radius: 8px; padding: 8px 14px;")
        self.notice.setAccessibleName(text)
        self.notice.show()
        self.notice.raise_()
        self.relayout()
        self._notice_timer.start(ms)

    def set_tiles(self, tiles):
        focus_key = None
        for w in self.tiles:
            if w.hasFocus():
                focus_key = w.tile.key
        for w in self.tiles:
            w.hide()
            w.deleteLater()
        self.tiles = []
        prev = self.settings_btn
        for t in tiles:
            w = TileButton(t, self.grid)
            w.activated.connect(lambda btn: self.tileActivated.emit(btn.tile))
            w.menuRequested.connect(self.tileMenu.emit)
            w.installEventFilter(self)
            self.pager.watch(w)
            self.setTabOrder(prev, w)
            prev = w
            self.tiles.append(w)
            w.show()
        self.relayout()
        if focus_key:
            self.focus_tile(focus_key)

    def tile_widget(self, key):
        for w in self.tiles:
            if w.tile.key == key:
                return w
        return None

    def focus_tile(self, key):
        w = self.tile_widget(key)
        if w is not None:
            self._goto_tile(self.tiles.index(w))

    def set_layout_mode(self, mode, scale):
        self.mode, self.scale = mode, scale
        self.relayout()

    # ------------------------------------------------------------------ geometry
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def relayout(self):
        W, H = self.width(), self.height()
        if W <= 0 or H <= 0:
            return
        L = layout(W, H, self.scale, self.mode, n=min(FIT_TILES, max(1, len(self.tiles) or FIT_TILES)))
        self.L = L
        px, tp = L["px"], L["tp"]
        compact = L["compact"]
        cw = L["content_w"]
        x0 = (W - cw) // 2
        y = px["margin_top"]
        hh = px["header"]
        # header controls (right)
        ch = tp["chip_h"]
        for chip in (self.auth_chip, self.net_chip, self.settings_btn):
            chip.set_metrics(ch, tp["chip_text"], tp["chip_icon"])
        gap = round(14 * self.scale) if not compact else round(10 * self.scale)
        by = y + (hh - ch) // 2
        bx = x0 + cw - ch
        self.settings_btn.setGeometry(bx, by, ch, ch)
        nw = self.net_chip.sizeHint().width()
        bx -= nw + gap
        self.net_chip.setGeometry(bx, by, nw, ch)
        aw = self.auth_chip.sizeHint().width()
        bx -= aw + gap
        self.auth_chip.setGeometry(bx, by, aw, ch)
        chips_left = bx
        # title / subtitle (left), never overlapping the chips
        tf = font(tp["title"], QFont.Weight.Bold)
        sf = font(tp["subtitle"])
        self._style_label(self.title, tf, C["text"])
        self._style_label(self.subtitle, sf, C["text2"])
        avail = max(0, chips_left - x0 - round(16 * self.scale))
        tfm, sfm = QFontMetricsF(tf), QFontMetricsF(sf)
        tw = min(avail, math.ceil(tfm.horizontalAdvance(self.title.text())) + 2)
        if compact:
            self.title.setGeometry(x0, y + (hh - tp["title_line"]) // 2, tw, tp["title_line"])
            sx = x0 + tw + round(14 * self.scale)
            sw = max(0, chips_left - sx - round(16 * self.scale))
            full = math.ceil(sfm.horizontalAdvance(self.subtitle.text())) + 2
            self.subtitle.setVisible(full <= sw)       # dropped rather than clipped or overlapping
            self.subtitle.setGeometry(sx, y + (hh - tp["subtitle_line"]) // 2 + 2, min(full, sw), tp["subtitle_line"])
        else:
            self.title.setGeometry(x0, y, tw, tp["title_line"])
            air = round((8 if L["effective"] == "large" else 4) * self.scale)
            full = math.ceil(sfm.horizontalAdvance(self.subtitle.text())) + 2
            self.subtitle.setVisible(True)
            self.subtitle.setGeometry(x0, y + tp["title_line"] + air, min(full, max(avail, 0)), tp["subtitle_line"])
        self._divider_y = [y + hh + px["gap_hg"] // 2]
        # footer
        fh = px["footer"]
        fy = H - px["margin_bottom"] - fh
        self._divider_y.append(fy)
        self._content = (x0, cw)
        dot = tp["dot"]
        self.dot.setGeometry(x0 + 2, fy + (fh - dot) // 2, dot, dot)
        ff = font(tp["footer_text"])
        self._style_label(self.core_label, ff, C["text"])
        self._style_label(self.net_label, ff, C["text2"])
        ffm = QFontMetricsF(ff)
        rw = math.ceil(ffm.horizontalAdvance(self.footer_right_plain())) + 4
        isz = round(22 * self.scale) if not compact else round(18 * self.scale)
        self.net_label.setGeometry(x0 + cw - rw, fy, rw, fh)
        self.db_icon.setGeometry(x0 + cw - rw - isz - round(10 * self.scale), fy + (fh - isz) // 2, isz, isz)
        self.db_icon.setPixmap(self._icon_pixmap("database", isz, C["text2"]))
        lx = x0 + dot + round(12 * self.scale)
        lw = min(math.ceil(ffm.horizontalAdvance(self.core_label.text())) + 4,
                 max(0, self.db_icon.x() - lx - round(16 * self.scale)))
        self.core_label.setGeometry(lx, fy, lw, fh)
        # grid: horizontally paged (ui/pager.py); tiles sized for the approved 3×4 page
        gy = y + hh + px["gap_hg"]
        gh = fy - px["gap_gf"] - gy
        ring = tp["focus_offset"] + 3
        self.grid_geom = self._page_geometry(L, gh, len(self.tiles), ring)
        g = self.grid_geom
        bar_h = g["bar_h"]
        gh2 = gh - (bar_h + g["bar_gap"] if bar_h else 0)
        page_w = cw + 2 * ring
        self.pager.setGeometry(x0 - ring, gy - ring, page_w, gh2 + 2 * ring)
        self.pager.set_pages(g["pages"], page_w, gh2 + 2 * ring)
        tw_, th_, cols, per = g["tile_w"], g["tile_h"], g["cols"], g["per_page"]
        gcol, grow = px["gutter_col"], px["gutter_row"]
        for i, w in enumerate(self.tiles):
            pg, k = divmod(i, per)
            r, c = divmod(k, cols)
            w.set_metrics(tp, compact)
            w.setGeometry(pg * page_w + c * (tw_ + gcol), r * (th_ + grow), tw_ + 2 * ring, th_ + 2 * ring)
        self.page_bar.setVisible(bar_h > 0)
        if bar_h:
            self.page_bar.setGeometry(x0, gy + gh2 + g["bar_gap"], cw, bar_h)
            self.page_bar.set_pages(self.pager.page, g["pages"], bar_h)
        if self.notice.isVisible():
            nw_ = min(cw, round(900 * self.scale))
            self.notice.setFixedWidth(nw_)
            self.notice.adjustSize()
            self.notice.move(x0 + (cw - nw_) // 2, gy)
        self.update()

    @staticmethod
    def _style_label(label, f, colour):
        """Labels carry their font in their own stylesheet so the application stylesheet (used by the
        dialogs) cannot override the home-view typography."""
        weight = int(f.weight()) if hasattr(f.weight(), "__int__") else f.weight().value
        ss = (f"color: {colour}; background: transparent; font-family: '{f.family()}'; "
              f"font-size: {f.pixelSize()}px; font-weight: {weight};")
        if label.styleSheet() != ss:
            label.setStyleSheet(ss)
        label.setFont(f)

    def _page_geometry(self, L, gh, n, ring=0):
        """Tile size, rows per page, page count. Tiles keep the size of the approved 12-tile page; if
        that does not fit (small windows) fewer rows per page are used, never smaller tiles than minH."""
        s = self.scale
        cols = L["cols"]
        tw = L["tile"][0]
        grow = L["px"]["gutter_row"]
        min_h, max_h = L["m"]["minH"] * s, L["m"]["maxH"] * s
        rows_full = math.ceil(FIT_TILES / cols)

        def fit(height):
            th = (height - (rows_full - 1) * grow) / rows_full
            if th >= min_h - 0.01:
                return rows_full, math.floor(min(max_h, th))
            rows = max(1, int((height + grow) // (min_h + grow)))
            return rows, math.floor(min(max_h, max(min_h, (height - (rows - 1) * grow) / rows)))

        rows, th = fit(gh)
        bar_h, bar_gap = 0, 0
        if n > rows * cols:
            bar_h = round((32 if L["compact"] else 40) * s)
            bar_gap = max(round(8 * s), ring + 2)   # focus rings of the last row never touch the bar
            rows, th = fit(gh - bar_h - bar_gap)
        per = rows * cols
        pages = max(1, math.ceil(n / per)) if n else 1
        return dict(cols=cols, rows=rows, per_page=per, pages=pages, tile_w=tw, tile_h=th, bar_h=bar_h,
                    bar_gap=bar_gap)

    def page_of(self, key_or_index):
        i = key_or_index if isinstance(key_or_index, int) else next(
            (k for k, w in enumerate(self.tiles) if w.tile.key == key_or_index), 0)
        per = self.grid_geom["per_page"] if self.grid_geom else FIT_TILES
        return i // per

    def _on_page_changed(self, page, pages):
        if self.grid_geom and self.grid_geom["bar_h"]:
            self.page_bar.set_pages(page, pages, self.grid_geom["bar_h"])

    def _goto_tile(self, index):
        index = max(0, min(len(self.tiles) - 1, index))
        w = self.tiles[index]
        pg = self.page_of(index)
        if pg != self.pager.page:
            self.pager.go_to(pg)
            if self.grid_geom and self.grid_geom["bar_h"]:
                self.page_bar.set_pages(pg, self.pager.pages, self.grid_geom["bar_h"])
        w.setFocus(Qt.FocusReason.TabFocusReason)

    def _icon_pixmap(self, name, size, colour):
        from PySide6.QtCore import QRectF

        dpr = self.devicePixelRatioF() or 1.0
        pix = QPixmap(int(size * dpr), int(size * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.paint(p, name, QRectF(0, 0, size, size), colour)
        p.end()
        return pix

    def paintEvent(self, e):
        super().paintEvent(e)
        if not getattr(self, "_content", None):
            return
        p = QPainter(self)
        p.setPen(QPen(QColor(C["divider"]), 1))
        x0, cw = self._content
        for yy in self._divider_y:
            p.drawLine(QPointF(x0, yy + 0.5), QPointF(x0 + cw, yy + 0.5))

    # ------------------------------------------------------------------ keyboard
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and isinstance(obj, TileButton) and obj in self.tiles:
            key, mods = ev.key(), ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            i = self.tiles.index(obj)
            g = self.grid_geom or {"cols": 3, "per_page": FIT_TILES, "pages": 1}
            cols, per = g["cols"], g["per_page"]
            pg, k = divmod(i, per)
            r, c = divmod(k, cols)
            alt = bool(mods & Qt.KeyboardModifier.AltModifier)
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            arrows = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -cols, Qt.Key.Key_Down: cols}
            if key in arrows and alt:
                self.moveRequested.emit(obj.tile.key, arrows[key])
                return True
            if ctrl and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                key = Qt.Key.Key_PageUp if key == Qt.Key.Key_Left else Qt.Key.Key_PageDown
                mods = Qt.KeyboardModifier.NoModifier
            if mods:
                return False
            n = len(self.tiles)
            if key == Qt.Key.Key_Left:
                if c > 0:
                    self._goto_tile(i - 1)
                elif pg > 0:   # grid edge: previous page, same row, last column
                    self._goto_tile((pg - 1) * per + r * cols + cols - 1)
                return True
            if key == Qt.Key.Key_Right:
                if c < cols - 1 and i + 1 < n and (i + 1) // per == pg:
                    self._goto_tile(i + 1)
                elif (pg + 1) * per < n:   # grid edge: next page, same row (clamped), first column
                    self._goto_tile(min(n - 1, (pg + 1) * per + r * cols))
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                j = i + arrows[key]
                if 0 <= j < n and j // per == pg:
                    self._goto_tile(j)
                return True
            if key in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                target = pg + (1 if key == Qt.Key.Key_PageDown else -1)
                if 0 <= target and target * per < n:
                    self._goto_tile(target * per)
                return True
            if key in (Qt.Key.Key_Home, Qt.Key.Key_End) and n:
                self._goto_tile(0 if key == Qt.Key.Key_Home else n - 1)
                return True
            if key == Qt.Key.Key_Delete:
                self.removeRequested.emit(obj.tile.key)
                return True
        if ev.type() == QEvent.Type.FocusIn and isinstance(obj, TileButton) and obj in self.tiles:
            pg = self.page_of(self.tiles.index(obj))
            if pg != self.pager.page:
                self.pager.go_to(pg)
        return super().eventFilter(obj, ev)
