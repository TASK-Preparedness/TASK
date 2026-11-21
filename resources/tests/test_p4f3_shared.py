# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F.3 (task-resources 0.2.2): read-only index mode, medical classification, embeddable ResourceBrowser."""

import hashlib
import sqlite3

import pytest

import zimfactory
from conftest import register, wait_until
from task_resources import classify
from task_resources.index import Index, ReadOnlyIndex
from task_resources.library import Library


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree(d):
    """Hashes of the index DATABASE file, plus proof that any WAL sidecar SQLite created for a read-only
    reader holds no data (an empty -wal; -shm is SQLite's shared-memory lock map, never data)."""
    wal = d / "index.sqlite-wal"
    assert not wal.exists() or wal.stat().st_size == 0
    return sha(d / "index.sqlite")


@pytest.fixture
def populated(settings, tmp_path):
    lib = Library(settings, tmp_path / "data/index.sqlite")
    z1 = zimfactory.make_zim(tmp_path / "lib/mdwiki_en_all.zim", title="MDWiki medical encyclopedia", name="mdwiki_en_all")
    z2 = zimfactory.make_zim(tmp_path / "lib/ham.zim", title="Amateur Radio Handbook", name="ham_radio")
    z3 = zimfactory.make_zim(tmp_path / "lib/fm.zim", title="Field Manual", name="fm_first_aid", fulltext=False)
    ids = [register(lib, p) for p in (z1, z2, z3)]
    lib.index.set_categories(ids[1], ["Radio"])
    lib.close()
    return tmp_path / "data/index.sqlite", ids, (z1, z2, z3)


def test_r01_read_only_index_changes_nothing(populated, settings):
    path, ids, zims = populated
    before = tree(path.parent), [sha(z) for z in zims]
    lib = Library(settings, path, read_only=True)
    assert lib.index.read_only and len(lib.index.list()) == 3
    assert lib.source(ids[0]).search("altitude").hits            # full-text read works
    lib.index.add_history(ids[0], "Home")                         # silently skipped
    for fn in (lambda: lib.index.add_bookmark(ids[0], "Home"), lambda: lib.index.set_categories(ids[0], ["x"]),
               lambda: lib.index.remove(ids[0]), lambda: lib.index.check_files()):
        with pytest.raises(ReadOnlyIndex):
            fn()
    with pytest.raises(sqlite3.OperationalError):                 # even raw SQL cannot write
        lib.index.db.execute("INSERT INTO meta VALUES('x','y')")
    lib.close()
    lib.index.close()
    assert (tree(path.parent), [sha(z) for z in zims]) == before


def test_r02_read_only_refuses_missing_newer_and_corrupt(tmp_path):
    with pytest.raises(FileNotFoundError):
        Index(tmp_path / "none.sqlite", read_only=True)
    assert not (tmp_path / "none.sqlite").exists()
    p = tmp_path / "new.sqlite"
    Index(p).db.execute("UPDATE meta SET value='99' WHERE key='schema'").connection.commit()
    with pytest.raises(RuntimeError, match="newer"):
        Index(p, read_only=True)
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database" * 100)
    h = sha(bad)
    with pytest.raises(RuntimeError, match="unreadable"):
        Index(bad, read_only=True)
    assert sha(bad) == h


@pytest.mark.parametrize("meta,reason", [
    ({"title": "MDWiki medical encyclopedia", "name": "mdwiki_en_all_maxi"}, "MDWiki"),
    ({"title": "WikEM", "name": "wikem_en_all"}, "WikEM"),
    ({"title": "MedlinePlus", "name": "medlineplus.gov_en_all"}, "MedlinePlus"),
    ({"title": "Medicine LibreTexts", "name": "libretexts.org_en_med"}, "Medicine LibreTexts"),
    ({"title": "Military Medicine", "name": "fas-military-medicine_en"}, "Military Medicine"),
    ({"title": "Medical Library", "name": "zimgit-medicine_en"}, "Medical Library"),
    ({"title": "Ham radio", "categories": ["Medical"]}, "category: Medical"),
    ({"title": "First Aid basics"}, "keyword: first aid"),
])
def test_r03_medical_classification_rules(meta, reason):
    assert classify.medical_reason(meta) == reason


