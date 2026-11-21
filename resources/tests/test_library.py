# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Section 11: discovery, duplicates, categories, metadata persistence, missing files, read-only
collections, paths with spaces, corrupt/unsupported files, large collections, title search,
background-job cancellation, file permissions."""

import hashlib
import os
import shutil
import stat
import time
from pathlib import Path

import pytest

import zimfactory
from conftest import register
from task_resources import discovery, importer, managed
from task_resources.index import UNCATEGORISED, DuplicateResource, Index, fts_query
from task_resources.jobs import CANCELLED, DONE, JobRunner


def tree_state(root):
    """Every path below root with mode, size, mtime_ns and sha256: proves nothing was written."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        st = p.lstat()
        out[str(p)] = (stat.S_IMODE(st.st_mode), st.st_size, st.st_mtime_ns,
                       hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    return out


def test_discovery_folders_library_xml_and_kiwix_desktop(library, settings, tmp_path, zim):
    other = tmp_path / "elsewhere"
    other.mkdir()
    z2 = zimfactory.make_zim(other / "second.zim", title="Second", name="second")
    (tmp_path / "lib/library.xml").write_text(f'<library version="20110515"><book id="x" path="{z2}" '
                                              'title="Second"/></library>')
    kd = Path(settings.expanded_kiwix_desktop())
    kd.mkdir(parents=True)
    z3 = zimfactory.make_zim(other / "third.zim", title="Third", name="third")
    (kd / "library.xml").write_text('<library><book id="y" path="../../../../elsewhere/third.zim"/></library>')
    (tmp_path / "lib/notes.txt").write_text("water notes")
    rep = discovery.scan(library.index, settings)
    titles = sorted(r["title"] for r in library.index.list())
    assert titles == ["Field Manual", "Second", "Third", "notes"], (titles, rep.errors)
    sources = {Path(r["path"]).name: r["source"] for r in library.index.list()}
    assert sources["second.zim"] == "library-xml" and sources["Field Manual.zim"] == "scan"
    assert rep.added == 4 and not rep.errors
    rep2 = discovery.scan(library.index, settings)
    assert rep2.unchanged == 4 and rep2.added == 0


def test_duplicate_detection(library, settings, tmp_path, zim):
    rid = register(library, zim)
    copy = tmp_path / "lib/sub/copy of manual.zim"
    copy.parent.mkdir()
    shutil.copy(zim, copy)
    rep = discovery.Report()
    assert discovery.register(library.index, copy, "import", rep, keep_duplicate=False) is None
    assert rep.duplicates == 1 and "UUID" in rep.errors[0][1]
    # a scan records it, linked and hidden, so the user sees "other copies"
    discovery.scan(library.index, settings)
    assert len(library.index.list()) == 1
    assert library.index.get(rid)["copies"] == [os.path.realpath(copy)]
    # same text content under another name -> fingerprint duplicate
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    register(library, tmp_path / "a.txt")
    with pytest.raises(DuplicateResource):
        from task_resources import fileinfo
        i = fileinfo.read(tmp_path / "b.txt")
        library.index.upsert(i, fileinfo.fingerprint(tmp_path / "b.txt"), "import")
    # same real path through a symlink is the same resource, not a new one
    (tmp_path / "link.zim").symlink_to(zim)
    assert register(library, tmp_path / "link.zim") == rid


def test_categories_many_to_many(library, tmp_path, zim):
    a = register(library, zim)
    (tmp_path / "t.txt").write_text("x")
    b = register(library, tmp_path / "t.txt")
    idx = library.index
    idx.set_categories(a, ["Medical", "Water"])
    idx.add_to_category(b, "Water")
    assert [r["id"] for r in idx.list(category="Water")] == sorted([a, b], key=lambda i: idx.get(i)["title"].lower())
    assert [r["id"] for r in idx.list(category="Medical")] == [a]
    assert dict(idx.categories()) == {"Medical": 1, "Water": 2}
    idx.rename_category("Water", "Water & Sanitation")
    assert idx.get(b)["categories"] == ["Water & Sanitation"]
    idx.delete_category("Medical")
    assert idx.get(a)["categories"] == ["Water & Sanitation"] and idx.get(a) is not None
    idx.set_categories(b, [])
    assert [r["id"] for r in idx.list(category=UNCATEGORISED)] == [b]
    with pytest.raises(ValueError):
        idx.create_category("   ")


def test_metadata_edits_persist_and_survive_rescan(library, settings, tmp_path, zim):
    rid = register(library, zim)
    library.index.set_override(rid, "title", "My Water Manual")
    library.index.set_override(rid, "notes", "checked 2026")
    library.close()
    from task_resources.library import Library
    lib2 = Library(settings, tmp_path / "data/index.sqlite")
    discovery.scan(lib2.index, settings)
    os.utime(zim, (time.time() + 5, time.time() + 5))      # file "changed" -> re-read on next scan
    discovery.scan(lib2.index, settings)
    r = lib2.index.get(rid)
    assert r["title"] == "My Water Manual" and r["extracted"]["title"] == "Field Manual"
    assert r["notes"] == "checked 2026"
    assert [x["id"] for x in lib2.index.list(query="water manual")] == [rid]
    lib2.index.clear_override(rid, "title")
    assert lib2.index.get(rid)["title"] == "Field Manual"
    with pytest.raises(ValueError):
        lib2.index.set_override(rid, "path", "/etc/passwd")
    lib2.close()


def test_missing_files_are_marked_not_deleted(library, settings, tmp_path, zim):
    rid = register(library, zim)
    library.index.add_bookmark(rid, "Home", "Home")
    moved = tmp_path / "moved.zim"
    os.rename(zim, moved)
    discovery.scan(library.index, settings)
    r = library.index.get(rid)
    assert r["missing"] == 1 and library.index.counts()["missing"] == 1
    assert library.index.bookmarks()[0]["missing"] == 1
    from task_resources.library import NotReadable
    with pytest.raises(NotReadable):
        library.source(rid)
    os.rename(moved, zim)
    discovery.scan(library.index, settings)
    assert library.index.get(rid)["missing"] == 0


def test_read_only_collection_is_never_written(library, settings, tmp_path):
    ro = tmp_path / "lib/ro collection"
    ro.mkdir()
    zimfactory.make_zim(ro / "ro.zim", title="Read Only", name="ro")
    (ro / "guide.html").write_text("<title>Guide</title><p>x</p>")
    for p in [ro / "ro.zim", ro / "guide.html"]:
        p.chmod(0o444)
    ro.chmod(0o555)
    try:
        before = tree_state(tmp_path / "lib")
        rep = discovery.scan(library.index, settings)
        rid = [r["id"] for r in library.index.list() if r["title"] == "Read Only"][0]
        library.index.set_override(rid, "title", "Edited")
        library.index.set_categories(rid, ["X"])
        library.source(rid).get("Home")
        library.source(rid).search("purify")
        assert tree_state(tmp_path / "lib") == before and not rep.errors
    finally:
        ro.chmod(0o755)


def test_paths_with_spaces_and_unicode(library, settings, tmp_path):
    d = tmp_path / "lib/My Docs/Über Wasser"
    d.mkdir(parents=True)
    zimfactory.make_zim(d / "field manual (2026).zim", name="fm2026")
    zimfactory.make_epub(d / "survival notes.epub")
    rep = discovery.scan(library.index, settings)
    paths = sorted(r["path"] for r in library.index.list())
    assert any(p.endswith("field manual (2026).zim") for p in paths) and not rep.errors
    rid = [r["id"] for r in library.index.list() if r["kind"] == "epub"][0]
    assert library.source(rid).get(library.source(rid).main_path()).is_html


def test_invalid_corrupt_and_unsupported_files_are_reported(library, settings, tmp_path, zim):
    lib = tmp_path / "lib"
    (lib / "broken.zim").write_bytes(zim.read_bytes()[:500])
    (lib / "fake.epub").write_bytes(b"PK\x03\x04garbage")
    (lib / "empty.pdf").write_bytes(b"")
    (lib / "program.exe").write_bytes(b"MZ")                  # not scanned (unsupported extension)
    (lib / "split.zimaa").write_bytes(b"ZIM\x04" + b"\0" * 100)
    rep = discovery.scan(library.index, settings)
    errs = {Path(p).name: why for p, why in rep.errors}
    assert set(errs) == {"broken.zim", "fake.epub", "empty.pdf", "split.zimaa"}, errs
    assert "split ZIM" in errs["split.zimaa"]
    assert [r["title"] for r in library.index.list()] == ["Field Manual"]
    res = importer.import_paths(library, [str(lib / "program.exe")])
    assert res[0].status == "error" and "unsupported" in res[0].message


@pytest.mark.slow
def test_large_collection_indexing(library, settings, tmp_path):
    big = tmp_path / "lib/big"
    big.mkdir()
    n = 3000
    for i in range(n):
        (big / f"note {i:04d}.txt").write_text(f"note {i} about item{i}")
    zimfactory.make_zim(big / "large.zim", name="large", extra_articles=2000)
    t0 = time.monotonic()
    rep = discovery.scan(library.index, settings)
    first = time.monotonic() - t0
    assert rep.added == n + 1 and not rep.errors
    t0 = time.monotonic()
    rep2 = discovery.scan(library.index, settings)
    second = time.monotonic() - t0
    assert rep2.unchanged == n + 1
    hits = library.index.list(query="note 1234")
    assert hits and hits[0]["title"] == "note 1234"
    rid = [r["id"] for r in library.index.list(kind="zim")][0]
    assert library.index.get(rid)["article_count"] >= 2000
    assert library.source(rid).get("Article_1999").title == "Article 1999"
    print(f"\nlarge collection: {n + 1} files, first scan {first:.2f}s, rescan {second:.2f}s")
    assert first < 120 and second < first


def test_title_search_query_is_safe():
    assert fts_query('water" OR title:* NEAR(') == '"water"* "OR"* "title"* "NEAR"*'
    assert fts_query("  ") == ""


def test_background_scan_cancellation(library, settings, tmp_path):
    big = tmp_path / "lib/many"
    big.mkdir()
    for i in range(4000):
        (big / f"n{i}.txt").write_text(str(i))
    runner = JobRunner()
    job = runner.start("scan", lambda j: discovery.scan(library.index, settings, j))
    deadline = time.monotonic() + 30
    while job.done < 50 and time.monotonic() < deadline:
        time.sleep(0.005)
    job.cancel()
    assert job.wait(30)
    assert job.state == CANCELLED
    assert library.index.counts()["total"] < 4000
    job2 = runner.start("scan", lambda j: discovery.scan(library.index, settings, j))
    job2.wait(120)
    assert job2.state == DONE and library.index.counts()["total"] == 4000


def test_managed_copy_cancellation_leaves_no_partial_file(library, settings, tmp_path):
    src = tmp_path / "big.txt"
    src.write_bytes(b"a" * (8 * 1024 * 1024))
    runner = JobRunner()
    started = []

    def fn(job):
        orig = job.progress

        def slow(**kw):
            started.append(1)
            time.sleep(0.01)
            return orig(**kw)
        job.progress = slow
        return managed.copy_in(src, settings, "Docs", job)
    job = runner.start("copy", fn)
    while not started:
        time.sleep(0.001)
    job.cancel()
    job.wait(30)
    assert job.state == CANCELLED
    dest = Path(settings.managed_root) / "Docs"
    assert list(dest.iterdir()) == []         # no .part, no half file


def test_managed_storage_explicit_only_with_fallback(library, settings, tmp_path, zim):
    # registering never creates managed storage
    register(library, zim)
    assert not Path(settings.managed_root).exists()
    # unwritable managed root -> per-user fallback, and the user is told
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    settings.managed_root = str(locked / "task-resources")
    try:
        (tmp_path / "doc.txt").write_text("doc")
        res = importer.import_paths(library, [str(tmp_path / "doc.txt")], categories=["Docs"], managed_copy=True)
        assert res[0].status == "copied" and "not writable" in res[0].message
        assert not (locked / "task-resources").exists()
        r = library.index.get(res[0].rid)
        assert r["managed"] == 1 and "/.local/share/task-resources/managed/Docs/" in r["path"]
        # a second copy never overwrites
        res2 = importer.import_paths(library, [str(tmp_path / "doc.txt")], categories=["Docs"], managed_copy=True)
        assert res2[0].status == "copied" and res2[0].rid != res[0].rid
        assert Path(library.index.get(res2[0].rid)["path"]).name == "doc (1).txt"
    finally:
        locked.chmod(0o755)


def test_managed_copy_refuses_without_free_space(library, settings, tmp_path):
    (tmp_path / "doc.txt").write_text("doc")
    settings.free_space_reserve_mb = 10 ** 9
    res = importer.import_paths(library, [str(tmp_path / "doc.txt")], managed_copy=True)
    assert res[0].status == "error" and "free space" in res[0].message


def test_import_tab_a_register_in_place_with_category_and_metadata(library, tmp_path, zim):
    before = tree_state(zim.parent)
    res = importer.import_paths(library, [str(zim)], categories=["Water"],
                                overrides={"title": "Water Manual", "description": ""})
    assert res[0].status == "registered"
    r = library.index.get(res[0].rid)
    assert r["path"] == os.path.realpath(zim) and r["categories"] == ["Water"] and r["title"] == "Water Manual"
    assert tree_state(zim.parent) == before
    again = importer.import_paths(library, [str(zim)])
    assert again[0].rid == res[0].rid               # same path: no second entry


def test_file_permissions(library, settings, tmp_path, isolated_home):
    from task_resources import settings as sm
    p = sm.save(settings)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    db = tmp_path / "data/index.sqlite"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600 and stat.S_IMODE(db.parent.stat().st_mode) == 0o700
    for side in ("-wal", "-shm"):
        f = Path(str(db) + side)
        if f.exists():
            assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert sm.load(p).viewer == settings.viewer


def test_bookmarks_and_history(library, zim):
    rid = register(library, zim)
    idx = library.index
    idx.add_bookmark(rid, "Boiling_water", "Boiling water")
    idx.add_bookmark(rid, "Boiling_water", "Boiling water (renamed)")
    assert [(b["path"], b["title"]) for b in idx.bookmarks()] == [("Boiling_water", "Boiling water (renamed)")]
    for i in range(idx.HISTORY_MAX + 20):
        idx.add_history(rid, f"p{i}")
    h = idx.history(limit=1000)
    assert len(h) == idx.HISTORY_MAX and h[0]["path"] == f"p{idx.HISTORY_MAX + 19}"
    idx.clear_history()
    assert idx.history() == []


def test_newer_index_schema_is_refused(tmp_path):
    i = Index(tmp_path / "x.sqlite")
    with i.db:
        i.db.execute("UPDATE meta SET value='99' WHERE key='schema'")
    i.close()
    with pytest.raises(RuntimeError):
        Index(tmp_path / "x.sqlite")


def test_d31_audit_existing_resources_read_fully_offline(library, settings, zim, monkeypatch):
    """Audit: with every socket refused (network down / offline), existing resources still open, read and search."""
    import socket
    from conftest import register

    def refuse(*a, **k):
        raise OSError("network disabled by test")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    rid = register(library, zim)
    src = library.source(rid)
    page = src.get(src.main_path()) if hasattr(src, "main_path") else None
    from task_resources.zim.archive import ZimArchive
    z = ZimArchive(zim)
    assert b"Field Manual" in z.get(z.main_path()).data
    assert z.search("purify")
    assert page is None or page.data
    discovery.scan(library.index, settings)
    assert library.index.get(rid)["missing"] == 0
