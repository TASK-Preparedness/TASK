# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Raster slippy-map widget (own QWidget renderer; no QtLocation, no web engine).

Tile states drawn distinctly — empty is never painted as downloaded:
* **downloaded**: the tile image;
* **overzoom**: a lower-zoom tile scaled up because the exact tile is missing (dashed amber
  border) or because the view is zoomed past the file's maximum zoom (status bar says so);
* **downloading**: inside the region of the running download and not stored yet (dark tile with
  a dashed blue outline);
* **missing coverage**: hatched with "No offline coverage";
* **failed**: download failed for this tile (red cross, "failed");
* **loading**: plain dark tile while the image is read (short).
"""

import math
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from task_maps import tilemath as tm
from task_maps.ui.theme import C
from task_maps.ui.tiles import ABSENT, TileCache

MAX_ZOOM = 20.0
ANCESTOR_DEPTH = 6
HANDLE = 10


class MapView(QWidget):
    cursorMoved = Signal(float, float)          # lat, lon
    viewChanged = Signal()
    mapClicked = Signal(float, float)           # lat, lon (click without drag)
    rectChanged = Signal()                      # download rectangle edited
    userPanned = Signal()
    overzoomChanged = Signal(str)

    def __init__(self, loader, cache_tiles=512, parent=None):
        super().__init__(parent)
        self.loader = loader
        self.loader.loaded.connect(self._on_loaded)
        self.cache = TileCache(cache_tiles)
        self.layer = None                        # layers.Layer
        self.lat, self.lon, self.zoom = 39.5, -98.35, 4.0
        self.failed = set()                      # (z, x, y) of the shown layer
        self.pending_region = None               # (BBox, minz, maxz) of the running download
        self.download_mode = False
        self.rect = None                         # download rectangle: (west, south, east, north) unwrapped lon
        self.waypoints = []
        self.tracks = []
        self.selected_wpt = None
        self.gps = None                          # GpsState
        self.coord_style = "decimal"
        self.overzoom_info = ""
        self.paints = 0
        self.stats = {"downloaded": 0, "overzoom": 0, "pending": 0, "missing": 0, "failed": 0, "loading": 0}
        self._drag = None
        self._press_pos = None
        self._moved = False
        self._vel = QPointF()
        self._last_move = None
        self._kinetic = QTimer(self)
        self._kinetic.setInterval(16)
        self._kinetic.timeout.connect(self._kinetic_step)
        self._pinch = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(200, 200)

    # ------------------------------------------------------------ model
    def set_layer(self, layer):
        self.layer = layer
        self.cache.clear()
        self.loader.new_generation(0)
        self.failed = set()
        self.update()
        self.viewChanged.emit()

    def set_view(self, lat, lon, zoom=None):
        self.lat = tm.clamp_lat(lat)
        self.lon = tm.wrap_lon(lon)
        if zoom is not None:
            self.zoom = max(0.0, min(MAX_ZOOM, zoom))
        self.update()
        self.viewChanged.emit()

    def tiles_committed(self, path, tiles):
        """Live refresh: tiles of ``path`` became readable (called on the GUI thread)."""
        if not self.layer or path != self.layer.path:
            return
        for z, x, y in tiles:
            self.cache.invalidate((z, x, y))
            self.failed.discard((z, x, y))
        if self.layer.maxzoom is None or (tiles and max(t[0] for t in tiles) > (self.layer.maxzoom or -1)):
            self.layer.maxzoom = max([t[0] for t in tiles] + [self.layer.maxzoom or 0])
        if self.layer.minzoom is None or (tiles and min(t[0] for t in tiles) < self.layer.minzoom):
            self.layer.minzoom = min([t[0] for t in tiles] + ([self.layer.minzoom] if self.layer.minzoom is not None else []))
        self.update()

    def _on_loaded(self, path, z, x, y, img, err):
        if not self.layer or path != self.layer.path:
            return
        if img is None and err and err not in ("corrupt", "offline", "missing"):
            self.failed.add((z, x, y))           # network/HTTP error: red cross, retried after the next refresh
            self.cache.store((z, x, y), None)
            self.update()
            return
        if err == "corrupt":
            self.failed.add((z, x, y))
            self.cache.store((z, x, y), None)
        else:
            self.cache.store((z, x, y), img)
        self.update()

    def network_changed(self, online):
        """Automatic online/offline switch: forget 'absent'/failed tiles so they are looked up again."""
        if self.layer is not None and self.layer.kind == "online":
            self.cache.absent.clear()
            self.failed = set()
            self.update()

    def set_overlays(self, entities_by_layer, enabled):
        self.overlays, self.overlay_enabled = entities_by_layer, dict(enabled)
        self.update()

    # ------------------------------------------------------------ geometry
    def level(self):
        if not self.layer or self.layer.maxzoom is None:
            return max(0, min(int(round(self.zoom)), int(MAX_ZOOM)))
        lo = self.layer.minzoom or 0
        return max(lo, min(int(round(self.zoom)), self.layer.maxzoom))

    def center_world(self, z):
        x, y = tm.lonlat_to_world(self.lon, self.lat, z)
        return x * tm.TILE, y * tm.TILE

    def screen_to_lonlat(self, sx, sy):
        cx, cy = self.center_world(self.zoom)
        wx = cx + sx - self.width() / 2
        wy = cy + sy - self.height() / 2
        n = tm.TILE * 2 ** self.zoom
        wy = max(0.0, min(n, wy))
        lon, lat = tm.world_to_lonlat(wx / tm.TILE, wy / tm.TILE, self.zoom)
        return lat, lon

    def lonlat_to_screen(self, lat, lon, wrap=True):
        cx, cy = self.center_world(self.zoom)
        wx, wy = tm.lonlat_to_world(lon, lat, self.zoom)
        wx, wy = wx * tm.TILE, wy * tm.TILE
        if wrap:
            n = tm.TILE * 2 ** self.zoom
            d = wx - cx
            wx -= round(d / n) * n
        return QPointF(wx - cx + self.width() / 2, wy - cy + self.height() / 2)

    def visible_bbox(self):
        lat_n, lon_w = self.screen_to_lonlat(0, 0)
        lat_s, lon_e = self.screen_to_lonlat(self.width(), self.height())
        return tm.BBox(lon_w, lat_s, lon_e, lat_n)

    # ------------------------------------------------------------ painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect_(), QColor(C["map_bg"]))
        self.paints += 1
        for k in self.stats:
            self.stats[k] = 0
        self._paint_tiles(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_tracks(p)
        self._paint_waypoints(p)
        self._paint_overlays(p)
        self._paint_gps(p)
        if self.rect is not None:
            self._paint_rect(p)
        self._paint_scale(p)
        self._paint_attribution(p)
        if not self.layer:
            self._banner(p, "No map loaded — use Maps to download an area or import an MBTiles file")
        p.end()

    def rect_(self):
        return QRectF(0, 0, self.width(), self.height())

    def _paint_tiles(self, p):
        L = self.level()
        ts = tm.TILE * 2 ** (self.zoom - L)
        cx, cy = self.center_world(L)
        cx, cy = cx * ts / tm.TILE, cy * ts / tm.TILE
        ox, oy = self.width() / 2 - cx, self.height() / 2 - cy
        n = 2 ** L
        x0, x1 = math.floor(-ox / ts), math.floor((self.width() - ox) / ts)
        y0, y1 = max(0, math.floor(-oy / ts)), min(n - 1, math.floor((self.height() - oy) / ts))
        info = ""
        if self.layer and self.layer.maxzoom is not None and self.zoom > self.layer.maxzoom + 0.5:
            info = f"Overzoom ×{2 ** (self.zoom - self.layer.maxzoom):.0f} (map data ends at z{self.layer.maxzoom})"
        if info != self.overzoom_info:
            self.overzoom_info = info
            self.overzoomChanged.emit(info)
        font = QFont(self.font())
        font.setPixelSize(12)
        p.setFont(font)
        cxl, cyl = self.width() / 2, self.height() / 2
        if self.layer is not None and self.layer.kind == "online":
            want = set()
            for ty in range(max(0, y0 - 1), min(n - 1, y1 + 1) + 1):
                for tx in range(x0 - 1, x1 + 2):
                    want.add((L, tx % n, ty))
            self.loader.set_wanted(self.layer.path, want)
        order = sorted(((tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)),
                       key=lambda t: (t[0] * ts + ox + ts / 2 - cxl) ** 2 + (t[1] * ts + oy + ts / 2 - cyl) ** 2)
        for tx, ty in order:
            r = QRectF(tx * ts + ox, ty * ts + oy, ts, ts)
            self._paint_tile(p, L, tx % n, ty, r)

    def _paint_tile(self, p, z, x, y, r):
        if not self.layer:
            self._hatch(p, r, "")
            return
        key = (z, x, y)
        got = self.cache.lookup(key)
        if got is not None and got is not ABSENT:
            p.drawImage(r, got)
            if self.overzoom_info:
                # beyond the file's max zoom: the deepest tile is scaled up, marked with an amber dashed edge
                p.setPen(QPen(QColor(C["warn"]), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r.adjusted(1, 1, -1, -1))
                if r.width() >= 300:
                    self._tag(p, r, f"overzoom from z{z}", C["warn"])
                self.stats["overzoom"] += 1
            else:
                self.stats["downloaded"] += 1
            self._overlay_state(p, key, r, fill=False)
            return
        if got is None:
            self.loader.request(self.layer.path, z, x, y)
        # fallback: a lower-zoom ancestor, scaled (only while loading, or dimmed under the missing hatch)
        for d in range(1, ANCESTOR_DEPTH + 1):
            az = z - d
            if az < 0 or (self.layer.minzoom is not None and az < self.layer.minzoom):
                break
            ak = (az, x >> d, y >> d)
            a = self.cache.lookup(ak)
            if a is None:
                if got is ABSENT:
                    self.loader.request(self.layer.path, *ak, front=False)
                continue
            if a is ABSENT:
                continue
            size = tm.TILE / (2 ** d)
            src = QRectF((x % (2 ** d)) * size, (y % (2 ** d)) * size, size, size)
            p.drawImage(r, a, src)
            if got is ABSENT:
                p.fillRect(r, QColor(11, 13, 16, 130))
                self._overlay_state(p, key, r, fill=True, note=f"(z{az} shown)")
            else:
                self.stats["loading"] += 1
            return
        if got is None:
            p.fillRect(r, QColor(C["surface"]))
            self.stats["loading"] += 1
            return
        p.fillRect(r, QColor(C["map_bg"]))
        self._overlay_state(p, key, r, fill=True)

    def _tag(self, p, r, text, color):
        p.setPen(QColor(color))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 12
        br = QRectF(r.left() + 6, r.top() + 6, w, 20)
        p.fillRect(br, QColor(11, 13, 16, 200))
        p.drawText(br, Qt.AlignmentFlag.AlignCenter, text)

    def _overlay_state(self, p, key, r, fill, note=""):
        """Live state of a tile without its own image: failed / downloading (pending) / missing."""
        if key in self.failed:
            if fill:
                self._failed(p, r)
            else:
                self._cross(p, r)
        elif not fill:
            return
        elif self._in_pending(*key):
            self._pending(p, r)
        else:
            self._hatch(p, r, "No offline coverage", note)

    def _in_pending(self, z, x, y):
        if not self.pending_region:
            return False
        bbox, minz, maxz = self.pending_region
        if not (minz <= z <= maxz):
            return False
        y0, y1 = tm.y_range(bbox, z)
        if not (y0 <= y <= y1):
            return False
        return any(a <= x <= b for a, b in tm.x_ranges(bbox, z))

    def _hatch(self, p, r, text, note=""):
        p.fillRect(r, QBrush(QColor(C["hatch"]), Qt.BrushStyle.BDiagPattern))
        p.setPen(QPen(QColor(C["divider"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        self.stats["missing"] += 1
        if text and r.width() >= 120:
            p.setPen(QColor(C["text2"]))
            label = text + ("\n" + note if note else "")
            br = QRectF(r.center().x() - 75, r.center().y() - (20 if note else 11), 150, 40 if note else 22)
            p.fillRect(br, QColor(C["map_bg"]))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, label)

    def _pending(self, p, r):
        p.fillRect(r, QColor(15, 26, 36, 200))
        p.setPen(QPen(QColor(C["pending"]), 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(3, 3, -3, -3))
        self.stats["pending"] += 1
        if r.width() >= 120:
            p.setPen(QColor(C["pending"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "downloading…")

    def _cross(self, p, r):
        p.setPen(QPen(QColor(C["err"]), 2))
        p.drawLine(r.topLeft() + QPointF(8, 8), r.bottomRight() - QPointF(8, 8))
        p.drawLine(r.topRight() + QPointF(-8, 8), r.bottomLeft() + QPointF(8, -8))

    def _failed(self, p, r):
        p.fillRect(r, QColor(30, 16, 18, 210))
        self._cross(p, r)
        self.stats["failed"] += 1
        if r.width() >= 120:
            p.setPen(QColor(C["err"]))
            br = QRectF(r.center().x() - 50, r.center().y() - 11, 100, 22)
            p.fillRect(br, QColor("#1E1012"))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, "failed")

    def _banner(self, p, text):
        f = QFont(self.font())
        f.setPixelSize(15)
        p.setFont(f)
        w = min(self.width() - 40, 640)
        r = QRectF((self.width() - w) / 2, self.height() / 2 - 26, w, 52)
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(QColor(C["surface"]))
        p.drawRoundedRect(r, 8, 8)
        p.setPen(QColor(C["text"]))
        p.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    def _paint_tracks(self, p):
        for t in self.tracks:
            if len(t.points) < 2:
                continue
            path = QPainterPath()
            first = self.lonlat_to_screen(t.points[0].lat, t.points[0].lon)
            path.moveTo(first)
            prev = first
            for pt in t.points[1:]:
                q = self.lonlat_to_screen(pt.lat, pt.lon)
                if abs(q.x() - prev.x()) > self.width():      # wrap jump
                    path.moveTo(q)
                else:
                    path.lineTo(q)
                prev = q
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#000000"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(C["track"]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)

    def _paint_waypoints(self, p):
        f = QFont(self.font())
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        for w in self.waypoints:
            q = self.lonlat_to_screen(w.lat, w.lon)
            if not self.rect_().adjusted(-40, -40, 40, 40).contains(q):
                continue
            sel = w.id == self.selected_wpt
            p.setPen(QPen(QColor("#000000"), 2))
            p.setBrush(QColor(C["accent"] if sel else C["wpt"]))
            path = QPainterPath()
            path.moveTo(q)
            path.lineTo(q + QPointF(-8, -14))
            path.arcTo(QRectF(q.x() - 9, q.y() - 32, 18, 18), 210, -240)
            path.closeSubpath()
            p.drawPath(path)
            label = QRectF(q.x() + 10, q.y() - 30, 220, 18)
            p.setPen(QColor("#000000"))
            p.drawText(label.translated(1, 1), Qt.AlignmentFlag.AlignLeft, w.name)
            p.setPen(QColor(C["text"]))
            p.drawText(label, Qt.AlignmentFlag.AlignLeft, w.name)

    OVERLAY_COLORS = {"aprs": "#e0a030", "mesh": "#40c080", "gmrs": "#c070e0"}

    def _paint_overlays(self, p):
        for name, ents in getattr(self, "overlays", {}).items():
            if not getattr(self, "overlay_enabled", {}).get(name):
                continue
            col = QColor(self.OVERLAY_COLORS.get(name, "#cccccc"))
            for e in ents:
                pt = self.lonlat_to_screen(e["lat"], e["lon"])
                if not (-20 <= pt.x() <= self.width() + 20 and -20 <= pt.y() <= self.height() + 20):
                    continue
                c = QColor(col)
                if e.get("stale"):
                    c.setAlpha(110)
                p.setPen(QPen(QColor("#101010"), 1))
                p.setBrush(c)
                p.drawRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10))
                p.setPen(c)
                p.drawText(QPointF(pt.x() + 8, pt.y() + 4), f"{e.get('label') or e['id']} · {e.get('source', '')}")

    def _paint_gps(self, p):
        g = self.gps
        if g is None or not g.has_fix:
            return
        q = self.lonlat_to_screen(g.lat, g.lon)
        fresh = g.fix_fresh()
        acc = g.accuracy_m()
        if acc:
            rpx = acc / tm.ground_resolution(g.lat, self.zoom)
            if rpx > 6:
                p.setPen(QPen(QColor(76, 194, 255, 160), 1))
                p.setBrush(QColor(76, 194, 255, 45))
                p.drawEllipse(q, rpx, rpx)
        if g.track is not None and (g.speed or 0) > 0.5 and fresh:
            p.save()
            p.translate(q)
            p.rotate(g.track)
            path = QPainterPath()
            path.moveTo(0, -22)
            path.lineTo(7, -10)
            path.lineTo(-7, -10)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["accent"]))
            p.drawPath(path)
            p.restore()
        p.setPen(QPen(QColor("#FFFFFF"), 3))
        p.setBrush(QColor(C["accent"] if fresh else C["muted"]))
        p.drawEllipse(q, 8, 8)
        if not fresh:
            p.setPen(QColor(C["warn"]))
            p.drawText(QRectF(q.x() + 12, q.y() - 8, 200, 18), Qt.AlignmentFlag.AlignLeft, "fix lost")

    def rect_screen(self):
        if self.rect is None:
            return None
        w, s, e, n = self.rect
        a = self.lonlat_to_screen(n, w)
        yb = self.lonlat_to_screen(s, w).y()
        width = (e - w) / 360.0 * tm.TILE * 2 ** self.zoom
        return QRectF(a.x(), a.y(), width, yb - a.y()).normalized()

    def rect_bbox(self):
        """The download rectangle as a normalised BBox (west > east across the antimeridian)."""
        if self.rect is None:
            return None
        w, s, e, n = self.rect
        return tm.BBox(w, s, e, n).normalized()

    def _paint_rect(self, p):
        r = self.rect_screen()
        outside = QPainterPath()
        outside.addRect(self.rect_())
        inner = QPainterPath()
        inner.addRect(r)
        p.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 90))
        p.setPen(QPen(QColor(C["accent"]), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if self.download_mode:
            p.setBrush(QColor(C["accent"]))
            p.setPen(QPen(QColor("#000000"), 1))
            for h in self._handles(r).values():
                p.drawRect(h)

    def _handles(self, r):
        hs = HANDLE
        pts = {"nw": r.topLeft(), "ne": r.topRight(), "sw": r.bottomLeft(), "se": r.bottomRight(),
               "n": QPointF(r.center().x(), r.top()), "s": QPointF(r.center().x(), r.bottom()),
               "w": QPointF(r.left(), r.center().y()), "e": QPointF(r.right(), r.center().y())}
        return {k: QRectF(v.x() - hs, v.y() - hs, 2 * hs, 2 * hs) for k, v in pts.items()}

    def _paint_scale(self, p):
        res = tm.ground_resolution(self.lat, self.zoom)
        metres, label = tm.nice_scale(res * min(160, self.width() / 4))
        if metres <= 0:
            return
        px = metres / res
        x, y = 14, self.height() - 22
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.fillRect(QRectF(x - 6, y - 20, px + 12, 30), QColor(11, 13, 16, 190))
        p.setPen(QPen(QColor(C["text"]), 2))
        p.drawLine(QPointF(x, y), QPointF(x + px, y))
        p.drawLine(QPointF(x, y - 5), QPointF(x, y))
        p.drawLine(QPointF(x + px, y - 5), QPointF(x + px, y))
        p.drawText(QRectF(x, y - 20, px, 14), Qt.AlignmentFlag.AlignCenter, label)

    def _paint_attribution(self, p):
        text = (self.layer.attribution if self.layer else "") or ("" if not self.layer else "Attribution not provided by this map file")
        if not text:
            return
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        fm = p.fontMetrics()
        maxw = min(self.width() - 220, 900)
        text = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(maxw))
        w = fm.horizontalAdvance(text) + 12
        r = QRectF(self.width() - w - 4, self.height() - 20, w, 18)
        p.fillRect(r, QColor(11, 13, 16, 200))
        p.setPen(QColor(C["text2"]))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    # ------------------------------------------------------------ interaction
    def pan_pixels(self, dx, dy):
        cx, cy = self.center_world(self.zoom)
        n = tm.TILE * 2 ** self.zoom
        nx, ny = cx - dx, max(0.0, min(n, cy - dy))
        lon, lat = tm.world_to_lonlat(nx / tm.TILE, ny / tm.TILE, self.zoom)
        self.lat, self.lon = tm.clamp_lat(lat), tm.wrap_lon(lon)
        self.update()
        self.viewChanged.emit()

    def zoom_at(self, new_zoom, sx=None, sy=None):
        new_zoom = max(0.0, min(MAX_ZOOM, new_zoom))
        if sx is None:
            sx, sy = self.width() / 2, self.height() / 2
        lat, lon = self.screen_to_lonlat(sx, sy)
        self.zoom = new_zoom
        q = self.lonlat_to_screen(lat, lon)
        self.pan_pixels(sx - q.x(), sy - q.y())

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            pos = e.position()
            self.zoom_at(self.zoom + steps * 0.5, pos.x(), pos.y())

    def keyPressEvent(self, e):
        k = e.key()
        step = 80
        if k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_at(round(self.zoom) + 1)
        elif k == Qt.Key.Key_Minus:
            self.zoom_at(round(self.zoom) - 1)
        elif k == Qt.Key.Key_Left:
            self.pan_pixels(step, 0)
        elif k == Qt.Key.Key_Right:
            self.pan_pixels(-step, 0)
        elif k == Qt.Key.Key_Up:
            self.pan_pixels(0, step)
        elif k == Qt.Key.Key_Down:
            self.pan_pixels(0, -step)
        else:
            super().keyPressEvent(e)
            return
        self.userPanned.emit()

    def mouseDoubleClickEvent(self, e):
        if not self.download_mode:
            pos = e.position()
            self.zoom_at(round(self.zoom) + 1, pos.x(), pos.y())

    def _hit_handle(self, pos):
        r = self.rect_screen()
        if r is None:
            return None
        for k, h in self._handles(r).items():
            if h.adjusted(-4, -4, 4, 4).contains(pos):
                return k
        if r.contains(pos):
            return "move"
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._kinetic.stop()
        pos = e.position()
        self._press_pos = pos
        self._moved = False
        self._last_move = (pos, time.monotonic())
        self._vel = QPointF()
        if self.download_mode:
            hit = self._hit_handle(pos)
            if hit:
                self._drag = ("rect", hit, pos, self.rect)
                return
            if self.rect is None:
                lat, lon = self.screen_to_lonlat(pos.x(), pos.y())
                self._drag = ("new", lat, lon)
                return
        self._drag = ("pan", pos)

    def mouseMoveEvent(self, e):
        pos = e.position()
        lat, lon = self.screen_to_lonlat(pos.x(), pos.y())
        self.cursorMoved.emit(lat, lon)
        if not self._drag:
            if self.download_mode:
                hit = self._hit_handle(pos)
                cursors = {"move": Qt.CursorShape.SizeAllCursor, "n": Qt.CursorShape.SizeVerCursor,
                           "s": Qt.CursorShape.SizeVerCursor, "e": Qt.CursorShape.SizeHorCursor,
                           "w": Qt.CursorShape.SizeHorCursor, "nw": Qt.CursorShape.SizeFDiagCursor,
                           "se": Qt.CursorShape.SizeFDiagCursor, "ne": Qt.CursorShape.SizeBDiagCursor,
                           "sw": Qt.CursorShape.SizeBDiagCursor}
                self.setCursor(cursors.get(hit, Qt.CursorShape.CrossCursor))
            return
        if self._press_pos is not None and (pos - self._press_pos).manhattanLength() > 4:
            self._moved = True
        kind = self._drag[0]
        if kind == "pan":
            last = self._drag[1]
            d = pos - last
            self.pan_pixels(d.x(), d.y())
            self._drag = ("pan", pos)
            now = time.monotonic()
            lp, lt = self._last_move
            dt = max(1e-3, now - lt)
            self._vel = (pos - lp) / dt
            self._last_move = (pos, now)
            if self._moved:
                self.userPanned.emit()
        elif kind == "new" and self._moved:
            _, lat0, lon0 = self._drag
            self.rect = (min(lon0, lon), min(lat0, lat), max(lon0, lon), max(lat0, lat))
            self.rectChanged.emit()
            self.update()
        elif kind == "rect":
            self._edit_rect(pos)

    def _edit_rect(self, pos):
        _, hit, start, orig = self._drag
        w, s, e, n = orig
        lat0, lon0 = self.screen_to_lonlat(start.x(), start.y())
        lat1, lon1 = self.screen_to_lonlat(pos.x(), pos.y())
        dlon = lon1 - lon0
        if dlon > 180:
            dlon -= 360
        elif dlon < -180:
            dlon += 360
        dlat = lat1 - lat0
        if hit == "move":
            dlat = max(-tm.MAX_LAT - s, min(tm.MAX_LAT - n, dlat))
            w, e, s, n = w + dlon, e + dlon, s + dlat, n + dlat
        else:
            if "w" in hit:
                w = min(w + dlon, e - 1e-6)
            if "e" in hit:
                e = max(e + dlon, w + 1e-6)
            if "n" in hit:
                n = max(min(n + dlat, tm.MAX_LAT), s + 1e-6)
            if "s" in hit:
                s = min(max(s + dlat, -tm.MAX_LAT), n - 1e-6)
        if e - w > 360:
            e = w + 360
        self.rect = (w, s, e, n)
        self.rectChanged.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        drag = self._drag
        self._drag = None
        if drag and drag[0] == "pan":
            if not self._moved:
                pos = e.position()
                lat, lon = self.screen_to_lonlat(pos.x(), pos.y())
                self.mapClicked.emit(lat, lon)
            elif self._last_move and time.monotonic() - self._last_move[1] < 0.08 and \
                    (abs(self._vel.x()) + abs(self._vel.y())) > 300:
                self._kinetic.start()

    def _kinetic_step(self):
        self._vel *= 0.90
        if abs(self._vel.x()) + abs(self._vel.y()) < 40:
            self._kinetic.stop()
            return
        self.pan_pixels(self._vel.x() * 0.016, self._vel.y() * 0.016)

    def event(self, e):
        t = e.type()
        if t in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd):
            pts = e.points()
            if len(pts) == 2:
                a, b = pts[0].position(), pts[1].position()
                dist = math.hypot(a.x() - b.x(), a.y() - b.y())
                mid = (a + b) / 2
                if self._pinch is None or t == QEvent.Type.TouchBegin:
                    self._pinch = (dist, self.zoom, mid)
                elif dist > 10:
                    d0, z0, m0 = self._pinch
                    self.zoom_at(z0 + math.log2(dist / max(1.0, d0)), mid.x(), mid.y())
                    self.pan_pixels(mid.x() - m0.x(), mid.y() - m0.y())
                    self._pinch = (dist, self.zoom, mid)
                e.accept()
                return True
            if t == QEvent.Type.TouchEnd:
                self._pinch = None
            return super().event(e)       # one finger: Qt synthesises mouse events (pan)
        return super().event(e)
