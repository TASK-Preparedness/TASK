# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""App Manager: every tile (built-in, manifest, added desktop application) with its real status,
per-user enable/disable, dashboard placement, launch, error clearing, and 'Add Application' for
installed desktop applications. Package install/update/remove is NOT available in Phase 3 (the
buttons are present, disabled, and say so)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from task_launcher.launch import tail
from task_launcher.registry import desktop as D
from task_launcher.ui.iconcache import icon_for_list

DASH = "—"
NOT_IN_PHASE3 = "Not available in Phase 3 (signed .rainpkg packages are future work; see ARCHITECTURE.md)"
COLUMNS = ("Name", "Source", "Version", "Status", "On dashboard", "Executable")


class AppManagerWindow(QWidget):
    def __init__(self, ctl, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.ctl = ctl
        self.setWindowTitle("App Manager")
        self.resize(1280, 760)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.add_btn = QPushButton("Add Application…")
        self.rescan_btn = QPushButton("Rescan")
        self.reset_btn = QPushButton("Reset layout")
        top.addWidget(self.add_btn)
        top.addWidget(self.rescan_btn)
        top.addWidget(self.reset_btn)
        top.addStretch(1)
        self.install_btn = QPushButton("Install…")
        self.update_btn = QPushButton("Update")
        self.uninstall_btn = QPushButton("Uninstall")
        for b in (self.install_btn, self.update_btn, self.uninstall_btn):
            b.setEnabled(False)
            b.setToolTip(NOT_IN_PHASE3)
            b.setAccessibleDescription(NOT_IN_PHASE3)
            top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter()
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.detail, 1)
        grid = QHBoxLayout()
        self.launch_btn = QPushButton("Launch")
        self.enable_btn = QPushButton("Disable")
        self.dash_btn = QPushButton("Remove from dashboard")
        self.clear_btn = QPushButton("Clear error")
        for b in (self.launch_btn, self.enable_btn, self.dash_btn, self.clear_btn):
            grid.addWidget(b)
        rl.addLayout(grid)
        grid2 = QHBoxLayout()
        self.up_btn = QPushButton("Move earlier")
        self.down_btn = QPushButton("Move later")
        self.rename_btn = QPushButton("Rename…")
        self.icon_btn = QPushButton("Change icon…")
        for b in (self.up_btn, self.down_btn, self.rename_btn, self.icon_btn):
            grid2.addWidget(b)
        rl.addLayout(grid2)
        self.problems = QLabel("")
        self.problems.setWordWrap(True)
        self.problems.setProperty("role", "warn")
        rl.addWidget(self.problems)
        split.addWidget(right)
        split.setSizes([760, 520])
        lay.addWidget(split, 1)
        self.table.itemSelectionChanged.connect(self.render_detail)
        self.add_btn.clicked.connect(self.open_add)
        self.rescan_btn.clicked.connect(ctl.rescan)
        self.reset_btn.clicked.connect(self._reset)
        self.launch_btn.clicked.connect(lambda: self._with(lambda t: ctl.activate(t)))
        self.enable_btn.clicked.connect(lambda: self._with(lambda t: ctl.set_enabled(t, not t.enabled)))
        self.dash_btn.clicked.connect(lambda: self._with(self._toggle_dash))
        self.clear_btn.clicked.connect(lambda: self._with(lambda t: ctl.clear_error(t.key)))
        self.up_btn.clicked.connect(lambda: self._with(lambda t: ctl.move_tile(t.key, -1)))
        self.down_btn.clicked.connect(lambda: self._with(lambda t: ctl.move_tile(t.key, 1)))
        self.rename_btn.clicked.connect(lambda: self._with(lambda t: ctl.rename_tile(t, self)))
        self.icon_btn.clicked.connect(lambda: self._with(lambda t: ctl.change_icon(t, self)))
        self.add_dialog = None
        self.refresh()

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        key = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return self.ctl.registry.get(key)

    def _with(self, fn):
        t = self.selected()
        if t is not None:
            fn(t)

    def _toggle_dash(self, t):
        if t.hidden:
            self.ctl.show_tile(t.key)
        else:
            self.ctl.remove_tile(t.key, confirm_parent=self)

    def _reset(self):
        if QMessageBox.question(self, "Reset layout", "Restore the default tile order and show all built-in tiles "
                                "again? Added applications stay (after the built-ins).") == QMessageBox.StandardButton.Yes:
            self.ctl.reset_layout()

    def refresh(self):
        keep = self.selected().key if self.selected() else None
        reg = self.ctl.registry
        self.table.setRowCount(0)
        for t in reg.tiles:
            r = self.table.rowCount()
            self.table.insertRow(r)
            status, line = self.ctl.display_state(t)
            exe = t.argv[0] if t.argv else ("built-in" if t.builtin else DASH)
            vals = (t.name, {"builtin": "Built-in", "manifest": "Manifest", "desktop": "Desktop app"}[t.source],
                    (t.version if t.status != "Planned" else "") or DASH, line or status,
                    "no" if t.hidden else "yes", exe)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, t.key)
                    it.setIcon(icon_for_list(t.icon))
                self.table.setItem(r, c, it)
            if t.key == keep:
                self.table.selectRow(r)
        probs = [f"• {p.path}: {p.reason}" for p in reg.problems]
        self.problems.setText(("Manifest problems:\n" + "\n".join(probs)) if probs else "")
        self.render_detail()
        if self.add_dialog is not None and self.add_dialog.isVisible():
            self.add_dialog.populate()

    def render_detail(self):
        t = self.selected()
        for b in (self.launch_btn, self.enable_btn, self.dash_btn, self.clear_btn, self.up_btn, self.down_btn,
                  self.rename_btn, self.icon_btn):
            b.setEnabled(t is not None)
        if t is None:
            self.detail.setText("Select an app.")
            return
        status, line = self.ctl.display_state(t)
        m = t.manifest
        lines = [f"<b>{_h(t.name)}</b> — {_h(line or status)}", _h(t.description) or ""]
        lines.append(f"Source: {t.source}" + (f" · id {m.id} · manifest {m.path} ({m.trust})" if m else
                                               f" · desktop file id {t.desktop_id}"))
        if t.entry is not None:
            lines.append(f"Desktop file: {t.entry.path}")
        if t.argv:
            lines.append("Command (argv, no shell): " + _h(repr(t.argv)))
        if m and len(m.candidates()) > 1:
            lines.append("Candidates, in order of preference: " + _h(", ".join(
                f"{a[0]}" + (f" ({m.labels[a[0]]})" if a[0] in m.labels else "") for a in m.candidates())))
        ready = self.ctl.ready_state(t) if hasattr(self.ctl, "ready_state") else None
        if ready:
            lines.append("Readiness (display only): " + _h(ready[0]))
        for a in t.actions:
            lines.append(f"Action “{_h(a.label)}”: " + (_h(repr(a.argv)) if a.argv else "unavailable — " + _h(a.reason)))
        if m:
            req = [f"launcher platform ≥ {m.min_platform}"]
            if m.core_min_version:
                req.append(f"task-core ≥ {m.core_min_version}")
            for cap in m.core_capabilities:
                st = self.ctl.link.capability_status(cap) if self.ctl.link.live else None
                req.append(f"capability {cap}: {st or 'unknown (task-core not connected)' if not self.ctl.link.live else st or 'not reported'}")
            if m.hardware:
                req.append("hardware (informational): " + ", ".join(m.hardware))
            if m.debian:
                req.append("Debian packages (informational, not installed by the launcher): " + ", ".join(m.debian))
            if m.min_role != "public":
                req.append(f"minimum role to launch from here: {m.min_role}")
            lines.append("Requires: " + "; ".join(req))
            for w in m.warnings:
                lines.append("Warning: " + _h(w))
        rt = self.ctl.runtime.get(t.key)
        if rt and rt.get("log"):
            log = tail(rt["log"], 15)
            if log:
                lines.append("Last output:<pre>" + _h(log) + "</pre>")
        self.detail.setText("<br>".join(x for x in lines if x))
        self.enable_btn.setText("Enable" if not t.enabled else "Disable")
        self.enable_btn.setEnabled(bool(m) and t.can_disable)
        self.dash_btn.setText("Show on dashboard" if t.hidden else "Remove from dashboard")
        self.dash_btn.setEnabled(t.can_hide)
        self.clear_btn.setEnabled(bool(rt and rt.get("status") == "Error"))
        self.rename_btn.setEnabled(t.source == "desktop")
        self.icon_btn.setEnabled(t.source == "desktop")
        self.launch_btn.setEnabled(t.launchable and t.status != "Disabled")

    def open_add(self):
        if self.add_dialog is None:
            self.add_dialog = AddApplicationDialog(self.ctl, self)
        self.add_dialog.populate()
        self.add_dialog.show()
        self.add_dialog.raise_()


