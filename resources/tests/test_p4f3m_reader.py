# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-resources 0.2.4: WebEngine crash guard + lightweight-reader images/tables (MDWiki-like synthetic ZIM)."""

import hashlib
import json
import subprocess
import sys

import pytest

import zimfactory
from conftest import register, wait_until
from libzim.writer import Creator, Hint

from task_resources.viewer import guard as G
from task_resources.viewer import urls


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def crashed_marker(path, fp):
    path.write_text(json.dumps({"state": "armed", "pid": dead_pid(), "fingerprint": fp, "started": 1.0,
                                "url": "zim://x/A/Brain"}))


# ---------------------------------------------------------------- guard unit
def test_guard_arm_disarm_and_crash_detection(tmp_path):
    p = tmp_path / "s/guard.json"
    g = G.CrashGuard(p, fp="F1")
    assert not g.known_crash() and not p.exists()
    g.arm("zim://r/A")
    rec = json.loads(p.read_text())
    assert rec["state"] == "armed" and rec["fingerprint"] == "F1" and (p.stat().st_mode & 0o777) == 0o600
    g.arm("zim://r/B")                                   # only the first arm writes
    assert json.loads(p.read_text())["url"] == "zim://r/A"
    g.disarm()
    assert not p.exists()


def test_stale_marker_from_dead_process_is_a_known_crash_only_for_same_fingerprint(tmp_path):
    p = tmp_path / "guard.json"
    crashed_marker(p, "F1")
    g = G.CrashGuard(p, fp="F1")
    assert g.known_crash() and json.loads(p.read_text())["state"] == "crashed"
    assert "stopped the application" in g.describe()
    assert G.CrashGuard(p, fp="F1").known_crash()           # persists across starts (never auto-retried)
    assert not G.CrashGuard(p, fp="F2-upgraded").known_crash()


def test_marker_of_a_live_other_process_is_not_a_crash(tmp_path):
    import os
    p = tmp_path / "guard.json"
    p.write_text(json.dumps({"state": "armed", "pid": os.getppid(), "fingerprint": "F1"}))
    assert not G.CrashGuard(p, fp="F1").known_crash()


def test_clean_release_before_success(tmp_path):
    p = tmp_path / "guard.json"
    g = G.CrashGuard(p, fp="F1")
    g.arm()
    g.release()
    assert not p.exists()
    crashed_marker(p, "F1")
    g = G.CrashGuard(p, fp="F1")
    g.arm()                     # manual retry after a known crash, closed before any success
    g.release()
    assert G.CrashGuard(p, fp="F1").known_crash()
    g = G.CrashGuard(p, fp="F1")
    g.arm()
    g.disarm()                  # retry that succeeded clears the record
    assert not G.CrashGuard(p, fp="F1").known_crash()


