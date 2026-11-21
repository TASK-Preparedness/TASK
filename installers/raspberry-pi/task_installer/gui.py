# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PySide6 installation wizard (pre-alpha skeleton, DRY RUN ONLY).

Pages: Welcome -> Hardware -> Compatibility -> Installation type -> Modules ->
Summary -> Confirm/Progress -> Finish. The wizard always runs as the normal
desktop user and refuses to start as root (project rule: no root GUI).
Privileged package steps are shown as exact commands; this version does not
execute them.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QProgressBar, QRadioButton, QVBoxLayout,
                               QWizard, QWizardPage)

from . import __version__
from .catalog import CATALOG, INSTALLABLE
from .compat import MODELS, evaluate
from .executor import DryRunExecutor
from .plan import COMPLETE, CUSTOM, MINIMAL, SOURCE_OFFLINE, install_plan, select
from .tui import report


class _Page(QWizardPage):
    def __init__(self, title, subtitle=""):
        super().__init__()
        self.setTitle(title)
        if subtitle:
            self.setSubTitle(subtitle)
        self.lay = QVBoxLayout(self)

    def label(self, text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(lb)
        return lb


class InstallerWizard(QWizard):
    def __init__(self, facts, manual=None):
        super().__init__()
        self.facts = facts
        self.manual = manual
        self.verdict = evaluate(facts, manual)
        self.plan = None
        self.setWindowTitle(f"T.A.S.K. Installer {__version__} (pre-alpha, dry run)")
        self.setOption(QWizard.NoBackButtonOnLastPage, True)

        # Welcome
        p = _Page("Welcome to T.A.S.K.", "Free, open-source, offline-first emergency preparedness tools.")
        p.label("This pre-alpha installer checks your Raspberry Pi and shows exactly what would be installed. "
                "In this version it does not install anything (dry run). It never flashes radios, never "
                "transmits, and never takes control of connected devices.")
        self.addPage(p)

        # Hardware
        self.hw = _Page("Your hardware", "Detected read-only. Correct the board model if needed.")
        self.hw_text = QPlainTextEdit(readOnly=True)
        self.hw.lay.addWidget(self.hw_text)
        self.model_box = QComboBox()
        self.model_box.addItem("Use detected board", None)
        for fam, m in MODELS.items():
            self.model_box.addItem(f"{m.label} ({m.status})", fam)
        self.model_box.currentIndexChanged.connect(self._model_changed)
        self.hw.lay.addWidget(self.model_box)
        self.addPage(self.hw)

        # Compatibility
        self.cp = _Page("Compatibility check", "Architecture and OS checks always use detected values.")
        self.cp_label = self.cp.label("")
        self.cp.isComplete = lambda: self.verdict.ok
        self.addPage(self.cp)

        # Mode
        self.md = _Page("Installation type")
        self.mode_group = QButtonGroup(self.md)
        self.mode_buttons = {}
        for mode, text in [(COMPLETE, "Complete — every compatible released module"),
                           (CUSTOM, "Custom — choose modules"),
                           (MINIMAL, "Minimal — launcher and core only")]:
            rb = QRadioButton(text)
            self.mode_group.addButton(rb)
            self.mode_buttons[mode] = rb
            self.md.lay.addWidget(rb)
        self.mode_buttons[MINIMAL].setChecked(True)
        self.addPage(self.md)

        # Modules
        self.mo = _Page("Modules", "Maturity is shown honestly. Planned modules cannot be selected.")
        self.mod_list = QListWidget()
        for m in CATALOG:
            it = QListWidgetItem(f"{m.name} {m.version} [{m.maturity}] — {m.summary}")
            it.setData(Qt.UserRole, m.id)
            if m.maturity in INSTALLABLE:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
            else:
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsUserCheckable)
            self.mod_list.addItem(it)
        self.mo.lay.addWidget(self.mod_list)
        self.addPage(self.mo)

        # Summary
        self.su = _Page("Summary", "Review the plan. Shared dependencies were selected automatically.")
        self.su_text = QPlainTextEdit(readOnly=True)
        self.su.lay.addWidget(self.su_text)
        self.su_error = self.su.label("")
        self.su.isComplete = lambda: self.plan is not None
        self.addPage(self.su)

        # Progress
        self.pr = _Page("Install (dry run)")
        self.confirm = QCheckBox("I understand this version performs a dry run only")
        self.pr.lay.addWidget(self.confirm)
        self.bar = QProgressBar()
        self.pr.lay.addWidget(self.bar)
        self.log = QPlainTextEdit(readOnly=True)
        self.pr.lay.addWidget(self.log)
        self.confirm.toggled.connect(lambda _: self.pr.completeChanged.emit())
        self.pr.isComplete = lambda: self.confirm.isChecked()
        self.addPage(self.pr)

        # Finish
        self.fi = _Page("Finished")
        self.fi.label("Dry run complete. Nothing was installed or changed. First launch: open \"T.A.S.K.\" from the "
                      "applications menu once real packages are installed. No service was enabled and nothing starts automatically.")
        self.addPage(self.fi)
        self.currentIdChanged.connect(self._entered)
        self._refresh()

    def _model_changed(self, _):
        self.manual = self.model_box.currentData()
        self.verdict = evaluate(self.facts, self.manual)
        self._refresh()

    def _refresh(self):
        self.hw_text.setPlainText(report(self.facts, self.verdict))
        lines = ["Compatible." if self.verdict.ok else "Not compatible — installation cannot continue."]
        lines += [f"BLOCKER: {b}" for b in self.verdict.blockers] + [f"Warning: {w}" for w in self.verdict.warnings]
        self.cp_label.setText("\n".join(lines))
        minimal_only = self.verdict.profile == "minimal-only"
        for mode in (COMPLETE, CUSTOM):
            self.mode_buttons[mode].setEnabled(not minimal_only)
        if minimal_only:
            self.mode_buttons[MINIMAL].setChecked(True)
        self.cp.completeChanged.emit()

    def mode(self):
        for m, b in self.mode_buttons.items():
            if b.isChecked():
                return m
        return MINIMAL

    def checked_ids(self):
        out = []
        for i in range(self.mod_list.count()):
            it = self.mod_list.item(i)
            if it.flags() & Qt.ItemIsUserCheckable and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _entered(self, pid):
        page = self.page(pid)
        if page is self.su:
            try:
                mods = select(self.mode(), self.verdict, self.checked_ids())
                self.plan = install_plan(mods, self.verdict, SOURCE_OFFLINE)
                self.su_text.setPlainText(self.plan.render())
                self.su_error.setText("")
            except (ValueError, KeyError, PermissionError) as e:
                self.plan = None
                self.su_text.setPlainText("")
                self.su_error.setText(f"Error: {e}")
            self.su.completeChanged.emit()
        elif page is self.fi and self.plan is not None:
            def prog(i, n, d):
                self.bar.setMaximum(n)
                self.bar.setValue(i)
            DryRunExecutor(self.log.appendPlainText).run(self.plan, prog)

    def nextId(self):
        if self.currentPage() is self.md and self.mode() != CUSTOM:
            return self.pageIds()[self.pageIds().index(self.currentId()) + 2]
        return super().nextId()


def run_gui(facts, manual=None) -> int:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("Refusing to run the graphical installer as root. Run it as your normal desktop user.", file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication(sys.argv)
    w = InstallerWizard(facts, manual)
    w.show()
    return app.exec()
