# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4E UI: live Download/Catalog tabs, Downloads window, auto-refresh, managed delete, offline state."""

import hashlib
import os
from pathlib import Path

import pytest

import zimfactory
from conftest import register, wait_until
from httpfixture import Server
from task_resources import catalog as cat
from task_resources import downloads as dl
from task_resources.net import safehttp

DATA = Path(__file__).parent / "data"
POL = safehttp.Policy(any_port=True, allow_ips=frozenset({"127.0.0.1"}), timeout=5)


@pytest.fixture
def srv():
    s = Server()
    yield s
    s.close()


@pytest.fixture
def env(qapp, library, tmp_path, srv):
    from task_resources.ui.main_window import MainWindow
    client = safehttp.Client(POL)
    c = cat.Catalog(srv.url("/catalog/v2"), client, tmp_path / "cache")
    m = dl.DownloadManager(library, client, tmp_path / "dl.sqlite", catalog=c)
    w = MainWindow(library, settings_path=tmp_path / "s.json", scan_on_start=False, manager=m, catalog=c)
    w.show()
    yield w, m, c
    w.close()
    m.close()
    w.deleteLater()
    qapp.processEvents()


def test_u01_dialog_tabs_live_and_nothing_contacted_at_start(qapp, env, srv):
    w, m, c = env
    d = w.make_add_dialog()
    assert [d.tabs.tabText(i) for i in range(3)] == ["Import from Pi", "Download from Website", "Online ZIM Catalog"]
    assert d.tab_download.url.isEnabled() and d.tab_download.start.isEnabled()
    assert d.tab_catalog.update.isEnabled() and "No catalog saved yet" in d.tab_catalog.state.text()
    assert srv.routes == {} and c.online is None            # no network until the user asks


def test_u02_catalog_tab_refresh_filter_installed_enqueue(qapp, env, srv, library, tmp_path):
    w, m, c = env
    srv.add("/catalog/v2/entries?count=-1", data=(DATA / "kiwix-catalog-sample.xml").read_bytes())
    d = w.make_add_dialog()
    tab = d.tab_catalog
    tab.refresh_catalog()
    assert wait_until(qapp, lambda: tab.refresh_job is None and c.entries, 10)
    assert tab.results.rowCount() == 8 and "8 entries" in tab.state.text()
    tab.category.setCurrentIndex(tab.category.findData("gutenberg"))
    assert tab.results.rowCount() == 2 and all(tab.results.item(r, 3).text() == "gutenberg" for r in range(2))
    tab.category.setCurrentIndex(0)
    tab.query.setText("zzzz-nothing")
    assert tab.results.rowCount() == 0
    tab.query.setText("")
    tab.results.selectRow(0)
    e = tab.selected()
    assert e is tab.shown[0] and e.title in tab.detail.toPlainText()
    tid = tab.enqueue()
    assert tid and m.get(tid)["catalog_uuid"] == e.uuid and m.get(tid)["url"] == e.url
    assert tab.enqueue() is None and "already in the download list" in tab.state.text()   # no duplicates
    m.pause(tid)


def test_u03_catalog_offline_shows_cached_copy(qapp, env, srv):
    w, m, c = env
    srv.add("/catalog/v2/entries?count=-1", data=(DATA / "kiwix-catalog-sample.xml").read_bytes())
    assert c.refresh()
    srv.routes["/catalog/v2/entries?count=-1"].status = 503
    tab = w.make_add_dialog().tab_catalog
    tab.refresh_catalog()
    assert wait_until(qapp, lambda: tab.refresh_job is None, 10)
    assert "offline" in tab.state.text() and tab.results.rowCount() == 8 and m.offline


def test_u04_download_tab_preview_enqueue_and_auto_refresh(qapp, env, srv, library):
    w, m, c = env
    body = b"%PDF-1.4\n" + os.urandom(80_000)
    srv.add("/guide.pdf", data=body, ctype="application/pdf")
    tab = w.make_add_dialog().tab_download
    tab.url.setText(srv.url("/guide.pdf"))
    tab.category.setEditText("Medical")
    tab.extra.setText("Field, Medical")
    tab.run_preview()
    assert wait_until(qapp, lambda: "guide.pdf" in tab.info.text(), 10)
    assert "78.1 KB" in tab.info.text() and "resumable" in tab.info.text()
    assert "free" in tab.free.text()
    tid = tab.enqueue()
    assert tid and m.get(tid)["categories"] == '["Medical", "Field"]'
    assert wait_until(qapp, lambda: m.get(tid)["state"] == dl.DONE, 15)
    assert wait_until(qapp, lambda: w.items.count() == 1, 5)          # appears without a restart
    w.items.setCurrentRow(0)
    assert "T.A.S.K. managed" in w.details.toPlainText() and w.delete_btn.isEnabled()
    path = w.delete_current(confirm=False)
    assert path and not os.path.exists(path) and w.items.count() == 0


def test_u05_preview_reports_refusals(qapp, env):
    w, m, c = env
    tab = w.make_add_dialog().tab_download
    tab.url.setText("http://169.254.169.254/latest/meta-data/x.pdf")
    tab.run_preview()
    assert wait_until(qapp, lambda: tab.preview_job is None, 10)
    assert "Cannot download" in tab.info.text()
    tab.url.setText("file:///etc/passwd")
    assert tab.enqueue() is None and "only http/https" in tab.info.text()


def test_u06_downloads_window_tabs_and_controls(qapp, env, srv):
    w, m, c = env
    srv.add("/slow.pdf", data=b"%PDF-1.4\n" + os.urandom(2_000_000), ctype="application/pdf", delay=0.05)
    srv.add("/bad.pdf", data=b"%PDF-1.4\n" + b"x" * 1000, ctype="application/pdf")
    a = m.add(srv.url("/slow.pdf"), ["Docs"])
    b = m.add(srv.url("/bad.pdf"), ["Docs"], expected_sha256="1" * 64)
    win = w.open_downloads()
    assert wait_until(qapp, lambda: (win.refresh() or win.counts()["Active"] == 1), 10)
    win.tabs.setCurrentIndex(0)
    win.tables["Active"].selectRow(0)
    assert win.selected_id() == a
    win.pause.click()
    assert wait_until(qapp, lambda: m.get(a)["state"] == dl.PAUSED, 10)
    assert wait_until(qapp, lambda: m.get(b)["state"] == dl.FAILED, 10)
    win.refresh()
    assert win.counts()["Paused"] == 1 and win.counts()["Failed"] == 1
    t = win.tables["Paused"]
    assert t.item(0, 2).text() == "paused" and "%" in t.item(0, 3).text() and "/" in t.item(0, 4).text()
    assert "sha256 mismatch" in win.tables["Failed"].item(0, 7).text()
    assert win.tabs.tabText(2) == "Paused (1)"


def test_u07_external_resource_cannot_be_deleted(qapp, env, library, zim):
    w, m, c = env
    rid = register(library, zim)
    w.refresh()
    w.items.setCurrentRow(0)
    assert not w.delete_btn.isEnabled() and "external (protected" in w.details.toPlainText()
    assert w.delete_current(confirm=False) is None and os.path.exists(zim)
    assert library.index.get(rid) is not None
