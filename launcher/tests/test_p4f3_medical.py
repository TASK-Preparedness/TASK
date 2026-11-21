# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F.3 (launcher 0.3.5 + task-resources 0.2.2): Medical = embedded T.A.S.K. Resources browser/reader.

Acceptance A1–A12 use the REAL shipped manifests, Registry and MainWindow.activate(), the REAL task-resources
package from this tree (in-process), real synthetic ZIMs (libzim) and a real Resources index; only process
starts are recorded. Index and ZIM hashes are compared before/after.
"""

import hashlib
import os
import sys
from pathlib import Path

import pytest

RES = Path(__file__).resolve().parents[2] / "resources"
os.environ["TASK_RESOURCES_PYPATH"] = str(RES)
sys.path.append(str(RES / "tests"))
sys.path.append(str(RES))

from test_p4_ui import probe_result  # noqa: E402
from test_p4e_routing import RecordingProcs, _registry  # noqa: E402
from task_launcher.registry.discovery import BUNDLED_APPS_DIR  # noqa: E402
from task_launcher.registry.manifest import ManifestError, load_file  # noqa: E402
from task_launcher.registry.registry import Registry  # noqa: E402
from task_launcher.registry.tilestore import TileStore  # noqa: E402
from task_launcher.ui.medical_view import MedicalView  # noqa: E402

pytest.importorskip("libzim")
import zimfactory  # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def lib_index(isolated_home, tmp_path):
    """A real Resources index (written by task-resources itself, read-write) with medical + other ZIMs."""
    from task_resources import discovery, paths as rpaths
    from task_resources.library import Library
    from task_resources.settings import Settings
    d = tmp_path / "zims"
    d.mkdir()
    z = {"md": zimfactory.make_zim(d / "mdwiki_en_all.zim", title="MDWiki medical encyclopedia", name="mdwiki_en_all"),
         "mil": zimfactory.make_zim(d / "military.zim", title="Military Medicine", name="fas-military-medicine_en",
                                    fulltext=False),
         "ham": zimfactory.make_zim(d / "ham.zim", title="Amateur Radio Handbook", name="ham_radio")}
    ip = rpaths.data_dir() / "index.sqlite"
    lib = Library(Settings(), ip)
    ids = {}
    for k, p in z.items():
        rep = discovery.Report()
        ids[k] = discovery.register(lib.index, p, "import", rep)
    lib.index.set_categories(ids["ham"], ["Radio"])
    lib.index.close()
    return ip, z, ids


@pytest.fixture
def mwin(launcher, safe_dir):
    def make(name="m", present=("task-resources",)):
        d = safe_dir / name
        d.mkdir(parents=True, exist_ok=True)
        reg, _ = _registry(d, set(present))
        procs = RecordingProcs()
        w = launcher(start=False, scan=False, registry=reg, procs=procs)
        w._on_probes(probe_result())
        return w, procs
    return make


def open_medical(w):
    return w.activate(w.registry.get("app:task.medical"))


def texts(lw):
    return [lw.item(i).text() for i in range(lw.count())]


def test_a01_tile_visible_and_manifest_has_no_exec(mwin, tmp_path):
    w, _ = mwin()
    t = w.registry.get("app:task.medical")
    assert t is not None and t.builtin == "medical" and t in w.registry.visible()
    text = (BUNDLED_APPS_DIR / "070-medical.toml").read_text()
    assert "exec" not in text.split("[launch]", 1)[1].split("[", 1)[0]
    bad = tmp_path / "070-medical.toml"
    bad.write_text(text.replace('builtin = "medical"', 'builtin = "medical"\nexec = ["/usr/bin/task-resources"]'))
    with pytest.raises(ManifestError, match="does not take 'exec'"):
        load_file(bad, "package")


def test_a02_opens_embedded_in_launcher_window_no_process(mwin, lib_index):
    w, procs = mwin()
    page = open_medical(w)
    assert isinstance(page, MedicalView) and w.views.currentWidget() is page and page.window() is w
    assert page.browser is not None and page.browser.library.read_only
    assert procs.started == [] and "medical" not in w.native_windows


def test_a03_filtered_to_medical_by_default_with_unfiltered_option(mwin, lib_index):
    w, _ = mwin()
    b = open_medical(w).browser
    items = " | ".join(texts(b.items))
    assert "MDWiki" in items and "Military Medicine" in items and "Amateur" not in items
    from task_resources.ui.browser import EVERYTHING
    keys = [b.cats.item(i).data(0x0100) for i in range(b.cats.count())]
    b.cats.setCurrentRow(keys.index(EVERYTHING))
    assert "Amateur" in " | ".join(texts(b.items))


def test_a04_metadata_shown_with_reason(mwin, lib_index):
    w, _ = mwin()
    b = open_medical(w).browser
    b.items.setCurrentRow(0)
    t = b.details.toPlainText()
    assert "Kind" in t and "ZIM" in t and "Listed because" in t and "Search" in t


def test_a05_search_metadata_and_full_text(mwin, lib_index):
    w, _ = mwin()
    b = open_medical(w).browser
    b.find.setText("military")
    assert texts(b.items) and all("Military" in x for x in texts(b.items))
    b.find.setText("altitude")
    b.contents.setChecked(True)
    b.search_contents(wait=True)
    hits = texts(b.items)
    assert any("in MDWiki" in h and "full-text" in h for h in hits)
    assert not any("Amateur" in h for h in hits)


def test_a06_zim_reads_inside_the_medical_view(mwin, lib_index):
    w, procs = mwin()
    page = open_medical(w)
    b = page.browser
    b.items.setCurrentRow([i for i, x in enumerate(texts(b.items)) if "MDWiki" in x][0])
    assert b.open_current() and b.view.nav.current.path == "Home"
    assert b.stack.currentWidget() is b.reader and b.view.window() is w and procs.started == []
    assert "Field Manual Home" in b.view.toPlainText() or b.view.last_title


def test_a07_navigation_and_bookmarks_persist_outside_the_index(mwin, lib_index, isolated_home):
    ip, z, ids = lib_index
    w, _ = mwin()
    b = open_medical(w).browser
    assert b.open_resource(ids["md"])
    assert b.view.open(ids["md"], "Boiling_water")
    assert b.view_back() and b.view.nav.current.path == "Home" and b.view_forward()
    assert b.bookmark()
    from task_launcher import paths
    f = paths.state_dir() / "medical-bookmarks.json"
    assert f.is_file() and oct(f.stat().st_mode & 0o777) == "0o600" and "Boiling_water" in f.read_text()
    b.inside.setText("altitude")
    assert b.search_inside().mode == "full-text"


def test_a08_back_home_refresh(mwin, lib_index):
    w, _ = mwin()
    page = open_medical(w)
    page.refresh_btn.click()
    assert page.browser.items.count() == 2
    page.back_btn.click()
    assert w.views.currentWidget() is w.home
    open_medical(w)
    page.home_btn.click()
    assert w.views.currentWidget() is w.home and w.view_history == []


def test_a09_lock_hides_content(mwin, lib_index):
    ip, z, ids = lib_index
    w, _ = mwin()
    b = open_medical(w).browser
    assert b.open_resource(ids["md"])
    b.inside.setText("altitude")
    b.search_inside()
    w._lock_changed(True)
    assert w.views.currentWidget() is w.home and w.overlay.isVisibleTo(w)
    assert b.stack.currentIndex() == 0 and b.hits.count() == 0 and b.details.toPlainText() == ""
    assert "altitude" not in b.view.toPlainText().lower()


def test_a10_one_reader_instance_on_reopen(mwin, lib_index):
    w, procs = mwin()
    a = open_medical(w)
    reader, view = a.browser.reader, a.browser.view
    for _ in range(4):
        w.go_home()
        assert open_medical(w) is a
    assert a.browser.reader is reader and a.browser.view is view and len(a.browser.reader._viewers) == 1
    assert w.views.count() == 2 and procs.started == []


def test_a11_useful_errors_missing_corrupt_zim_and_no_index(mwin, lib_index, isolated_home):
    ip, z, ids = lib_index
    w, _ = mwin()
    b = open_medical(w).browser
    z["mil"].write_bytes(z["mil"].read_bytes()[:300])
    assert not b.open_resource(ids["mil"]) and "could not be read" in b.mode.text()
    z["md"].unlink()
    assert not b.open_resource(ids["md"]) and "File missing" in b.mode.text()


def test_a11b_no_index_and_no_resources_messages(mwin, monkeypatch):
    from task_launcher.services import resources_embed
    w, _ = mwin()
    page = open_medical(w)
    assert page.browser is None and "no index yet" in page.error
    def gone():
        raise resources_embed.EmbedUnavailable("T.A.S.K. Resources is not installed")
    p2 = MedicalView(w, loader=gone)
    assert "not installed" in p2.error and p2.browser is None


def test_a12_db_and_zim_hashes_unchanged_and_standalone_apps_route(mwin, lib_index):
    ip, z, ids = lib_index
    before = sha(ip), {k: sha(p) for k, p in z.items()}
    w, procs = mwin()
    page = open_medical(w)
    b = page.browser
    b.open_resource(ids["md"])
    b.view.open(ids["md"], "Boiling_water")
    b.bookmark()
    b.contents.setChecked(True)
    b.find.setText("water")
    b.search_contents(wait=True)
    page.refresh()
    page.shutdown()
    wal = Path(str(ip) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    assert (sha(ip), {k: sha(p) for k, p in z.items()}) == before
    w.activate(w.registry.get("app:task.library"))                  # standalone Resources/Library unchanged
    assert procs.started and procs.started[-1][1][0].endswith("task-resources")
    ids12 = sorted(t.key for t in w.registry.visible() if t.key.startswith("app:task."))
    assert len(ids12) == 12


def test_a12b_survives_reboot(mwin, safe_dir, launcher, lib_index):
    w, _ = mwin("r")
    open_medical(w)
    reg2 = Registry(manifest_dirs=[(safe_dir / "r" / "apps", "package")], desktop_dirs=[],
                    store=TileStore(safe_dir / "r" / "tiles.json"))
    reg2.build()
    w2 = launcher(start=False, scan=False, registry=reg2, procs=RecordingProcs())
    assert w2.views.currentWidget() is w2.home
    page = w2.activate(reg2.get("app:task.medical"))
    assert isinstance(page, MedicalView) and page.browser is not None


def test_a12c_routing_of_other_builtins_unchanged(mwin):
    w, _ = mwin(present=("task-resources", "task-aprs"))
    calls = []
    w.open_builtin = lambda n: calls.append(n) or n
    for k in ("app:task.system", "app:task.app-manager", "app:task.weather", "app:task.medical"):
        w.activate(w.registry.get(k))
    assert calls == ["system", "app-manager", "weather"]
