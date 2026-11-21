# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Devices panel (PHASE-2.md section 8).

Public: counts and the sign-in prompt only, and no device.* request except
device.counts (D5). Operator: slots, list and detail, read-only. Administrator:
plus Assign... and Unassign, always through a confirmation.
"""

from PySide6.QtCore import QEvent, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont, QFontMetrics, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QGridLayout, QHBoxLayout, QHeaderView, QPushButton,
                               QScrollArea, QStackedWidget, QTableView, QVBoxLayout, QWidget)

from task_console.panels.base import DASH, UNAVAILABLE, Panel, dash, plain, title
from task_console.widgets.dialogs import LOGICAL_CAPABILITY, LOGICALS, AssignDialog, UnassignDialog

FACTORY_SERIALS = {"0001", "00000001"}
UNSTABLE_NOTE = ("This device has no usable serial number. Its id depends on the USB port: moved to another port, "
                 "it appears as a new device and any assignment shows Disconnected.")
SHARED_NOTE = ("Identical units of this model may share this id. Use one per T.A.S.K. unit, "
               "or set a unique serial where the hardware allows.")
PUBLIC_PROMPT = "Sign in as operator or administrator to view devices."
OPERATOR_NOTE = "Assigning devices requires an administrator."
NOT_CONNECTED = "This device is not connected now; the assignment applies when it reconnects."
CHANGED_NOTE = "The assignments changed after the confirmation was built. Review the effects again."
COLUMNS = ("Name", "Class", "Logical / alias", "Status", "Identity", "Id", "Device node")
DETAIL_FIELDS = ("id", "by_id", "vid", "pid", "serial", "manufacturer", "product", "subsystem", "class",
                 "potential", "identity_stable", "connected", "devnode", "logical", "alias")
LIVE_FIELDS = {"connected", "devnode"}
STRETCH_COLUMNS = ("Name", "Logical / alias")
OPTIONAL_COLUMNS = ("Device node", "Class", "Identity")
FILTERS = ("All", "Assigned", "Unassigned", "Disconnected", "Network")


def device_name(device) -> str:
    return (device or {}).get("product") or (device or {}).get("manufacturer") or DASH


def shared_identity(device) -> bool:
    """K2 information note (8.4): empty, all-zero or factory-default serial, or a model-only by-id."""
    serial = (device.get("serial") or "").strip()
    if serial == "" or set(serial) == {"0"} or serial in FACTORY_SERIALS:
        return True
    return bool(device.get("by_id")) and device.get("serial") is None


def counts_text(counts) -> str:
    return (f"{counts.get('connected', DASH)} connected \u00b7 {counts.get('disconnected', DASH)} disconnected "
            f"\u00b7 {counts.get('total', DASH)} total")


def assign_effects(listing, logical, device_id):
    """Every effect of an assign, listed explicitly (8.5 item 2). None if the device is unknown."""
    devices = {device["id"]: device for device in listing.get("devices") or []}
    device = devices.get(device_id)
    if device is None:
        return None
    lines = [f"{logical} \u2192 {device_name(device)} ({device_id})"]
    displaced = []
    for other in devices.values():
        if other["id"] != device_id and other.get("logical") == logical:
            lines.append(f"{logical} will be removed from {device_name(other)} ({other['id']})")
            displaced.append({"logical": logical, "device_id": other["id"]})
    if device.get("logical") and device["logical"] != logical:
        lines.append(f"This device will lose {device['logical']}")
        displaced.append({"logical": device["logical"], "device_id": device_id})
    warnings = []
    capability = LOGICAL_CAPABILITY[logical]
    if capability not in (device.get("potential") or []):
        warnings.append(f"task-core will accept this, but this device is not classified for {capability}.")
    if device.get("identity_stable") is False:
        warnings.append(UNSTABLE_NOTE)
    if not device.get("connected"):
        lines.append(NOT_CONNECTED)
    names = {key: device_name(value) for key, value in devices.items()}
    return {"logical": logical, "lines": lines, "displaced": displaced, "warnings": warnings, "names": names}


class _Filter(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.mode = "All"

    def set_mode(self, mode) -> None:
        self.mode = mode
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent) -> bool:
        if self.mode == "All":
            return True
        device = self.sourceModel().item(row, 0).data(Qt.ItemDataRole.UserRole + 1) or {}
        if self.mode == "Assigned":
            return bool(device.get("logical"))
        if self.mode == "Unassigned":
            return not device.get("logical")
        if self.mode == "Disconnected":
            return not device.get("connected")
        if self.mode == "Network":
            return device.get("class") == "network" or device.get("subsystem") == "net"
        return True


class DeviceDetail(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.heading = plain("Select a device to see its details.")
        layout.addWidget(self.heading)
        self.stale = plain("")
        layout.addWidget(self.stale)
        grid = QGridLayout()
        self.values = {}
        for row, key in enumerate(DETAIL_FIELDS):
            name = plain(key, wrap=False)
            value = plain(DASH, selectable=True, mono=key in ("id", "by_id", "devnode"))
            grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.unstable = plain(UNSTABLE_NOTE)
        self.shared = plain(SHARED_NOTE)
        layout.addWidget(self.unstable)
        layout.addWidget(self.shared)
        self.unavailable = plain("task-core unavailable")
        layout.addWidget(self.unavailable)
        self.assign = QPushButton("Assign\u2026")
        layout.addWidget(self.assign, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.device = None
        self.show_device(None, True, None, False)

    def show_device(self, device, live, stale_since, admin) -> None:
        self.device = device
        has = device is not None
        for key, value in self.values.items():
            if not has:
                value.setText(DASH)
            elif key in LIVE_FIELDS and not live:
                value.setText(UNAVAILABLE)
            else:
                value.setText(dash(device.get(key)))
        self.heading.setText(f"{device_name(device)}" if has else "Select a device to see its details.")
        self.stale.setVisible(has and not live)
        self.stale.setText(f"stale since {stale_since}" if stale_since else "")
        self.unstable.setVisible(has and device.get("identity_stable") is False)
        self.shared.setVisible(has and shared_identity(device))
        self.assign.setVisible(has and admin)
        self.assign.setEnabled(live)
        self.unavailable.setVisible(has and admin and not live)


class DevicesPanel(Panel):
    key = "devices"
    title_text = "Devices"

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        outer.addWidget(title(self.title_text))
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)

        # public page
        public = QWidget()
        pl = QVBoxLayout(public)
        self.public_counts = plain(DASH)
        self.public_prompt = plain(PUBLIC_PROMPT)
        self.public_sign_in = QPushButton("Sign in")
        self.public_sign_in.clicked.connect(lambda: self.ctx.request_sign_in())
        pl.addWidget(self.public_counts)
        pl.addWidget(self.public_prompt)
        pl.addWidget(self.public_sign_in, 0, Qt.AlignmentFlag.AlignLeft)
        pl.addStretch(1)
        self.pages.addWidget(public)

        # signed-in page
        signed = QWidget()
        sl = QVBoxLayout(signed)
        sl.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        bl = QVBoxLayout(body)
        self.counts = plain(DASH)
        self.offline = plain("")
        bl.addWidget(self.counts)
        bl.addWidget(self.offline)
        bl.addWidget(plain("Logical devices", wrap=False))
        self.slot_labels = {}
        self.slot_buttons = {}
        for logical in LOGICALS:
            row = QHBoxLayout()
            label = plain("", selectable=True)
            button = QPushButton("Unassign")
            button.clicked.connect(self.guarded(lambda _=False, lg=logical: self._open_unassign(lg)))
            row.addWidget(label, 1)
            row.addWidget(button)
            bl.addLayout(row)
            self.slot_labels[logical] = label
            self.slot_buttons[logical] = button
        self.role_note = plain(OPERATOR_NOTE)
        bl.addWidget(self.role_note)
        filters = QHBoxLayout()
        self.filter_group = QButtonGroup(self)
        self.filter_buttons = {}
        for name in FILTERS:
            button = QPushButton(name)
            button.setCheckable(True)
            self.filter_group.addButton(button)
            self.filter_buttons[name] = button
            filters.addWidget(button)
            button.clicked.connect(self.guarded(lambda _=False, n=name: self.proxy.set_mode(n)))
        self.filter_buttons["All"].setChecked(True)
        filters.addStretch(1)
        bl.addLayout(filters)
        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(list(COLUMNS))
        self.proxy = _Filter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setTabKeyNavigation(False)  # arrows move within the table, Tab leaves it (7.3)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(5 * 48)
        self.table.installEventFilter(self)
        self.table.selectionModel().selectionChanged.connect(self.guarded(lambda *_: self._selection_changed()))
        self.table.clicked.connect(self.guarded(lambda *_: self._maybe_open_page()))
        self.table.activated.connect(self.guarded(lambda *_: self._maybe_open_page()))
        self.split = QHBoxLayout()
        self.split.addWidget(self.table, 3)
        self.detail = DeviceDetail()
        self.detail.assign.clicked.connect(self.guarded(lambda: self._open_assign()))
        self.detail_slot = QVBoxLayout()
        self.detail_slot.addWidget(self.detail)
        self.split.addLayout(self.detail_slot, 2)
        bl.addLayout(self.split, 1)
        self.scroll.setWidget(body)
        sl.addWidget(self.scroll)
        self.pages.addWidget(signed)

        # compact detail page (7.8)
        page = QWidget()
        dl = QVBoxLayout(page)
        self.back = QPushButton("\u2190 Back")
        self.back.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        dl.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_page_slot = QVBoxLayout()
        dl.addLayout(self.detail_page_slot, 1)
        self.pages.addWidget(page)

        self.selected_id = None
        self._filling = False
        self.dialogs = []
        self._compact = False

    # ---------------------------------------------------------------- layout

    def apply_metrics(self, metrics) -> None:
        compact = metrics.compact
        if compact != self._compact:
            self._compact = compact
            self.detail.setParent(None)
            (self.detail_page_slot if compact else self.detail_slot).addWidget(self.detail)
            self.split.setStretch(1, 0 if compact else 2)
            self.detail.show()
            if not compact and self.pages.currentIndex() == 2:
                self.pages.setCurrentIndex(1)
        self.table.verticalHeader().setDefaultSectionSize(metrics.row_height)
        self.table.horizontalHeader().setMinimumHeight(metrics.target)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """No horizontal scrolling (7.7 item 4) and no elided ids or states (test 71).

        Fixed columns are sized to their full text; when the table is too narrow
        (1024x600, or scale 1.5), Device node, then Class, then Identity are hidden
        from the table. Every hidden value stays in the device detail.
        """
        header = self.table.horizontalHeader()
        m = self.ctx.metrics
        pad = m.px(28)
        fm = self.table.fontMetrics()
        hfm = header.fontMetrics()
        widths = {}
        for column, name in enumerate(COLUMNS):
            if name in STRETCH_COLUMNS:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
                continue
            texts = [self.model.item(row, column).text() for row in range(self.model.rowCount())]
            metrics = fm
            if name == "Id":
                mono = QFont("monospace")
                mono.setPixelSize(m.font_px)
                metrics = QFontMetrics(mono)
            width = max([hfm.horizontalAdvance(name) + pad] + [metrics.horizontalAdvance(t) + pad for t in texts])
            widths[column] = width
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(column, width)
        available = self.table.viewport().width()
        hidden = set()
        for name in OPTIONAL_COLUMNS:
            used = sum(width for column, width in widths.items() if COLUMNS[column] not in hidden)
            if used + len(STRETCH_COLUMNS) * m.px(150) <= available:
                break
            hidden.add(name)
        for column, name in enumerate(COLUMNS):
            self.table.setColumnHidden(column, name in hidden)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.table and event.type() == QEvent.Type.Resize and self.host is not None:
            self.host.safe(self._fit_columns)
        return False

    def _maybe_open_page(self) -> None:
        if self._compact and self.selected_id is not None:
            self.pages.setCurrentIndex(2)

    # ---------------------------------------------------------------- rendering

    def reset(self) -> None:
        self.selected_id = None

    def render(self, area: str = "all") -> None:
        c = self.ctx.controller
        live = c.live
        if not c.signed_in:
            self.selected_id = None
            self.model.removeRows(0, self.model.rowCount())
            self.detail.show_device(None, live, None, False)
            for logical, label in self.slot_labels.items():
                label.setText("")
                self.slot_buttons[logical].setAccessibleName("Unassign")
                self.slot_buttons[logical].hide()
            self.pages.setCurrentIndex(0)
            self.public_counts.setText(counts_text(c.counts) if (live and c.counts) else
                                       f"Devices: {UNAVAILABLE if not live else DASH}")
            return
        if self.pages.currentIndex() == 0:
            self.pages.setCurrentIndex(1)
        admin = c.role == "administrator"
        self.counts.setText(counts_text(c.counts) if (live and c.counts) else f"Devices: {UNAVAILABLE}"
                            if not live else f"Devices: {DASH}")
        if live:
            self.offline.setText("")
            self.offline.hide()
        else:
            stale = f" \u2014 identity fields stale since {c.stale_since}" if c.stale_since else ""
            self.offline.setText("task-core unavailable" + stale)
            self.offline.show()
        listing = c.devices
        devices = (listing or {}).get("devices") or []
        by_id = {device.get("id"): device for device in devices}
        assignments = (listing or {}).get("assignments") or {}
        for logical in LOGICALS:
            entry = assignments.get(logical)
            button = self.slot_buttons[logical]
            if listing is None:
                text = f"{logical}: {DASH}"
            elif entry is None:
                text = f"{logical}: Unassigned"
            else:
                device = by_id.get(entry.get("device_id"), {})
                alias = f'alias "{entry["alias"]}"' if entry.get("alias") is not None else f"alias {DASH}"
                if not live:
                    status = UNAVAILABLE
                elif entry.get("connected"):
                    status = "Connected"
                else:
                    status = "Disconnected \u2014 assignment kept"
                text = f"{logical}: {device_name(device)} \u00b7 {dash(entry.get('device_id'))} \u00b7 {alias} \u00b7 {status}"
            self.slot_labels[logical].setText(text)
            button.setVisible(admin and entry is not None)
            button.setAccessibleName(f"Unassign {logical}" if admin and entry is not None else "Unassign")
            button.setEnabled(live)
        self.role_note.setText(OPERATOR_NOTE if not admin else ("task-core unavailable" if not live else ""))
        self.role_note.setVisible(not admin or not live)
        self._fill_table(devices, live)
        self.detail.show_device(by_id.get(self.selected_id), live, c.stale_since, admin)

    def _fill_table(self, devices, live) -> None:
        sorting = self.table.horizontalHeader().sortIndicatorSection(), self.table.horizontalHeader().sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self._filling = True
        self.model.removeRows(0, self.model.rowCount())
        for device in devices:
            logical = device.get("logical")
            if logical:
                logical_text = f'{logical} "{device["alias"]}"' if device.get("alias") is not None else logical
            else:
                logical_text = DASH
            if not live:
                status, node = UNAVAILABLE, UNAVAILABLE
            else:
                status = "Connected" if device.get("connected") else "Disconnected"
                node = dash(device.get("devnode"))
            identity = "Stable" if device.get("identity_stable") else "\u26a0 Unstable (USB port)"
            row = [device_name(device), dash(device.get("class")), logical_text, status, identity,
                   dash(device.get("id")), node]
            items = []
            for value in row:
                item = QStandardItem(value)
                item.setEditable(False)
                items.append(item)
            mono = QFont("monospace")
            mono.setPixelSize(self.ctx.metrics.font_px)
            items[COLUMNS.index("Id")].setFont(mono)
            items[0].setData(device.get("id"), Qt.ItemDataRole.UserRole)
            items[0].setData(device, Qt.ItemDataRole.UserRole + 1)
            self.model.appendRow(items)
        self.table.setSortingEnabled(True)
        self._fit_columns()
        if sorting[0] >= 0:
            self.table.sortByColumn(sorting[0], sorting[1])
        if self.selected_id is not None:
            for row in range(self.proxy.rowCount()):
                index = self.proxy.index(row, 0)
                if index.data(Qt.ItemDataRole.UserRole) == self.selected_id:
                    self.table.selectRow(row)
                    break
        self._filling = False

    def _selection_changed(self) -> None:
        if self._filling:
            return
        rows = self.table.selectionModel().selectedRows()
        self.selected_id = rows[0].data(Qt.ItemDataRole.UserRole) if rows else None
        c = self.ctx.controller
        by_id = {d.get("id"): d for d in ((c.devices or {}).get("devices") or [])}
        self.detail.show_device(by_id.get(self.selected_id), c.live, c.stale_since, c.role == "administrator")

    def select_device(self, device_id) -> bool:
        for row in range(self.proxy.rowCount()):
            if self.proxy.index(row, 0).data(Qt.ItemDataRole.UserRole) == device_id:
                self.table.selectRow(row)
                return True
        return False

    # ---------------------------------------------------------------- assign / unassign

    def _open_assign(self) -> None:
        c = self.ctx.controller
        device = self.detail.device
        if device is None or c.role != "administrator" or not c.live:
            return
        dialog = AssignDialog(self.window(), dict(device), self.ctx.metrics.dialog_max)
        self.ctx.register_dialog(dialog)
        dialog.continueRequested.connect(self.guarded(lambda lg, alias: self._confirm(dialog, lg)))
        dialog.assignRequested.connect(self.guarded(
            lambda lg, did, alias, confirm: self._send_assign(dialog, lg, did, alias, confirm)))
        dialog.open()
        return dialog

    def _confirm(self, dialog, logical, note=None) -> None:
        device_id = dialog.device.get("id")

        def built(listing, reply):
            if dialog.cancelled:
                return
            if listing is None:
                error = reply.get("error") or {}
                dialog.show_error("task-core unavailable" if reply.get("transport")
                                  else f"task-core refused: {error.get('message', '')}")
                return
            effects = assign_effects(listing, logical, device_id)
            if effects is None:
                dialog.show_error("task-core no longer lists this device.")
                return
            dialog.show_confirmation(effects, note)

        self.ctx.controller.fetch_devices(built)

    def _send_assign(self, dialog, logical, device_id, alias, confirm) -> None:
        names = dict((dialog.effects or {}).get("names") or {})

        def done(reply):
            if dialog.cancelled:
                return
            if reply.get("ok") is True:
                result = reply.get("result") or {}
                parts = [f"Assigned {logical} \u2192 {names.get(device_id, DASH)} ({device_id})"]
                for entry in result.get("displaced") or []:
                    parts.append(f"{entry.get('logical')} removed from {names.get(entry.get('device_id'), DASH)} "
                                 f"({entry.get('device_id')})")
                self.ctx.notifier.post("info", "; ".join(parts))
                dialog.accept()
                return
            error = reply.get("error") or {}
            if error.get("code") == "would-displace":
                # rebuilt from a fresh device.list and shown again; never retried automatically (8.5 item 5)
                self._confirm(dialog, logical, CHANGED_NOTE)
            elif reply.get("transport"):
                dialog.show_error("task-core unavailable")
            else:
                dialog.show_error(f"task-core refused: {error.get('message', '')}")

        self.ctx.controller.assign(logical, device_id, alias, confirm, done)

    def _open_unassign(self, logical) -> None:
        c = self.ctx.controller
        if c.role != "administrator" or not c.live or not c.devices:
            return
        entry = (c.devices.get("assignments") or {}).get(logical)
        if entry is None:
            return  # unassigning an empty slot is not offered (8.6)
        device = {d.get("id"): d for d in c.devices.get("devices") or []}.get(entry.get("device_id"), {})
        device = dict(device, id=entry.get("device_id"), alias=entry.get("alias"))
        dialog = UnassignDialog(self.window(), logical, device, self.ctx.metrics.dialog_max)
        self.ctx.register_dialog(dialog)

        def confirmed(lg):
            def done(reply):
                if dialog.cancelled:
                    return
                if reply.get("ok") is True:
                    self.ctx.notifier.post("info", f"Unassigned {lg}")
                    dialog.accept()
                else:
                    error = reply.get("error") or {}
                    dialog.show_error("task-core unavailable" if reply.get("transport")
                                      else f"task-core refused: {error.get('message', '')}")

            self.ctx.controller.unassign(lg, done)

        dialog.confirmed.connect(self.guarded(confirmed))
        dialog.open()
        return dialog
