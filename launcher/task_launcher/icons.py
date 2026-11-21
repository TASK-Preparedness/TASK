# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Lucide (ISC) icons, vendored as SVG under data/icons/lucide/ with the licence file.

Icons are recoloured by replacing ``currentColor`` and rendered with QSvgRenderer
(Debian ``python3-pyside6.qtsvg``). App-supplied icons go through the same loader after the
manifest validator has confined their path (registry/manifest.py).
"""

import re
from functools import lru_cache
from pathlib import Path

LUCIDE_DIR = Path(__file__).resolve().parent / "data" / "icons" / "lucide"
MAX_ICON_BYTES = 64 * 1024
STROKE = 1.75
_UNSAFE = re.compile(rb"<script|javascript:|xlink:href\s*=\s*[\"'](?!#)|href\s*=\s*[\"'](?:https?:|file:|//)|<foreignObject",
                     re.IGNORECASE)


def lucide_path(name: str) -> Path:
    return LUCIDE_DIR / f"{name}.svg"


def svg_is_safe(data: bytes) -> bool:
    """No scripts, no external references (data-only monochrome SVG)."""
    return len(data) <= MAX_ICON_BYTES and b"<svg" in data[:4096] and not _UNSAFE.search(data)


@lru_cache(maxsize=256)
def _read(path: str) -> bytes:
    data = Path(path).read_bytes()
    if not svg_is_safe(data):
        raise ValueError("unsafe or oversized SVG")
    return data


def svg_bytes(path, colour: str, stroke: float = STROKE) -> bytes:
    data = _read(str(path))
    return (data.replace(b"currentColor", colour.encode())
            .replace(b'stroke-width="2"', f'stroke-width="{stroke}"'.encode()))


def resolve(icon) -> Path:
    """``icon`` is a Path to an SVG, or a bundled Lucide name; falls back to 'shapes'."""
    if isinstance(icon, Path):
        return icon
    if isinstance(icon, str) and re.fullmatch(r"[a-z0-9-]{1,64}", icon) and lucide_path(icon).is_file():
        return lucide_path(icon)
    return lucide_path("shapes")


def paint(painter, icon, rect, colour: str, stroke: float = STROKE) -> bool:
    """Render an icon into ``rect`` (QRectF). Returns False if it could not be rendered."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer

    try:
        data = svg_bytes(resolve(icon), colour, stroke)
    except (OSError, ValueError):
        return False
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        return False
    renderer.render(painter, rect)
    return True


def qicon(icon, colour: str, size: int = 24):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap

    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint(p, icon, QRectF(0, 0, size * 2, size * 2), colour)
    p.end()
    return QIcon(pix)
