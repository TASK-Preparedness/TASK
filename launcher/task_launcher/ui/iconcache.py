# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Rendering tile icons: bundled Lucide SVGs (recoloured) and real installed application icons
(icon theme lookup through QIcon.fromTheme -> hicolor fallback -> /usr/share/pixmaps; validated
absolute Icon= paths)."""

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

from task_launcher import icons
from task_launcher.registry.desktop import ICON_EXTS, icon_file_ok

PIXMAP_DIRS = ("/usr/share/pixmaps", "/usr/local/share/pixmaps")
_theme_ready = False


def _ensure_theme():
    global _theme_ready
    if _theme_ready:
        return
    _theme_ready = True
    if not QIcon.fallbackThemeName():
        QIcon.setFallbackThemeName("hicolor")
    paths = list(QIcon.themeSearchPaths())
    for d in [os.path.join(x, "icons") for x in
              (os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
               *(os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"))]:
        if d not in paths and os.path.isdir(d):
            paths.append(d)
    QIcon.setThemeSearchPaths(paths)


def app_qicon(spec):
    """QIcon for ('theme', name) / ('file', path), or None if nothing real was found."""
    _ensure_theme()
    kind, value = spec
    if kind == "file":
        if icon_file_ok(value):
            ic = QIcon(value)
            return None if ic.isNull() else ic
        return None
    ic = QIcon.fromTheme(value)
    if not ic.isNull():
        return ic
    for d in PIXMAP_DIRS:
        for ext in ICON_EXTS:
            p = os.path.join(d, value + ext)
            if icon_file_ok(p):
                ic = QIcon(p)
                if not ic.isNull():
                    return ic
    return None


_pixcache = {}
PIXCACHE_MAX = 512


def clear_cache():
    _pixcache.clear()


def paint_icon(painter: QPainter, spec, rect: QRectF, colour: str, muted=False):
    """Draw any tile icon from a per-(icon, size, colour, dpr) pixmap cache, so animation frames do
    no SVG parsing or theme lookups. Returns 'lucide' | 'app' | 'fallback'."""
    dpr = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
    key = (repr(spec), int(rect.width()), int(rect.height()), colour, muted, dpr)
    hit = _pixcache.get(key)
    if hit is None:
        w, h = max(1, int(rect.width() * dpr)), max(1, int(rect.height() * dpr))
        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind = _paint_icon_direct(p, spec, QRectF(0, 0, w, h), colour, muted)
        p.end()
        pix.setDevicePixelRatio(dpr)
        if len(_pixcache) > PIXCACHE_MAX:
            _pixcache.clear()
        hit = _pixcache[key] = (pix, kind)
    painter.drawPixmap(rect.topLeft(), hit[0])
    return hit[1]


def _paint_icon_direct(painter, spec, rect, colour, muted=False):
    if isinstance(spec, tuple):
        ic = app_qicon(spec)
        if ic is not None:
            size = int(max(rect.width(), rect.height()))
            pix = ic.pixmap(size, size)
            if not pix.isNull():
                painter.save()
                if muted:
                    painter.setOpacity(0.45)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawPixmap(rect, pix, QRectF(pix.rect()))
                painter.restore()
                return "app"
        icons.paint(painter, "app-window", rect, colour)
        return "fallback"
    icons.paint(painter, spec, rect, colour)
    return "lucide"


def icon_for_list(spec, colour="#E8EAED", size=32) -> QIcon:
    if isinstance(spec, tuple):
        ic = app_qicon(spec)
        if ic is not None:
            return ic
        spec = "app-window"
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    icons.paint(p, spec, QRectF(0, 0, size * 2, size * 2), colour)
    p.end()
    return QIcon(pix)
