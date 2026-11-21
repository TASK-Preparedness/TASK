# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Render assets/icons/task-mesh.svg to PNG sizes with QtSvg (no external tools)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = QGuiApplication(sys.argv[:1])
    svg = ROOT / "assets" / "icons" / "task-mesh.svg"
    r = QSvgRenderer(str(svg))
    if not r.isValid():
        print("invalid SVG", file=sys.stderr)
        return 1
    for size in (48, 64, 128, 256):
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p)
        p.end()
        out = ROOT / "assets" / "icons" / f"task-mesh-{size}.png"
        img.save(str(out))
        print(out)
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