@pytest.mark.parametrize("meta", [{"title": "Amateur Radio Handbook", "name": "ham_radio"},
                                  {"title": "Wikipedia", "name": "wikipedia_en_all"},
                                  {"title": "Power surge protection", "name": "surge"},
                                  {"title": "Systems engineering", "name": "systems"}])
def test_r04_non_medical_not_matched(meta):
    assert classify.medical_reason(meta) == ""


def test_r05_scoped_browser_lists_reads_searches_and_bookmarks(qapp, populated, settings, tmp_path):
    from task_resources.ui.browser import ALL, BOOKMARKS, EVERYTHING, JsonBookmarks, ResourceBrowser, Scope
    path, ids, zims = populated
    before = tree(path.parent)
    lib = Library(settings, path, read_only=True)
    bm = JsonBookmarks(tmp_path / "state/bm.json", lib.index)
    b = ResourceBrowser(lib, "lightweight", Scope("medical", "Medical", classify.medical_reason), bm)
    b.refresh()
    titles = sorted(b.items.item(i).text() for i in range(b.items.count()))
    assert len(titles) == 2 and "Amateur" not in " ".join(titles)          # filtered by default
    keys = [b.cats.item(i).data(0x0100) for i in range(b.cats.count())]
    assert keys[0] == ALL and BOOKMARKS in keys and EVERYTHING in keys
    b.items.setCurrentRow([i for i, t in enumerate(titles) if "MDWiki" in b.items.item(i).text()][0])
    assert "Listed because" in b.details.toPlainText() and "MDWiki" in b.details.toPlainText()
    assert b.open_current() and b.view.nav.current.path == "Home"           # embedded reader
    b.inside.setText("altitude")
    assert b.search_inside().mode == "full-text" and b.hits.count() == 1
    b.view.open(b.view.nav.current.rid, "Boiling_water")
    assert b.view_back() and b.view.nav.current.path == "Home" and b.view_forward()
    assert b.bookmark() and bm.list()[0]["path"] == "Boiling_water"
    b.contents.setChecked(True)
    b.find.setText("altitude")
    b.search_contents(wait=True)
    hits = [b.items.item(i).text() for i in range(b.items.count())]
    assert any("in MDWiki" in h for h in hits)
    b.find.setText("")
    b.cats.setCurrentRow(keys.index(BOOKMARKS))
    assert b.items.count() == 1
    b.items.setCurrentRow(0)
    assert b.open_current() and b.view.nav.current.path == "Boiling_water"
    b.shutdown()
    lib.close()
    lib.index.close()
    assert tree(path.parent) == before and [sha(z) for z in zims] == [sha(z) for z in zims]


def test_r06_missing_and_corrupt_zim_errors(qapp, settings, tmp_path):
    from task_resources.ui.browser import ResourceBrowser
    lib = Library(settings, tmp_path / "data/index.sqlite")
    z = zimfactory.make_zim(tmp_path / "lib/medical_a.zim", title="Medical A", name="med_a")
    rid = register(lib, z)
    b = ResourceBrowser(lib, "lightweight")
    data = bytearray(z.read_bytes())
    z.write_bytes(bytes(data[:200]))                                       # truncated -> corrupt
    lib.pool.clear()
    assert not b.open_resource(rid) and "could not be read" in b.mode.text()
    z.unlink()
    assert not b.open_resource(rid) and "File missing" in b.mode.text()
    b.shutdown()
    lib.close()


def test_r07_one_reader_instance_engine_switch_reuses(qapp, library):
    from task_resources.ui.browser import ResourceBrowser
    b = ResourceBrowser(library, "lightweight")
    v1 = b.view
    b.set_engine("lightweight")
    assert b.view is v1 and len(b.reader._viewers) == 1
    b.shutdown()


def test_r08_standalone_window_unchanged_api(qapp, library, zim, tmp_path):
    from task_resources.ui.main_window import MainWindow
    rid = register(library, zim)
    w = MainWindow(library, settings_path=tmp_path / "s.json", scan_on_start=False)
    w.refresh()
    assert w.items.count() == 1 and w.find is w.browser.find
    assert w.open_resource(rid) and w.view.nav.current.path == "Home"
    w.bookmark()
    assert library.index.bookmarks()                                  # standalone keeps index bookmarks
    assert w.edit_btn.parent() is not None and w.delete_btn.parent() is not None
    w.close()
    w.deleteLater()
    qapp.processEvents()
    assert wait_until(qapp, lambda: True, 0.1)
