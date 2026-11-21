# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""The console window: status strip, banner, navigation rail, content stack, Lock overlay.

An ordinary decorated, resizable top-level window (PHASE-2.md sections 7.2 and 10.1):
opened maximized within the work area, never fullscreen at start, no window-flag
tricks, no input grabs, and only window-scoped shortcuts.
"""

import logging
import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QFrame, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMainWindow, QProxyStyle, QPushButton, QScroller, QStackedWidget, QStyle,
                               QStyleFactory, QVBoxLayout, QWidget)

from task_console import theme
from task_console.layout import Metrics, is_compact
from task_console.lock import IdleWatcher, LockOverlay
from task_console.notify import Banner, Notifier
from task_console.panels.base import PanelHost, plain
from task_console.panels.core_status import CoreStatusPanel
from task_console.panels.devices import DevicesPanel
from task_console.panels.home import HomePanel
from task_console.panels.placeholder import PlaceholderPanel
from task_console.prefs import SCALES
from task_console.widgets.dialogs import AssignDialog, SignInDialog, UnassignDialog

logger = logging.getLogger("task_console")

RAIL = (("home", "\u2302", "Home"), ("core", "\u2699", "Core"), ("devices", "\u26c1", "Devices"))
# Compact rail (72 px, PHASE-2.md 7.9): icons and short labels. The full label stays the accessible name and tooltip.
RAIL_SHORT = {"devices": "Devs"}
MIN_SIZE = (1024, 600)


class ConsoleStyle(QProxyStyle):
    """Fusion with layout spacing of at least 8 logical px between targets (7.7 item 1)."""

    def __init__(self) -> None:
        super().__init__(QStyleFactory.create("Fusion"))
        self.spacing = 8

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_LayoutHorizontalSpacing, QStyle.PixelMetric.PM_LayoutVerticalSpacing):
            return self.spacing
        return super().pixelMetric(metric, option, widget)


class StatusStrip(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statusStrip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)
        self.product = plain("T.A.S.K.", wrap=False)
        self.product.setProperty("role", "title")
        self.link = plain("", wrap=False)
        self.link.setAccessibleName("task-core link")
        self.identity = plain("Public", wrap=False)
        self.identity.setAccessibleName("Identity")
        self.action = QPushButton("Sign in")
        self.clock = plain("--:--", wrap=False)
        layout.addWidget(self.product)
        layout.addWidget(self.link)
        layout.addStretch(1)
        layout.addWidget(self.identity)
        layout.addWidget(self.action)
        layout.addWidget(self.clock)


class ShellContext:
    def __init__(self, window) -> None:
        self.window = window

    @property
    def controller(self):
        return self.window.controller

    @property
    def metrics(self):
        return self.window.metrics

    @property
    def notifier(self):
        return self.window.notifier

    def register_dialog(self, dialog) -> None:
        self.window.register_dialog(dialog)

    def request_sign_in(self) -> None:
        self.window.request_sign_in()


class MainWindow(QMainWindow):
    def __init__(self, controller, prefs, window_state=None, idle_clock=time.monotonic, wall=datetime.now,
                 parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.prefs = prefs
        self.window_state = window_state
        self.wall = wall
        self.notifier = Notifier(self)
        self.metrics = Metrics(prefs.scale, False)
        self.dialogs = []
        self.ctx = ShellContext(self)
        self.setWindowTitle("T.A.S.K. Console")
        self.setMinimumSize(*MIN_SIZE)

        central = QWidget()
        self.setCentralWidget(central)
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.strip = StatusStrip()
        column.addWidget(self.strip)
        self.banner = Banner(self.notifier)
        column.addWidget(self.banner)
        self.body = QWidget()
        column.addWidget(self.body, 1)
        row = QHBoxLayout(self.body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.rail = QListWidget()
        self.rail.setObjectName("rail")
        self.rail.setAccessibleName("Navigation")
        self.rail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rail.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for key, icon, label in RAIL:
            item = QListWidgetItem(f"{icon}\n{label}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
            self.rail.addItem(item)
        row.addWidget(self.rail)
        self.content = QStackedWidget()
        content_frame = QWidget()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(24, 16, 24, 16)
        content_layout.addWidget(self.content)
        row.addWidget(content_frame, 1)
        self.content_frame = content_frame

        self.home = HomePanel(self.ctx)
        self.core = CoreStatusPanel(self.ctx)
        self.devices = DevicesPanel(self.ctx)
        self.module = PlaceholderPanel(self.ctx)
        self.hosts = {}
        for panel in (self.home, self.core, self.devices, self.module):
            host = PanelHost(panel)
            self.hosts[panel.key] = host
            self.content.addWidget(host)
        self.home.openModule.connect(self.open_module)
        self.module.back.connect(lambda: self.show_panel("home"))
        self.rail.currentRowChanged.connect(self._rail_changed)

        self.overlay = LockOverlay(self.body)
        self.overlay.signInRequested.connect(self.request_sign_in)
        self.overlay.publicRequested.connect(self.controller.continue_public)
        self.strip.action.clicked.connect(self._strip_action)

        self.idle = IdleWatcher(prefs.idle_lock_minutes, clock=idle_clock, parent=self)
        self.idle.idle.connect(lambda: self.controller.lock("idle"))
        app = QApplication.instance()
        app.installEventFilter(self.idle)

        controller.changed.connect(self._on_changed)
        controller.lockChanged.connect(self._on_lock)
        controller.notice.connect(lambda severity, text: self.notifier.post(severity, text))

        self._dirty = set()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(30)
        self._render_timer.timeout.connect(self._flush)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(1000)

        self._shortcuts()
        self.apply_metrics(force=True)
        self.show_panel(prefs.last_panel)
        self.render_all()
        self._on_tick()

    # ---------------------------------------------------------------- shortcuts (window-scoped only)

    def _shortcuts(self) -> None:
        bindings = [
            ("Ctrl+1", lambda: self.show_panel("home")),
            ("Ctrl+2", lambda: self.show_panel("core")),
            ("Ctrl+3", lambda: self.show_panel("devices")),
            ("Ctrl+L", lambda: self.controller.lock("ctrl+l")),
            ("Ctrl+Shift+S", self.request_sign_in),
            ("F5", self.controller.reload),
            ("F11", self._toggle_fullscreen),
            ("Ctrl+=", lambda: self.step_scale(1)),
            ("Ctrl++", lambda: self.step_scale(1)),
            ("Ctrl+-", lambda: self.step_scale(-1)),
            ("Ctrl+0", lambda: self.set_scale(1.0)),
            ("F6", self._cycle_region),
        ]
        self.shortcuts = []
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)
            self.shortcuts.append(shortcut)

    def _toggle_fullscreen(self) -> None:
        """F11 only. Fullscreen is never stored or restored (10.1 item 2)."""
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def _cycle_region(self) -> None:
        focus = QApplication.focusWidget()
        regions = [self.strip, self.rail, self.content]
        current = 0
        for index, region in enumerate(regions):
            if focus is region or (focus is not None and region.isAncestorOf(focus)):
                current = index
                break
        else:
            current = -1
        for step in range(1, 4):
            region = regions[(current + step) % 3]
            target = self._first_focusable(region)
            if target is not None:
                target.setFocus(Qt.FocusReason.TabFocusReason)
                return

    @staticmethod
    def _first_focusable(region):
        if region.focusPolicy() & Qt.FocusPolicy.TabFocus and region.isVisible() and region.isEnabled():
            return region
        for child in region.findChildren(QWidget):
            if child.focusPolicy() & Qt.FocusPolicy.TabFocus and child.isVisible() and child.isEnabled() \
                    and child.isVisibleTo(region):
                return child
        return None

    # ---------------------------------------------------------------- scale and compact layout

    def step_scale(self, direction: int) -> None:
        index = SCALES.index(self.metrics.scale) if self.metrics.scale in SCALES else 0
        self.set_scale(SCALES[max(0, min(len(SCALES) - 1, index + direction))])

    def set_scale(self, scale: float) -> None:
        if scale not in SCALES:
            return
        self.prefs.scale = scale
        self.prefs.save()
        self.metrics = Metrics(scale, self.metrics.compact)
        self.apply_metrics(force=True)

    def apply_metrics(self, force=False) -> None:
        compact = is_compact(self.width(), self.height())
        if not force and compact == self.metrics.compact:
            return
        self.metrics = Metrics(self.metrics.scale, compact)
        m = self.metrics
        app = QApplication.instance()
        style = app.style()
        if not isinstance(style, ConsoleStyle):
            style = ConsoleStyle()
            app.setStyle(style)
        style.spacing = m.spacing
        font = QFont(app.font())
        font.setPixelSize(m.font_px)
        app.setFont(font)
        app.setStyleSheet(theme.stylesheet(m))
        self.strip.setFixedHeight(m.strip_height)
        self.rail.setFixedWidth(m.rail_width)
        self.rail.setSpacing(m.spacing // 2)  # 8 px between rail targets (7.7 item 1)
        for index, (key, icon, label) in enumerate(RAIL):
            item = self.rail.item(index)
            item.setSizeHint(QSize(m.rail_width - m.spacing, m.rail_item_height))
            item.setText(f"{icon}\n{RAIL_SHORT.get(key, label) if m.compact else label}")
            item.setToolTip(label)
        for host in self.hosts.values():
            host.safe(host.panel.apply_metrics, m)
        self.apply_kinetic(self.prefs.kinetic_scroll)
        self.render_all()

    def apply_kinetic(self, enabled: bool) -> None:
        """Touch readiness (7.7 item 4): one setting enables kinetic gesture scrolling everywhere."""
        for area in self.findChildren(QAbstractScrollArea):
            if enabled:
                QScroller.grabGesture(area.viewport(), QScroller.ScrollerGestureType.TouchGesture)
            else:
                QScroller.ungrabGesture(area.viewport())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.apply_metrics()

    # ---------------------------------------------------------------- navigation

    def show_panel(self, key: str) -> None:
        if key not in ("home", "core", "devices"):
            key = "home"
        self.content.setCurrentWidget(self.hosts[key])
        row = [entry[0] for entry in RAIL].index(key)
        if self.rail.currentRow() != row:
            self.rail.blockSignals(True)
            self.rail.setCurrentRow(row)
            self.rail.blockSignals(False)
        if self.prefs.last_panel != key:
            self.prefs.last_panel = key
            self.prefs.save()

    def _rail_changed(self, row: int) -> None:
        if 0 <= row < len(RAIL):
            self.show_panel(RAIL[row][0])

    def open_module(self, module_id: str) -> None:
        self.module.module_id = module_id
        self.hosts["module"].safe(self.module.render, "all")
        self.content.setCurrentWidget(self.hosts["module"])
        self.module.back_button.setFocus()

    def current_panel_key(self) -> str:
        return self.content.currentWidget().panel.key

    # ---------------------------------------------------------------- rendering

    def render_all(self) -> None:
        self._render_strip()
        for host in self.hosts.values():
            host.safe(host.panel.render, "all")

    def _on_changed(self, area: str) -> None:
        if area in ("role", "link", "devices"):
            # synchronous: a lock or role change must clear operator data in the same turn (6.4)
            self._dirty.discard(area)
            self._render_strip()
            for host in self.hosts.values():
                host.safe(host.panel.render, area)
            if area == "role" and self.controller.role != "administrator":
                for dialog in list(self.dialogs):
                    if isinstance(dialog, (AssignDialog, UnassignDialog)):
                        dialog.reject()
            return
        self._dirty.add(area)
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush(self) -> None:
        areas, self._dirty = self._dirty, set()
        if not areas:
            return
        if areas == {"seq"}:
            self.hosts["core"].safe(self.core.render, "seq")
            return
        self._render_strip()
        for host in self.hosts.values():
            host.safe(host.panel.render, "data")

    def _render_strip(self) -> None:
        c = self.controller
        icon = {"connected": theme.ICON_CONNECTED, "connecting": theme.ICON_CONNECTING,
                "too-old": theme.ICON_WARNING}.get(c.link, theme.ICON_OFFLINE)
        self.strip.link.setText(f"{icon} {c.link_text()}")
        self.strip.identity.setText(f"{c.username} \u00b7 {c.role}" if c.signed_in and c.username else "Public")
        self.strip.action.setText("\U0001f512 Lock" if c.signed_in else "Sign in")
        self.overlay.link.setText(f"{icon} {c.link_text()}")

    def _on_tick(self) -> None:
        now = self.wall().strftime("%H:%M")
        self.strip.clock.setText(now)
        self.overlay.clock.setText(now)
        if self.controller.link not in ("connected", "connecting"):
            self._render_strip()

    def _strip_action(self) -> None:
        if self.controller.signed_in:
            self.controller.lock("button")
        else:
            self.request_sign_in()

    # ---------------------------------------------------------------- dialogs, sign-in, lock

    def register_dialog(self, dialog) -> None:
        self.dialogs.append(dialog)
        dialog.lockRequested.connect(lambda: self.controller.lock("ctrl+l"))
        dialog.finished.connect(lambda _code, d=dialog: self.dialogs.remove(d) if d in self.dialogs else None)

    def request_sign_in(self):
        for dialog in self.dialogs:
            if isinstance(dialog, SignInDialog):
                dialog.raise_()
                dialog.username.setFocus()
                return dialog
        if self.controller.signed_in:
            self.notifier.post("info", f"Signed in as {self.controller.username}. Lock first to change user.")
            return None
        dialog = SignInDialog(self, self.controller, self.metrics.dialog_max)
        self.register_dialog(dialog)
        dialog.open()
        dialog.username.setFocus()
        return dialog

    def _on_lock(self, locked: bool) -> None:
        if locked:
            for dialog in list(self.dialogs):
                dialog.reject()  # cancelled without sending anything (6.4 step 2)
                dialog.scrub()  # nothing operator-level stays in a closed dialog awaiting deletion
            self._render_strip()
            for host in self.hosts.values():
                host.safe(host.panel.render, "role")
            if self.current_panel_key() == "module":
                self.module.render("role")
            self.overlay.show_locked()
        else:
            self.overlay.hide()
            self._render_strip()

    def closeEvent(self, event) -> None:
        if self.window_state is not None:
            geometry = self.normalGeometry()
            self.window_state.save(geometry.x(), geometry.y(), geometry.width(), geometry.height())
        self.prefs.save()
        super().closeEvent(event)
