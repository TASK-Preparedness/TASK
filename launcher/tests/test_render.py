# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Offscreen renders for the reports. Skipped unless TL_RENDER_DIR is set.

Every image is stamped "TESTDATA" in its corner: they are offscreen Qt renders on the build box,
not screenshots from the Pi."""

import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from task_launcher.ui.pager import DURATION_MS

OUT = os.environ.get("TL_RENDER_DIR")
REFERENCE = Path("/workspace/rain-platform-spec/approved-launcher-reference.png")
pytestmark = pytest.mark.skipif(not OUT, reason="renders only when TL_RENDER_DIR is set")
BOX_APPS = ["libreoffice-writer.desktop", "libreoffice-calc.desktop", "libreoffice-impress.desktop",
            "thunar.desktop", "xfce4-terminal.desktop", "google-chrome.desktop"]


def stamp(img: QImage, label: str) -> QImage:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("DejaVu Sans")
    f.setPixelSize(max(12, img.height() // 70))
    f.setBold(True)
    p.setFont(f)
    text = f"TESTDATA — {label} — offscreen render on the build box, not a Pi screenshot"
    w = p.fontMetrics().horizontalAdvance(text) + 24
    h = p.fontMetrics().height() + 10
    r = QRectF(img.width() - w - 8, 8, w, h)
    p.fillRect(r, QColor(120, 20, 20, 225))
    p.setPen(QColor("white"))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


def save(w, name, label):
    Path(OUT).mkdir(parents=True, exist_ok=True)
    img = w.grab().toImage()
    stamp(img, label).save(str(Path(OUT) / name))
    return img


def test_render_connected_and_disconnected(qtbot, launcher, p2env):
    core = p2env()
    w = launcher(core.config.socket, size=(1920, 1080))
    qtbot.waitUntil(lambda: w.link.live and w.link.health is not None, timeout=5000)
    qtbot.wait(100)
    img = save(w, "launcher-connected-1920x1080.png", "connected to a test task-core (p2env)")
    core.close()
    qtbot.waitUntil(lambda: not w.link.live, timeout=5000)
    qtbot.wait(100)
    save(w, "launcher-disconnected-1920x1080.png", "task-core stopped")
    if REFERENCE.exists():
        ref = QImage(str(REFERENCE))
        h = 1080
        refs = ref.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
        out = QImage(refs.width() + 1920 + 24, h + 48, QImage.Format.Format_ARGB32)
        out.fill(QColor("#202020"))
        p = QPainter(out)
        p.drawImage(0, 48, refs)
        p.drawImage(refs.width() + 24, 48, img)
        f = QFont("DejaVu Sans")
        f.setPixelSize(24)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(12, 32, "Approved reference (mockup, includes a drawn panel/title bar)")
        p.drawText(refs.width() + 36, 32, "task-launcher 0.2.0 (real window content, no fake panel)")
        p.end()
        stamp(out, "side-by-side").save(str(Path(OUT) / "side-by-side-vs-reference.png"))


@pytest.mark.parametrize("size", [(1366, 768), (1280, 720), (1024, 600)])
def test_render_layouts(launcher, size):
    w = launcher(size=size, start=False)
    save(w, f"launcher-{size[0]}x{size[1]}.png", f"{w.home.L['effective']} layout, task-core not running")


@pytest.fixture
def box_apps(monkeypatch):
    """Read-only scan of the build box's real /usr/share/applications for real icons."""
    monkeypatch.setenv("XDG_DATA_DIRS", "/usr/share")
    present = [a for a in BOX_APPS if (Path("/usr/share/applications") / a).exists()]
    if len(present) < 3:
        pytest.skip("not enough desktop entries on this box")
    return present


def test_render_extra_tiles_page_two(qtbot, launcher, box_apps):
    w = launcher(size=(1920, 1080), start=False)
    for a in box_apps:
        w.registry.add_desktop(a)
    w.rebuild()
    save(w, "launcher-page1-with-extra-tiles.png", "page 1 of 2; build-box apps added")
    w.home.pager.go_to(1, animate=False)
    qtbot.wait(50)
    save(w, "launcher-page2-extra-tiles.png", "page 2: added desktop applications (build box)")
    am = w.open_builtin("app-manager")
    am.resize(1400, 800)
    qtbot.wait(50)
    am.grab().toImage().save(str(Path(OUT) / "_am.png"))
    stamp(QImage(str(Path(OUT) / "_am.png")), "App Manager").save(str(Path(OUT) / "app-manager.png"))
    os.unlink(Path(OUT) / "_am.png")
    am.open_add()
    d = am.add_dialog
    d.resize(760, 640)
    qtbot.wait(50)
    stamp(d.grab().toImage(), "Add Application (build box entries)").save(str(Path(OUT) / "add-application.png"))


def test_render_mid_transition_frames(qtbot, launcher, box_apps):
    w = launcher(size=(1920, 1080), start=False)
    for a in box_apps:
        w.registry.add_desktop(a)
    w.rebuild()
    pg = w.home.pager
    pg.next()
    pg.group.pause()
    for pct in (25, 50, 75):
        pg.group.setCurrentTime(int(DURATION_MS * pct / 100))
        qtbot.wait(20)
        save(w, f"transition-{pct:02d}pct.png", f"page transition at {pct}% of {DURATION_MS} ms (OutCubic)")
    pg.group.stop()
    pg.go_to(0, animate=False)
    pg.press(1500, 500, t=0.0)
    pg.move(1500 - int(pg.page_w * 0.4), 500, t=1.0)
    qtbot.wait(20)
    save(w, "drag-40pct.png", "pointer drag at 40% of the page width")
    pg.cancel_gesture_silently()


def test_render_icon_copy(launcher):
    shutil.copy(Path(__file__).resolve().parents[1] / "share/icons/hicolor/scalable/apps/task-launcher.svg",
                Path(OUT) / "task-launcher-icon.svg")
