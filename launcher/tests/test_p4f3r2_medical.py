# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F.3 r2 (launcher 0.3.6 + task-resources 0.2.3): Medical index access creates nothing next to the
index, survives repeated open/close/lock/reopen, runs alongside a Resources writer, leaks no DB connection,
snapshot or QtWebEngine process (also on failure), and leaves DB/ZIM hashes unchanged."""

import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from test_p4f3_medical import RES, lib_index, mwin, open_medical, sha, texts  # noqa: F401,E402

pytest.importorskip("libzim")
import zimfactory  # noqa: E402


def listing(d):
    return sorted((p.name, sha(p)) for p in Path(d).iterdir() if p.is_file())


def snapdirs():
    from task_resources import rosnap
    return list(Path(rosnap._tmp_root()).glob(rosnap.PREFIX + "*"))


def open_conns_to(path):
    """Open file descriptors of THIS process pointing at the index or its side files."""
    n = 0
    for fd in os.listdir("/proc/self/fd"):
        try:
            t = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if t.startswith(str(path)):
            n += 1
    return n


def _touch_index(ip):
    from task_resources.index import Index
    w = Index(ip)
    with w.db:
        w.db.execute("INSERT OR REPLACE INTO meta VALUES('touched', ?)", (uuid.uuid4().hex,))
    w.close()


def test_b01_repeated_open_close_lock_reopen(mwin, lib_index):
    ip, z, ids = lib_index
    before = listing(ip.parent), {k: sha(p) for k, p in z.items()}
    w, procs = mwin()
    for i in range(10):
        page = open_medical(w)
        b = page.browser
        assert b is not None and page.library.index.ro_mode == "snapshot"
        assert b.open_resource(ids["md"])
        w._lock_changed(True)
        assert b.hits.count() == 0 and b.stack.currentIndex() == 0
        w._lock_changed(False)
        page.refresh()                                          # unchanged index: same browser/reader kept
        assert page.browser is b and len(snapdirs()) == 1
        if i % 3 == 2:                                          # Resources changed the index meanwhile
            _touch_index(ip)
            page.refresh()                                      # stale snapshot -> renewed, one reader again
            assert page.browser is not b and len(snapdirs()) == 1
            before = listing(ip.parent), before[1]
        assert texts(page.browser.items) and listing(ip.parent) == before[0]
        w.go_home()
    page.shutdown()
    page.shutdown()                                             # idempotent
    assert snapdirs() == [] and open_conns_to(ip) == 0 and page.browser is None
    assert (listing(ip.parent), {k: sha(p) for k, p in z.items()}) == before and procs.started == []


def test_b02_medical_and_resources_writer_at_the_same_time(mwin, lib_index, tmp_path):
    from task_resources import discovery
    from task_resources.library import Library
    from task_resources.settings import Settings
    ip, z, ids = lib_index
    writer = Library(Settings(), ip)                            # T.A.S.K. Resources running (read-write)
    names_with_writer = sorted(p.name for p in ip.parent.iterdir())
    w, _ = mwin()
    page = open_medical(w)
    assert page.library.index.ro_mode == "live"
    n0 = page.browser.items.count()
    (tmp_path / "zims2").mkdir()
    new = zimfactory.make_zim(tmp_path / "zims2" / "wikem.zim", title="WikEM emergency medicine", name="wikem_en")
    discovery.register(writer.index, new, "import", discovery.Report())   # writer commits while Medical is open
    page.refresh()
    assert page.browser.items.count() == n0 + 1 and any("WikEM" in t for t in texts(page.browser.items))
    assert sorted(p.name for p in ip.parent.iterdir()) == names_with_writer     # Medical created nothing
    with writer.index.db:                                       # writer is never blocked by the reader
        writer.index.db.execute("INSERT INTO meta VALUES('probe','1')")
    writer.close()
    writer.index.close()
    # Medical held the last connection when the writer closed, so SQLite could not remove Resources' own
    # -wal/-shm (only the last READ-WRITE close can). They are Resources' files, kept, never deleted by us.
    page.refresh()
    assert page.browser.items.count() == n0 + 1
    after_writer = sorted(p.name for p in ip.parent.iterdir())
    assert set(after_writer) <= set(names_with_writer)
    page.shutdown()
    assert sorted(p.name for p in ip.parent.iterdir()) == after_writer and snapdirs() == []
    assert open_conns_to(ip) == 0
    w2 = Library(Settings(), ip)                                # next Resources start/stop cleans up as usual
    w2.close()
    w2.index.close()
    assert sorted(p.name for p in ip.parent.iterdir()) == ["index.sqlite"]


def test_b03_failures_leak_no_connection_snapshot_or_reader(mwin, lib_index, monkeypatch):
    ip, z, ids = lib_index
    w, _ = mwin()
    from task_resources.ui import browser as rb

    class Boom(Exception):
        pass

    real = rb.ResourceBrowser
    fail = {"on": True}

    def broken(*a, **k):
        if fail["on"]:
            raise Boom("simulated reader failure")
        return real(*a, **k)
    monkeypatch.setattr(rb, "ResourceBrowser", broken)
    page = open_medical(w)
    assert page.browser is None and page.library is None and "could not start" in page.error
    assert snapdirs() == [] and open_conns_to(ip) == 0
    fail["on"] = False
    good = ip.read_bytes()
    ip.write_bytes(b"garbage" * 1000)
    page.refresh()
    assert page.browser is None and "could not be read" in page.error
    assert snapdirs() == [] and open_conns_to(ip) == 0
    ip.write_bytes(good)
    page.refresh()
    assert page.browser is not None and page.library.index.ro_mode == "snapshot"
    page.shutdown()
    assert snapdirs() == [] and open_conns_to(ip) == 0


CHILD = r'''
import os, sys, time
sys.path[:0] = [sys.argv[1], sys.argv[2]]
os.environ["TASK_RESOURCES_PYPATH"] = sys.argv[2]
from task_launcher.services import resources_embed
mode = resources_embed.prepare_before_qapplication()
from PySide6.QtWidgets import QApplication
app = QApplication([])
from task_launcher.ui.medical_view import MedicalView
class Home:
    def show_notice(self, *a): pass
class MW:
    home = Home()
    def go_back(self): pass
    def go_home(self): pass
v = MedicalView(MW(), index_path=sys.argv[3])
print("engine", resources_embed.engine(), mode, flush=True)
b = v.browser
ok = b.open_resource(int(sys.argv[4]))
end = time.time() + 8
while time.time() < end:
    app.processEvents(); time.sleep(0.02)
def children():
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                st = open(f"/proc/{p}/stat").read().split()
                name = open(f"/proc/{p}/comm").read().strip()
            except OSError:
                continue
            if "QtWebEngine" in name:
                out.append(p)
    return out
print("opened", ok, "webengine_procs", len(children()), flush=True)
v.shutdown()
end = time.time() + 3
while time.time() < end:
    app.processEvents(); time.sleep(0.02)
print("after_shutdown", len(children()), flush=True)
'''


def marked_processes(mark):
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            env = Path(f"/proc/{p}/environ").read_bytes()
        except OSError:
            continue
        if mark.encode() in env:
            out.append(p)
    return out


def test_b04_no_orphaned_qtwebengine_processes(lib_index, tmp_path):
    ip, z, ids = lib_index
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    mark = f"TASK_TEST_MARK={uuid.uuid4().hex}"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_DISABLE_SANDBOX="1",
               QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu", **dict([mark.split("=", 1)]))
    src = str(Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", CHILD, src, str(RES), str(ip), str(ids["md"])], env=env,
                       capture_output=True, text=True, timeout=120)
    out = r.stdout
    assert r.returncode == 0, r.stderr[-2000:]
    if "engine webengine" not in out:
        pytest.skip(f"WebEngine reader not available here: {out.splitlines()[:1]}")
    assert "opened True" in out
    import time
    deadline = time.time() + 10
    while marked_processes(mark) and time.time() < deadline:
        time.sleep(0.2)
    assert marked_processes(mark) == [], "QtWebEngine helper processes outlived the launcher process"
    assert snapdirs() == []
