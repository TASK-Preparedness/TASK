# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Main window, Add Resource dialog (A working; B/C disabled when opened without a download manager), viewer setting."""

import pytest
from PySide6.QtWidgets import QPushButton

import zimfactory
from conftest import WEB, register, wait_until
from task_resources import settings as sm
from task_resources.ui.add_dialog import PHASE_4E, AddResourceDialog
from task_resources.viewer.pdf import qtpdf_available


@pytest.fixture
def win(qapp, library, tmp_path):
    from task_resources.ui.main_window import MainWindow
    w = MainWindow(library, settings_path=tmp_path / "s.json", scan_on_start=False)
    w.show()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_add_dialog_tabs_without_manager_are_disabled(qapp):
    d = AddResourceDialog(["Water"])
    names = [d.tabs.tabText(i) for i in range(d.tabs.count())]
    assert names == ["Import from Pi", "Download from Website", "Online ZIM Catalog"]
    a = d.tab_import
    assert a.add_files.isEnabled() and a.managed.isEnabled() and not a.managed.isChecked()
    for tab in (d.tab_download, d.tab_catalog):
        assert PHASE_4E in tab.notice.text()
        buttons = tab.findChildren(QPushButton)
        assert buttons and all(not b.isEnabled() and PHASE_4E in b.text() for b in buttons)
    for w in (d.tab_download.url, d.tab_download.format, d.tab_catalog.query, d.tab_catalog.results):
        assert not w.isEnabled()
    a.files.addItem("/x/y.zim")
    a.category.setEditText("Water")
    assert d.request() == {"paths": ["/x/y.zim"], "categories": ["Water"],
                           "overrides": {"title": "", "description": ""}, "managed_copy": False,
                           "allow_duplicate": False}


def test_window_import_list_open_search(qapp, win, library, zim):
    job = win.run_import({"paths": [str(zim)], "categories": ["Water"], "overrides": {},
                          "managed_copy": False, "allow_duplicate": False})
    assert job.wait(30) and job.state == "done"
    assert wait_until(qapp, lambda: win.items.count() == 1, 5)
    win.items.setCurrentRow(0)
    assert "Field Manual" in win.details.toPlainText() and "full-text index" in win.details.toPlainText()
    assert win.open_current()
    assert win.view.nav.current.path == "Home"
    win.inside.setText("altitude")
    res = win.search_inside()
    assert res.mode == "full-text" and win.hits.count() == 1 and "Full-text results" in win.mode.text()
    win.find.setText("nothing-matches")
    assert win.items.count() == 0
    win.find.setText("manual")
    assert win.items.count() == 1


def test_window_title_only_label(qapp, win, library, tmp_path):
    rid = register(library, zimfactory.make_zim(tmp_path / "n.zim", fulltext=False, name="n"))
    win.refresh()
    win.open_resource(rid)
    assert "Title search only" in win.mode.text()
    win.inside.setText("Boil")
    win.search_inside()
    assert "Title matches" in win.mode.text() and "no full-text index" in win.mode.text()


def test_viewer_setting_switch_persists(qapp, win, tmp_path):
    first = win.view.name
    idx = win.viewer_choice.findData("lightweight")
    win.viewer_choice.setCurrentIndex(idx)
    assert win.view.name == "lightweight" and sm.load(tmp_path / "s.json").viewer == "lightweight"
    win.viewer_choice.setCurrentIndex(win.viewer_choice.findData("webengine"))
    assert win.view.name == ("webengine" if WEB else "lightweight")
    if not WEB:
        assert "unavailable" in win.viewer_note.text()
    assert first in ("webengine", "lightweight")


@pytest.mark.skipif(not qtpdf_available()[0], reason="QtPdf not importable here")
def test_pdf_opens_in_qtpdf(qapp, win, library, tmp_path):
    rid = register(library, zimfactory.make_pdf(tmp_path / "a.pdf"))
    assert win.open_resource(rid) and "1 pages" in win.mode.text()


def test_rescan_job_runs_and_window_refreshes(qapp, win, settings, zim):
    job = win.rescan()
    assert job.wait(30) and job.state == "done"
    assert wait_until(qapp, lambda: win.items.count() == 1, 5)
