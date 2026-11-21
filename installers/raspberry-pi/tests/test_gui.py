# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Wizard tests (offscreen Qt, simulated hosts)."""
import pytest

pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from task_installer import gui  # noqa: E402


def walk_to_end(w, qtbot):
    for _ in range(12):
        if w.currentPage() is w.pr:
            w.confirm.setChecked(True)
        if w.currentPage() is w.fi:
            break
        w.next()
    return w


def test_wizard_minimal_dry_run(qtbot, facts):
    w = gui.InstallerWizard(facts("pi5"))
    qtbot.addWidget(w)
    w.show()
    walk_to_end(w, qtbot)
    assert w.currentPage() is w.fi
    assert "task-launcher" in w.su_text.toPlainText()
    assert "Dry run" in w.log.toPlainText() or "dry run" in w.log.toPlainText()


def test_wizard_custom_selects_dependencies(qtbot, facts):
    w = gui.InstallerWizard(facts("pi5"))
    qtbot.addWidget(w)
    w.show()
    w.mode_buttons["custom"].setChecked(True)
    for i in range(w.mod_list.count()):
        it = w.mod_list.item(i)
        if it.data(Qt.UserRole) == "mesh":
            it.setCheckState(Qt.Checked)
        if it.data(Qt.UserRole) == "firmware":
            assert not (it.flags() & Qt.ItemIsUserCheckable)
    walk_to_end(w, qtbot)
    text = w.su_text.toPlainText()
    assert "python3-task-comms" in text and "task-mesh" in text


def test_wizard_blocks_incompatible(qtbot, facts):
    w = gui.InstallerWizard(facts("pi5", arch="amd64"))
    qtbot.addWidget(w)
    w.show()
    w.next(); w.next()
    assert w.currentPage() is w.cp and not w.cp.isComplete()
    w.model_box.setCurrentIndex(1)  # manual Pi 5 cannot bypass
    assert not w.cp.isComplete()


def test_wizard_zero2w_disables_complete(qtbot, facts):
    w = gui.InstallerWizard(facts("zero2w"))
    qtbot.addWidget(w)
    assert not w.mode_buttons["complete"].isEnabled() and w.mode_buttons["minimal"].isChecked()


def test_gui_refuses_root(monkeypatch, facts):
    monkeypatch.setattr(gui.os, "geteuid", lambda: 0)
    assert gui.run_gui(facts("pi5")) == 2