def test_guard_io_errors_never_raise(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        g = G.CrashGuard(ro / "sub/guard.json", fp="F")
        g.arm()
        g.disarm()
        g.release()
        assert g.error
    finally:
        ro.chmod(0o700)


def test_choose_guarded(tmp_path, monkeypatch):
    from task_resources import viewer
    monkeypatch.setattr(viewer, "choose", lambda s: ("webengine", ""))
    p = tmp_path / "guard.json"
    assert viewer.choose_guarded("auto", None) == ("webengine", "")
    assert viewer.choose_guarded("auto", G.CrashGuard(p, fp="F"))[0] == "webengine"
    crashed_marker(p, "F")
    eng, note = viewer.choose_guarded("auto", G.CrashGuard(p, fp="F"))
    assert eng == "lightweight" and "Try enhanced reader" in note


def test_fingerprint_contains_versions():
    fp = G.fingerprint("host-x 1")
    assert fp.startswith("host-x 1|task-resources 0.2.4|Qt ") and "PySide6" in fp


# ---------------------------------------------------------------- MDWiki-like archive
ART = """<html><head><title>Brain tumor</title></head><body><h1>Brain tumor</h1>
<table class="infobox"><tr><th colspan="2">Brain tumor</th></tr>
<tr><td colspan="2"><img id="ib" src="../I/Scan_%28axial%29_%C3%A9.png" alt="MRI scan"></td></tr>
<tr><td>Specialty</td><td>Neurology</td></tr></table>
<p>Text.</p><img id="wide" src="../I/wide.png" alt="wide figure">
<img id="webp" src="../I/fig.jpg.webp" alt="Diagram">
<img id="gone" src="../I/nothere.png" alt="Missing figure">
<table class="wikitable"><tr><th>Type</th><th>Rate</th></tr><tr><td>Glioma</td><td>30%</td></tr></table>
<p><a id="g" href="Glioma%20tumor">Glioma</a></p></body></html>"""


def make_md(path):
    c = Creator(str(path))
    with c:
        c.set_mainpath("A/Brain_tumor")
        for k, v in {"Title": "mdwiki syn", "Language": "eng", "Name": "mdwiki_syn", "Creator": "tests",
                     "Publisher": "tests", "Date": "2026-10-15", "Description": "x"}.items():
            c.add_metadata(k, v)
        it = zimfactory._Item
        c.add_item(it("A/Brain_tumor", "Brain tumor", "text/html", ART))
        c.add_item(it("A/Glioma tumor", "Glioma", "text/html", "<html><body><h1>Glioma</h1></body></html>"))
        c.add_item(it("I/Scan_(axial)_é.png", "", "image/png", zimfactory.png(40, 30), front=False))
        c.add_item(it("I/wide.png", "", "image/png", zimfactory.png(3000, 10), front=False))
        c.add_item(it("I/fig.jpg.webp", "", "image/webp", b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x00" * 24,
                      front=False))
    return path


@pytest.fixture
def md(tmp_path):
    (tmp_path / "lib").mkdir(exist_ok=True)
    return make_md(tmp_path / "lib/mdwiki_syn.zim")


def test_sanitiser_decodes_before_join_and_marks_tables():
    from task_resources.viewer.sanitize import sanitise
    html, rep = sanitise(ART, "zim", 7, "A/Brain_tumor")
    want = urls.make("zim", 7, "I/Scan_(axial)_é.png")
    assert f'src="{want}"' in html.replace("&amp;", "&")
    assert urls.parse(want)[2] == "I/Scan_(axial)_é.png"
    assert rep["img_alt"][want] == "MRI scan"
    assert 'class="infobox" border="1" cellspacing="0" cellpadding="4" align="right"' in html
    assert 'class="wikitable" border="1"' in html and 'width="100%"' in html
    assert urls.parse(urls.make("zim", 7, "A/Glioma tumor"))[2] == "A/Glioma tumor"


def test_archive_lookup_accepts_encoded_path(md, library):
    rid = register(library, md)
    src = library.source(rid)
    assert src.get("I/Scan_%28axial%29_%C3%A9.png").data[:4] == b"\x89PNG"


def light_open(qapp, library, md):
    from task_resources.viewer.light import LightViewer
    v = LightViewer(library)
    v.resize(900, 700)
    v.show()
    rid = register(library, md)
    assert v.open(rid)
    for _ in range(5):
        qapp.processEvents()
    return v, rid


def test_light_images_placeholders_scaling_and_cache(qapp, library, md, monkeypatch):
    from task_resources.viewer.light import LightViewer
    calls = []
    v, rid = light_open(qapp, library, md)
    src = library.source(rid)
    real = type(src).get
    monkeypatch.setattr(type(src), "get", lambda self, p, *a, **k: (calls.append(p), real(self, p, *a, **k))[1])
    assert "I/Scan_(axial)_é.png" in v.loaded_resources            # encoded name now resolves
    reasons = dict(v.placeholders)
    assert reasons["I/nothere.png"] == "not in this file"
    assert "I/fig.jpg.webp" in reasons                             # fake webp: placeholder, never a broken box
    from PySide6.QtGui import QTextDocument
    rt = QTextDocument.ResourceType.ImageResource
    from PySide6.QtCore import QUrl
    wide = v.loadResource(rt, QUrl(urls.make("zim", rid, "I/wide.png")))
    assert wide.width() <= v.viewport().width() and wide.height() >= 1
    gone = QUrl(urls.make("zim", rid, "I/nothere.png"))
    before = len(calls)
    for _ in range(5):
        assert not v.loadResource(rt, gone).isNull()
    assert len(calls) == before                                    # failure cache: no repeated libzim reads
    v.close()
    assert LightViewer  # noqa


def test_light_unsupported_format_hint(qapp, library, md, monkeypatch):
    from task_resources.viewer import light
    monkeypatch.setattr(light, "supported_formats", lambda: {"png", "jpeg", "gif", "bmp"})
    v, _ = light_open(qapp, library, md)
    assert "webp" in v.unsupported_formats
    assert any("qt6-image-formats-plugins" in r for _, r in v.placeholders)
    v.close()


def test_sniff_format():
    from task_resources.viewer.light import sniff_format
    assert sniff_format(b"RIFF\0\0\0\0WEBPVP8 ", "x.jpg") == "webp"
    assert sniff_format(zimfactory.png(), "x.webp") == "png"
    assert sniff_format(b"<?xml version='1.0'?><svg xmlns='x'/>") == "svg"
    assert sniff_format(b"\xff\xd8\xff\xe0", "") == "jpeg"


# ---------------------------------------------------------------- reader pane fallback
def test_reader_pane_guarded_fallback_and_manual_retry(qapp, library, md, tmp_path, monkeypatch):
    from task_resources import viewer
    from task_resources.ui.browser import ResourceBrowser
    ok, _ = viewer.webengine_available()
    gp = tmp_path / "state/guard.json"
    gp.parent.mkdir()
    fp = G.fingerprint("t")
    crashed_marker(gp, fp)
    g = G.CrashGuard(gp, fp=fp)
    zh = hashlib.sha256(md.read_bytes()).hexdigest()
    b = ResourceBrowser(library, "webengine", guard=g)
    b.show()
    rp = b.reader
    assert rp.engine == "lightweight" and not rp.guard_bar.isHidden() and "not retried" in rp.guard_label.text()
    rid = register(library, md)
    assert b.open_resource(rid)
    assert rp.view.name == "lightweight"
    if not ok:
        pytest.skip("WebEngine unavailable here")
    assert rp.try_enhanced()
    assert rp.view.name == "webengine" and not not rp.guard_bar.isHidden()
    assert wait_until(qapp, lambda: rp.view.loaded and rp.view.loaded[0], 30)
    assert not gp.exists() and not G.CrashGuard(gp, fp=fp).known_crash()   # success cleared the record
    b.reader.shutdown() if hasattr(b.reader, "shutdown") else None
    b.close()
    b.deleteLater()
    qapp.processEvents()
    assert hashlib.sha256(md.read_bytes()).hexdigest() == zh                 # ZIM untouched


def test_web_viewer_arms_before_first_load_and_clears_after(qapp, library, md, tmp_path):
    from task_resources import viewer
    if not viewer.webengine_available()[0]:
        pytest.skip("WebEngine unavailable here")
    from task_resources.viewer.web import WebViewer
    gp = tmp_path / "g.json"
    g = G.CrashGuard(gp, fp="F")
    armed = []
    orig = g.arm
    g.arm = lambda url="": (armed.append((url, gp.exists())), orig(url), armed.append(gp.exists()))
    v = WebViewer(library, guard=g)
    v.show()
    rid = register(library, md)
    v.open(rid)
    assert armed and armed[-1] is True                      # marker written before setUrl
    assert wait_until(qapp, lambda: v.loaded and v.loaded[0], 30)
    assert not gp.exists()
    v.open(rid, "A/Glioma tumor")
    assert wait_until(qapp, lambda: v.loaded and "Glioma" in v.loaded[2], 30)
    assert len(armed) == 2                                  # no re-arm after the first success
    v.close()
    v.deleteLater()
    qapp.processEvents()
