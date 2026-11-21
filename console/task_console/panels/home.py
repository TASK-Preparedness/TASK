# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Home: one tile per module manifest reported by module.list (PHASE-2.md section 7.4)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from task_console.panels.base import DASH, UNAVAILABLE, WITHHELD, Panel, dash, plain, title


def capability_status(controller, name):
    if not controller.live or controller.capabilities is None:
        return UNAVAILABLE if not controller.live else DASH
    for entry in controller.capabilities:
        if entry.get("name") == name:
            return dash(entry.get("status"))
    return DASH


def logical_lines(controller, module) -> list:
    """The backing logical devices: operator and above only; public sees 'Sign in to view' (D5)."""
    if not controller.signed_in:
        return [WITHHELD]
    logicals = module.get("logical_devices")
    if logicals is None:
        return [DASH]
    if not logicals:
        return [DASH]
    lines = []
    assignments = (controller.devices or {}).get("assignments") if controller.devices else None
    for logical in logicals:
        if assignments is None:
            lines.append(f"{logical} \u00b7 {DASH}")
            continue
        entry = assignments.get(logical)
        if entry is None:
            lines.append(f"{logical} \u00b7 unassigned")
        elif not controller.live:
            lines.append(f"{logical} \u00b7 assigned \u00b7 {UNAVAILABLE}")
        else:
            lines.append(f"{logical} \u00b7 assigned \u00b7 {'connected' if entry.get('connected') else 'disconnected'}")
    return lines


class Tile(QFrame):
    activated = Signal(str)

    def __init__(self, module_id: str, parent=None) -> None:
        super().__init__(parent)
        self.module_id = module_id
        self.setObjectName("tile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self.name = plain("", wrap=True)
        self.name.setProperty("role", "title")
        self.state = plain("")
        self.reason = plain("")
        self.caps = plain("")
        self.logical = plain("")
        for label in (self.name, self.state, self.reason, self.caps, self.logical):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(label)
        layout.addStretch(1)

    def set_content(self, name, state, reason, caps, logical) -> None:
        self.name.setText(name)
        self.state.setText(f"State: {state}")
        self.reason.setText(f"Reason: {reason}")
        self.caps.setText("Capabilities: " + ("; ".join(caps) if caps else DASH))
        self.logical.setText("Logical devices: " + "; ".join(logical))
        self.setAccessibleName(f"{name} module, state {state}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.activated.emit(self.module_id)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.module_id)
            return
        super().keyPressEvent(event)


class HomePanel(Panel):
    key = "home"
    title_text = "Home"
    openModule = Signal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        outer.addWidget(title(self.title_text))
        self.status = plain("")
        outer.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        outer.addWidget(self.scroll, 1)
        self.tiles = []
        self._ids = None
        self._columns = 4

    def columns(self) -> int:
        m = self.ctx.metrics
        available = max(1, self.scroll.viewport().width() - 32)
        fit = max(1, available // (m.tile_width + 16))
        return max(1, min(m.max_columns, fit))

    def apply_metrics(self, metrics) -> None:
        self._ids = None
        self.render("modules")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.columns() != self._columns:
            self._ids = None
            if self.host is not None:
                self.host.safe(self.render, "modules")

    def reset(self) -> None:
        self._ids = None

    def render(self, area: str = "all") -> None:
        controller = self.ctx.controller
        modules = controller.modules
        if modules is None:
            self.status.setText(f"Modules: {UNAVAILABLE if not controller.live else DASH}")
            self._rebuild([])
            return
        self.status.setText("" if controller.live else "task-core unavailable: live fields show \u2014")
        ids = [str(module.get("id")) for module in modules]
        if ids != self._ids or self.columns() != self._columns:
            self._rebuild(ids)
        for tile, module in zip(self.tiles, modules):
            requires = ((module.get("capabilities") or {}).get("requires")) or []
            caps = [f"{name} {capability_status(controller, name)}" for name in requires]
            state = dash(module.get("state")) if controller.live else UNAVAILABLE
            tile.set_content(dash(module.get("name")), state, dash(module.get("reason")), caps,
                             logical_lines(controller, module))

    def _rebuild(self, ids) -> None:
        for tile in self.tiles:
            tile.setParent(None)
            tile.deleteLater()
        self.tiles = []
        self._ids = list(ids)
        self._columns = self.columns()
        m = self.ctx.metrics
        for index, module_id in enumerate(ids):
            tile = Tile(module_id)
            tile.setMinimumSize(m.tile_width, m.tile_height)
            tile.setMaximumWidth(m.tile_width * 2)
            tile.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            tile.activated.connect(self.guarded(self.openModule.emit))
            self.grid.addWidget(tile, index // self._columns, index % self._columns)
            self.tiles.append(tile)

    def keyPressEvent(self, event) -> None:
        """Arrow keys move between tiles in the grid (7.3)."""
        focus = self.focusWidget()
        if focus in self.tiles:
            index = self.tiles.index(focus)
            step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1,
                    Qt.Key.Key_Up: -self._columns, Qt.Key.Key_Down: self._columns}.get(event.key())
            if step is not None:
                target = index + step
                if 0 <= target < len(self.tiles):
                    self.tiles[target].setFocus()
                    self.scroll.ensureWidgetVisible(self.tiles[target])
                return
        super().keyPressEvent(event)