def _h(text):
    import html

    return html.escape(text or "")


class AddApplicationDialog(QDialog):
    """Searchable list of installed desktop applications (XDG .desktop entries). Adding creates a
    launcher tile only; nothing is installed and the .desktop file is not changed."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle("Add Application")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, description, keywords…")
        self.search.setAccessibleName("Search applications")
        lay.addWidget(self.search)
        row = QHBoxLayout()
        self.show_admin = QCheckBox("Show administrative entries")
        self.show_hidden = QCheckBox("Show entries hidden from menus")
        row.addWidget(self.show_admin)
        row.addWidget(self.show_hidden)
        row.addStretch(1)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setAccessibleName("Installed applications")
        lay.addWidget(self.list, 1)
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bottom = QHBoxLayout()
        self.rescan = QPushButton("Rescan")
        self.add = QPushButton("Add as tile")
        self.add.setDefault(True)
        close = QPushButton("Close")
        bottom.addWidget(self.rescan)
        bottom.addStretch(1)
        bottom.addWidget(close)
        bottom.addWidget(self.add)
        lay.addLayout(bottom)
        self.search.textChanged.connect(self.filter)
        self.show_admin.toggled.connect(self.populate)
        self.show_hidden.toggled.connect(self.populate)
        self.rescan.clicked.connect(ctl.rescan)
        self.add.clicked.connect(self.add_selected)
        self.list.itemActivated.connect(lambda _i: self.add_selected())
        close.clicked.connect(self.close)

    def populate(self):
        entries = self.ctl.registry.desktop_entries
        added = {c["desktop_id"] for c in self.ctl.registry.store.custom}
        self.list.clear()
        offer = D.offerable(entries, include_admin=self.show_admin.isChecked(),
                            include_hidden=self.show_hidden.isChecked())
        for entry, reason in offer:
            text = entry.name + (f" — {entry.generic_name or entry.comment}" if (entry.generic_name or entry.comment) else "")
            if entry.id in added:
                text += "   (already on the dashboard)"
            if reason:
                text += f"   [{reason}]"
            it = QListWidgetItem(icon_for_list(self.ctl.registry.desktop_icon(entry)), text)
            it.setData(Qt.ItemDataRole.UserRole, entry.id)
            it.setData(Qt.ItemDataRole.UserRole + 1, entry.search_text())
            it.setToolTip(f"{entry.id}\n{entry.path}")
            if entry.id in added:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(it)
        scanning = self.ctl.scanning
        self.status.setText(("Scanning installed applications…  " if scanning else "") +
                            f"{len(offer)} applications listed from {len(entries)} desktop entries. "
                            "Adding a tile does not install or change anything.")
        self.filter(self.search.text())

    def filter(self, text):
        words = text.lower().split()
        for i in range(self.list.count()):
            it = self.list.item(i)
            hay = it.data(Qt.ItemDataRole.UserRole + 1) or ""
            it.setHidden(not all(w in hay for w in words))

    def add_selected(self):
        it = self.list.currentItem()
        if it is None or not it.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self.ctl.add_desktop(it.data(Qt.ItemDataRole.UserRole))
        self.populate()


class IconDialog(QDialog):
    """Choose a custom icon for an added tile: a theme icon name or an image file (validated)."""

    def __init__(self, current="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change icon")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(current if current and not current.startswith("/") else "")
        self.name.setPlaceholderText("icon theme name, e.g. utilities-terminal")
        self.path = QLineEdit(current if current.startswith("/") else "")
        self.path.setReadOnly(True)
        pick = QPushButton("Choose file…")
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(pick)
        form.addRow("Theme icon", self.name)
        form.addRow("Image file", row)
        lay.addLayout(form)
        self.error = QLabel("")
        self.error.setProperty("role", "error")
        lay.addWidget(self.error)
        b = QHBoxLayout()
        reset = QPushButton("Use the application's icon")
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        b.addWidget(reset)
        b.addStretch(1)
        b.addWidget(cancel)
        b.addWidget(ok)
        lay.addLayout(b)
        self.value = None
        pick.clicked.connect(self._pick)
        reset.clicked.connect(lambda: self._done(""))
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._ok)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Icon file", "", "Images (*.png *.svg *.xpm)")
        if path:
            self.path.setText(path)
            self.name.clear()

    def _ok(self):
        if self.path.text():
            if not D.icon_file_ok(self.path.text()):
                self.error.setText("Not usable: must be an existing .png/.svg/.xpm file of at most 2 MiB.")
                return
            if self.path.text().lower().endswith(".svg"):
                from task_launcher.icons import svg_is_safe

                try:
                    ok = svg_is_safe(open(self.path.text(), "rb").read())
                except OSError:
                    ok = False
                if not ok:
                    self.error.setText("SVG refused: too large, or contains scripts/external references.")
                    return
            self._done(self.path.text())
        else:
            name = self.name.text().strip()
            import re

            if name and not re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", name):
                self.error.setText("Theme icon names contain only letters, digits and . _ + -")
                return
            self._done(name)

    def _done(self, value):
        self.value = value
        self.accept()
