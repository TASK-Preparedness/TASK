# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Both viewers on synthetic ZIM/EPUB/HTML: images, CSS, redirects, internal links, anchors,
back/forward, search, scripts, media, tables and blocked network access. The WebEngine tests run only
where PySide6.QtWebEngine* is importable; otherwise they are reported as skipped."""

import http.server
import threading

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextCursor, QTextDocument, QTextTable

import zimfactory
from conftest import WEB, WEB_WHY, register, wait_until
from task_resources import viewer
from task_resources.viewer import urls
from task_resources.viewer.sanitize import sanitise

needs_web = pytest.mark.skipif(not WEB, reason=f"Qt WebEngine not importable here: {WEB_WHY}")


class Trap(http.server.BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        Trap.hits.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"x")

    def log_message(self, *a):
        pass


@pytest.fixture
def trap():
    Trap.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Trap)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def trapzim(tmp_path, trap):
    (tmp_path / "lib").mkdir(exist_ok=True)
    return zimfactory.make_zim(tmp_path / "lib/manual.zim", external_img=trap + "/ext.png")


# ------------------------------------------------------------------ sanitiser
def test_sanitiser_strips_scripts_handlers_media_and_rewrites_links():
    html, rep = sanitise(zimfactory.HOME.replace("EXTERNAL_IMG", "http://h/x.png").encode(), "zim", 7, "Home")
    assert "<script" not in html and "SCRIPT-RAN" not in html and "onerror" not in html
    assert rep["scripts_removed"] == 1 and rep["media_placeholders"] == 1 and rep["external_links"] == 1
    assert 'href="zim://r7/Boiling_water"' in html and 'src="zim://r7/img/logo.png"' in html
    assert 'href="zim://r7/-/style.css"' in html and 'href="#table"' in html
    assert "not playable in the lightweight viewer" in html and "<table" in html
    assert 'href="https://example.org/outside"' in html and "task-external" in html
    h2, _ = sanitise(b'<a href="javascript:alert(1)">x</a><iframe src="http://e"></iframe><p>ok</p>', "zim", 1, "a/b")
    assert "javascript" not in h2 and "iframe" not in h2 and "<p>ok</p>" in h2


# ------------------------------------------------------------------ lightweight viewer
def anchor_href(doc, text):
    """href of the link whose visible text is text (what a click on it would deliver)."""
    c = doc.find(text)
    if c.isNull():
        return None
    probe = QTextCursor(doc)
    probe.setPosition(c.selectionEnd())
    return probe.charFormat().anchorHref() or None


def char_color(doc, text):
    c = doc.find(text)
    return c.charFormat().foreground().color().name() if not c.isNull() else None


def has_table(doc):
    c = QTextCursor(doc)
    while not c.atEnd():
        if isinstance(c.currentTable(), QTextTable):
            return True
        c.movePosition(QTextCursor.MoveOperation.NextBlock)
    return False


@pytest.fixture
def light(qapp, library):
    from task_resources.viewer.light import LightViewer
    v = LightViewer(library)
    v.resize(800, 600)
    v.show()
    yield v
    v.close()


def test_light_renders_article_images_css_table_and_no_script(qapp, light, library, trapzim, trap):
    rid = register(library, trapzim)
    assert light.open(rid)
    qapp.processEvents()
    doc = light.document()
    text = doc.toPlainText()
    assert "Water purification basics." in text and "Filter then boil" in text
    assert light.last_title == "Field Manual Home"
    assert "img/logo.png" in light.loaded_resources and "-/style.css" in light.loaded_resources
    img = doc.resource(QTextDocument.ResourceType.ImageResource, QUrl(urls.make("zim", rid, "img/logo.png")))
    assert img is not None and img.width() == 4 and img.height() == 3
    assert char_color(doc, "Water purification basics.") == "#ff0000"      # from the ZIM's style.css
    assert has_table(doc)
    assert "not playable in the lightweight viewer" in text and light.report["scripts_removed"] == 1
    assert trap + "/ext.png" in light.blocked and Trap.hits == []          # never fetched
    assert light.resource_errors == []


def test_light_internal_links_redirects_anchor_back_forward(qapp, light, library, zim):
    rid = register(library, zim)
    light.open(rid)
    doc = light.document()
    href = anchor_href(doc, "Boiling water")
    assert href == urls.make("zim", rid, "Boiling_water")
    light.anchorClicked.emit(QUrl(href))
    assert light.nav.current.path == "Boiling_water" and "Boil water for one minute" in doc.toPlainText()
    assert light.back() and light.nav.current.path == "Home"
    assert light.forward() and light.nav.current.path == "Boiling_water"
    light.back()
    light.anchorClicked.emit(QUrl(anchor_href(doc, "Purify (redirect)")))       # redirect entry
    assert light.nav.current.path == "Boiling_water"
    light.back()
    light.anchorClicked.emit(QUrl(anchor_href(doc, "Filters")))                  # sub-folder + ../ image
    assert light.nav.current.path == "guides/Filters" and "img/logo.png" in light.loaded_resources
    light.anchorClicked.emit(QUrl(anchor_href(doc, "Boiling")))                  # ../ link
    assert light.nav.current.path == "Boiling_water"
    light.back(), light.back()
    depth = len(light.nav.back_stack)
    light.anchorClicked.emit(QUrl("#table"))                                      # in-page anchor
    assert light.nav.current.path == "Home" and len(light.nav.back_stack) == depth


def test_light_external_link_is_blocked_not_opened(qapp, light, library, zim):
    rid = register(library, zim)
    light.open(rid)
    events = []
    light.listeners.append(lambda e, **d: events.append((e, d)))
    href = anchor_href(light.document(), "External site")
    assert href == "https://example.org/outside"
    light.anchorClicked.emit(QUrl(href))
    assert light.nav.current.path == "Home" and ("blocked", {"url": href}) in events


def test_light_missing_entry_shows_error(qapp, light, library, zim):
    rid = register(library, zim)
    assert not light.open(rid, "Does_not_exist")
    assert "Does_not_exist" in light.last_error and "Cannot show this page" in light.document().toPlainText()


def test_light_epub_local_html_and_markdown(qapp, light, library, tmp_path):
    e = register(library, zimfactory.make_epub(tmp_path / "notes.epub"))
    light.open(e)
    assert "Fire" in light.document().toPlainText() and "OEBPS/images/fire.png" in light.loaded_resources
    light.anchorClicked.emit(QUrl(anchor_href(light.document(), "Next chapter")))
    assert light.nav.current.path == "OEBPS/ch2.xhtml" and "Shelter" in light.document().toPlainText()
    d = tmp_path / "page dir"
    d.mkdir()
    (d / "dot.png").write_bytes(zimfactory.png())
    (d / "page.html").write_text('<title>Local</title><h1>Local page</h1><img src="dot.png"><script>x()</script>')
    h = register(library, d / "page.html")
    light.open(h)
    assert "Local page" in light.document().toPlainText() and "dot.png" in light.loaded_resources
    (tmp_path / "n.md").write_text("# Heading\n\n* item one\n")
    m = register(library, tmp_path / "n.md")
    light.open(m)
    assert "item one" in light.document().toPlainText()


# ------------------------------------------------------------------ WebEngine viewer
@pytest.fixture
def web(qapp, library):
    from task_resources.viewer.web import WebViewer
    v = WebViewer(library)
    v.resize(800, 600)
    v.show()
    yield v
    v.close()
    v.deleteLater()
    qapp.processEvents()


def js(qapp, view, code):
    box = []
    view.page().runJavaScript(code, 0, lambda r: box.append(r))
    assert wait_until(qapp, lambda: box, 15), code
    return box[0]


def load(qapp, view, action, expect_change=True):
    before = view.nav.current
    view.loaded = None
    action()

    def settled():
        cur = view.nav.current
        if cur is None or view.loaded is None or (expect_change and cur == before):
            return False
        want = urls.make(view.url().scheme(), cur.rid, cur.path)
        return view.loaded[2].split("#")[0] == want and view.url().toString().split("#")[0] == want
    assert wait_until(qapp, settled, 30), (view.nav.current, view.url().toString())
    return view.loaded[0]


@needs_web
def test_web_renders_from_libzim_with_images_css_and_js(qapp, web, library, trapzim, trap):
    rid = register(library, trapzim)
    assert load(qapp, web, lambda: web.open(rid))
    assert web.url().toString() == urls.make("zim", rid, "Home")
    assert js(qapp, web, "document.getElementById('logo').naturalWidth") == 4
    assert js(qapp, web, "getComputedStyle(document.querySelector('.note')).color") == "rgb(255, 0, 0)"
    assert js(qapp, web, "document.title") == "SCRIPT-RAN"               # JS runs in WebEngine
    assert js(qapp, web, "document.getElementById('extimg').naturalWidth") == 0
    # blocked either by our interceptor or already by the "local content may not load remote URLs"
    # setting; in both cases nothing reaches the network
    assert Trap.hits == []
    assert {"Home", "img/logo.png", "-/style.css"} <= set(web.served)


@needs_web
def test_web_links_redirects_back_forward(qapp, web, library, zim):
    rid = register(library, zim)
    load(qapp, web, lambda: web.open(rid))
    load(qapp, web, lambda: js(qapp, web, "document.getElementById('l-boil').click(); 1"))
    assert web.nav.current.path == "Boiling_water"
    assert "one minute" in js(qapp, web, "document.body.innerText")
    load(qapp, web, web.back)
    assert web.nav.current.path == "Home"
    load(qapp, web, web.forward)
    assert web.nav.current.path == "Boiling_water"
    load(qapp, web, web.back)
    load(qapp, web, lambda: js(qapp, web, "document.getElementById('l-redirect').click(); 1"))
    assert web.nav.current.path == "Boiling_water"
    load(qapp, web, web.back)
    load(qapp, web, lambda: js(qapp, web, "document.getElementById('l-sub').click(); 1"))
    assert web.nav.current.path == "guides/Filters"
    assert js(qapp, web, "document.getElementById('sub-img').naturalWidth") == 4


@needs_web
def test_web_blocks_external_navigation_and_fetch(qapp, web, library, trapzim, trap):
    rid = register(library, trapzim)
    load(qapp, web, lambda: web.open(rid))
    js(qapp, web, "document.getElementById('l-ext').click(); 1")
    js(qapp, web, f"fetch('{trap}/fetch').catch(()=>0); new Image().src='{trap}/img2'; 1")
    wait_until(qapp, lambda: len(web.blocked_requests) >= 2, 5)
    assert web.nav.current.path == "Home" and "https://example.org/outside" in web.blocked
    assert web.url().toString() == urls.make("zim", rid, "Home")
    assert Trap.hits == []


@needs_web
def test_web_epub(qapp, web, library, tmp_path):
    e = register(library, zimfactory.make_epub(tmp_path / "w.epub"))
    assert load(qapp, web, lambda: web.open(e))
    assert js(qapp, web, "document.getElementById('fire').naturalWidth") == 4


# ------------------------------------------------------------------ selection / settings
def test_viewer_choice_and_automatic_fallback(monkeypatch):
    monkeypatch.setattr(viewer, "_web", (False, "not installed"))
    assert viewer.choose("auto") == ("lightweight", "")
    eng, note = viewer.choose("webengine")
    assert eng == "lightweight" and "unavailable" in note
    assert viewer.choose("lightweight") == ("lightweight", "")
    assert viewer.choose("bogus")[0] == "lightweight"
    monkeypatch.setattr(viewer, "_web", (True, ""))
    assert viewer.choose("auto") == ("webengine", "") and viewer.choose("lightweight")[0] == "lightweight"


def test_search_in_both_modes(library, zim, tmp_path):
    rid = register(library, zim)
    r = library.source(rid).search("altitude")
    assert r.mode == "full-text" and [p for p, _ in r.hits] == ["Boiling_water"]
    n = register(library, zimfactory.make_zim(tmp_path / "noidx.zim", fulltext=False, name="noidx", title="No Index"))
    r2 = library.source(n).search("Filters")
    assert r2.mode == "title-only" and "no full-text index" in r2.note and r2.hits[0][0] == "guides/Filters"


# ------------------------------------------------------------------ Phase 4E: no file:// or local interfaces
@pytest.fixture
def filezim(tmp_path):
    (tmp_path / "lib").mkdir(exist_ok=True)
    secret = tmp_path / "secret.png"
    secret.write_bytes(zimfactory.png(9, 9))
    return zimfactory.make_zim(tmp_path / "lib/f.zim", external_img=secret.as_uri()), secret.as_uri()


def test_e4_light_never_loads_file_urls(qapp, light, library, filezim):
    z, uri = filezim
    rid = register(library, z)
    assert light.open(rid)
    assert uri in light.blocked and not any("secret" in p for p in light.loaded_resources)


@needs_web
def test_e4_web_never_loads_file_urls_or_local_interfaces(qapp, web, library, filezim, trap):
    z, uri = filezim
    rid = register(library, z)
    load(qapp, web, lambda: web.open(rid))
    assert js(qapp, web, "document.getElementById('extimg').naturalWidth") == 0
    js(qapp, web, f"fetch('{uri}').catch(()=>0); fetch('http://[::1]:{trap.rsplit(':', 1)[1]}/v6').catch(()=>0); "
                  f"fetch('{trap.replace('127.0.0.1', 'localhost')}/name').catch(()=>0); 1")
    wait_until(qapp, lambda: len(web.blocked_requests) >= 3, 5)
    assert any(u.startswith("file:") for u in web.blocked_requests) and Trap.hits == []


def test_e4_light_markdown_and_css_cannot_reach_file_urls(qapp, light, library, tmp_path):
    secret = tmp_path / "s2.png"
    secret.write_bytes(zimfactory.png(7, 7))
    md = tmp_path / "lib/notes.md"
    md.write_text(f"# Notes\n\n![leak]({secret.as_uri()})\n\nText.\n")
    rid = register(library, md)
    assert light.open(rid)
    assert secret.as_uri() in light.blocked and "Text." in light.toPlainText()
    h, rep = sanitise(f'<style>p{{background:url("{secret.as_uri()}")}}</style><p style="background-image:'
                      f'url(file:///etc/x.png)">a</p><img src="img/ok.png"><link rel="stylesheet" '
                      f'href="file:///etc/a.css">'.encode(), "zim", 3, "A")
    assert "file:" not in h and 'src="zim://r3/img/ok.png"' in h and len(rep["blocked_resources"]) == 3
