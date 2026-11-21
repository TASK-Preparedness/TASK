# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""libzim layer: metadata, main page, entries, redirects, search modes, corrupt archives, EPUB, local."""

import pytest

import zimfactory
from task_resources import fileinfo
from task_resources.docs.epub import EpubSource
from task_resources.docs.local import LocalSource
from task_resources.zim.archive import EntryNotFound, RedirectLoop, ZimArchive, ZimError, join


def test_metadata_main_page_and_entries(zim):
    z = ZimArchive(zim)
    md = z.metadata()
    assert md["Title"] == "Field Manual" and md["Language"] == "eng" and md["Name"] == "field_manual"
    assert z.main_path() == "Home"
    c = z.get("Home")
    assert c.is_html and b"Field Manual" in c.data
    img = z.get("img/logo.png")
    assert img.mimetype == "image/png" and img.data.startswith(b"\x89PNG")
    assert z.get("-/style.css").data.startswith(b".note")
    with pytest.raises(EntryNotFound):
        z.get("Nope")


def test_redirects_and_loops(tmp_path):
    z = ZimArchive(zimfactory.make_zim(tmp_path / "l.zim", loop=True))
    assert z.resolve("Purify") == ("Boiling_water", ["Purify"])
    c = z.get("Purify")
    assert c.path == "Boiling_water" and c.redirected_from == ["Purify"]
    with pytest.raises(RedirectLoop):
        z.get("LoopA")


def test_fulltext_search_and_title_suggestions(zim):
    z = ZimArchive(zim)
    assert z.has_fulltext
    r = z.search("purify")
    assert r.mode == "full-text" and "Boiling_water" in [p for p, _ in r.hits] and r.note == ""
    s = z.suggest("Boil")
    assert s.mode == "title-only" and ("Boiling_water", "Boiling water") in s.hits


def test_zim_without_index_says_title_search_only(tmp_path):
    z = ZimArchive(zimfactory.make_zim(tmp_path / "n.zim", fulltext=False))
    assert not z.has_fulltext
    r = z.search("Boil")
    assert r.mode == "title-only" and "no full-text index" in r.note
    assert ("Boiling_water", "Boiling water") in r.hits


def test_item_size_cap(zim):
    with pytest.raises(ZimError):
        ZimArchive(zim, max_item=10).get("Home")


@pytest.mark.parametrize("mutate", ["truncate", "magic", "empty"])
def test_invalid_or_corrupt_zim(tmp_path, zim, mutate):
    data = zim.read_bytes()
    bad = tmp_path / f"bad-{mutate}.zim"
    bad.write_bytes({"truncate": data[:len(data) // 3], "magic": b"XXXX" + data[4:], "empty": b""}[mutate])
    with pytest.raises((ZimError, fileinfo.CorruptFile, fileinfo.UnsupportedFile)):
        fileinfo.read(bad)
        ZimArchive(bad).get("Home")


def test_join_never_escapes_root():
    assert join("guides/Filters", "../img/logo.png") == "img/logo.png"
    assert join("Home", "../../../etc/passwd") == "etc/passwd"
    assert join("a/b/c", "/x/y#frag") == "x/y"
    assert join("Home", "Boiling_water?x=1") == "Boiling_water"


def test_epub_source(tmp_path):
    e = EpubSource(zimfactory.make_epub(tmp_path / "s.epub"))
    assert e.metadata()["Title"] == "Survival Notes"
    assert e.main_path() == "OEBPS/ch1.xhtml" and e.chapters()[1] == "OEBPS/ch2.xhtml"
    assert e.get("OEBPS/images/fire.png").data.startswith(b"\x89PNG")
    with pytest.raises(ZimError, match="DRM"):
        EpubSource(zimfactory.make_epub(tmp_path / "d.epub", drm=True))


def test_local_source_stays_in_its_folder(tmp_path):
    d = tmp_path / "doc folder"
    d.mkdir()
    (d / "page.html").write_text("<p>hi</p>")
    (tmp_path / "secret.txt").write_text("no")
    s = LocalSource(d / "page.html")
    assert s.get("page.html").data == b"<p>hi</p>"
    with pytest.raises(EntryNotFound):
        s.get("../secret.txt")


def test_fileinfo_kinds_and_unsupported(tmp_path, zim):
    assert fileinfo.read(zim).kind == "zim" and fileinfo.read(zim).metadata_source == "libzim"
    p = zimfactory.make_pdf(tmp_path / "a.pdf")
    assert fileinfo.read(p).kind == "pdf"
    assert fileinfo.read(zimfactory.make_epub(tmp_path / "b.epub")).title == "Survival Notes"
    (tmp_path / "n.md").write_text("# Notes\n")
    assert fileinfo.read(tmp_path / "n.md").kind == "md"
    (tmp_path / "x.exe").write_bytes(b"MZ\x90\x00")
    with pytest.raises(fileinfo.UnsupportedFile):
        fileinfo.read(tmp_path / "x.exe")
    (tmp_path / "fake.pdf").write_text("not a pdf")
    with pytest.raises(fileinfo.CorruptFile):
        fileinfo.read(tmp_path / "fake.pdf")


def test_zim_header_fallback_without_libzim(zim, monkeypatch):
    monkeypatch.setattr(fileinfo, "_Archive", None)
    i = fileinfo.read(zim)
    assert i.metadata_source == "zim-header" and i.zim_uuid == ZimArchive(zim).uuid
