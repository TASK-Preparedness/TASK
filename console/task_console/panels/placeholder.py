# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Module placeholder: the manifest fields, and no fake functionality (PHASE-2.md section 7.4)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QPushButton, QVBoxLayout

from task_console.panels.base import DASH, UNAVAILABLE, WITHHELD, Panel, dash, plain, title
from task_console.panels.home import capability_status

NO_INTERFACE = "This module has no interface in Phase 2."


class PlaceholderPanel(Panel):
    key = "module"
    title_text = "Module"
    back = Signal()

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.module_id = None
        layout = QVBoxLayout(self)
        self.back_button = QPushButton("\u2190 Home")
        self.back_button.clicked.connect(self.back)
        layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.heading = title(self.title_text)
        layout.addWidget(self.heading)
        form = QFormLayout()
        self.fields = {}
        for key in ("Name", "Version", "Summary", "State", "Reason", "Capabilities", "Logical devices"):
            value = plain(DASH, selectable=True)
            self.fields[key] = value
            form.addRow(plain(key, wrap=False), value)
        layout.addLayout(form)
        self.note = plain(NO_INTERFACE)
        layout.addWidget(self.note)
        layout.addStretch(1)

    def set_module(self, module_id: str) -> None:
        self.module_id = module_id
        self.render("all")

    def render(self, area: str = "all") -> None:
        controller = self.ctx.controller
        module = None
        for entry in controller.modules or []:
            if entry.get("id") == self.module_id:
                module = entry
        if module is None:
            for value in self.fields.values():
                value.setText(DASH)
            self.heading.setText(self.title_text)
            return
        self.heading.setText(dash(module.get("name")))
        self.fields["Name"].setText(dash(module.get("name")))
        self.fields["Version"].setText(dash(module.get("version")))
        self.fields["Summary"].setText(dash(module.get("summary")))
        self.fields["State"].setText(dash(module.get("state")) if controller.live else UNAVAILABLE)
        self.fields["Reason"].setText(dash(module.get("reason")))
        requires = ((module.get("capabilities") or {}).get("requires")) or []
        self.fields["Capabilities"].setText(
            "; ".join(f"{name} {capability_status(controller, name)}" for name in requires) or DASH)
        if not controller.signed_in:
            self.fields["Logical devices"].setText(WITHHELD)
        else:
            self.fields["Logical devices"].setText(dash(module.get("logical_devices")))
