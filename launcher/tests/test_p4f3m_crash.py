# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""launcher 0.3.7 / task-resources 0.2.4 — Medical reader crash repair.

RCA (reproduced on x86, see docs): an application-wide Python event filter (the launcher's idle tracking) made
PySide wrap a QWebEngineUrlRequestJob while its C++ constructor was still running -> SIGSEGV on the first
zim:// request of the embedded Medical WebEngine reader. These tests pin the fix and the crash guard."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtTest import QTest

from test_p4f3_medical import RES, lib_index, mwin  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CHILD_ROOT = Path(os.environ.get("TASK_TEST_LAUNCHER_ROOT", ROOT))   # lets the RCA run this against 0.3.6


def test_idle_filter_is_not_application_wide():
    src = (ROOT / "task_launcher/ui/main_window.py").read_text()
    code = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    assert not any("app.installEventFilter" in ln or "instance().installEventFilter" in ln for ln in code)
    assert "focusWindowChanged.connect(self._idle_filter.attach)" in src


def test_idle_filter_does_not_see_events_for_unrelated_objects(qtbot, mwin, monkeypatch):
    w, _ = mwin()
    seen = []
    monkeypatch.setattr(type(w), "note_input", lambda self: seen.append(1))
    o = QObject()
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QKeyEvent
    QCoreApplication.sendEvent(o, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
    assert seen == []


def test_idle_tracking_still_sees_window_input(qtbot, mwin, monkeypatch):
    w, _ = mwin()
    w.show()
    qtbot.waitExposed(w)
    assert w.windowHandle() in w._idle_filter.windows
    seen = []
    monkeypatch.setattr(type(w), "note_input", lambda self: seen.append(1))
    QTest.keyClick(w.windowHandle(), Qt.Key.Key_A)
    QTest.mouseClick(w.windowHandle(), Qt.MouseButton.LeftButton)
    assert len(seen) >= 2
    w.shutdown()
    assert w._idle_filter.windows == []


def test_other_top_level_windows_are_attached_when_focused(qtbot, mwin):
    from PySide6.QtWidgets import QWidget
    w, _ = mwin()
    d = QWidget()
    d.show()
    qtbot.waitExposed(d)
    w._idle_filter.attach(d.windowHandle())          # what focusWindowChanged does
    assert not w._idle_filter.attach(d.windowHandle())   # idempotent
    d.close()
    d.deleteLater()


def test_make_guard_uses_launcher_state_dir(isolated_home):
    from task_launcher import paths
    from task_launcher.services import resources_embed
    g = resources_embed.make_guard()
    assert g is not None and g.path == paths.state_dir() / "medical-webengine-guard.json"
    assert g.fp.startswith("task-launcher 0.3.7|task-resources 0.2.4|")


def test_make_guard_absent_with_older_resources(monkeypatch):
    import builtins
    from task_launcher.services import resources_embed
    real = builtins.__import__

    def imp(name, *a, **k):
        if name == "task_resources.viewer.guard":
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", imp)
    assert resources_embed.make_guard() is None


CHILD = r'''
import faulthandler, os, sys, time
faulthandler.enable()
sys.path[:0] = [sys.argv[1], sys.argv[2]]
os.environ["TASK_RESOURCES_PYPATH"] = sys.argv[2]
from task_launcher.services import resources_embed
resources_embed.prepare_before_qapplication()
from PySide6.QtWidgets import QApplication
app = QApplication(["task-launcher"])
from task_launcher.app import build
w, link, client = build(os.path.join(os.environ["HOME"], "nosock"))
w.resize(1100, 700); w.show(); app.processEvents()
def pump(cond, t=30):
    end = time.monotonic() + t
    while time.monotonic() < end:
        app.processEvents()
        if cond(): return True
        time.sleep(0.01)
    return cond()
for c in range(2):
    page = w.open_view("medical")
    r = page.browser.reader
    print("engine", r.engine, flush=True)
    if r.engine != "webengine":
        break
    r.view.loaded = None
    page.browser.open_resource(int(sys.argv[3]))
    print("loaded", pump(lambda: r.view.loaded is not None) and r.view.loaded[0], flush=True)
    print("guard_file", os.path.exists(sys.argv[4]), flush=True)
    w.go_home(); app.processEvents()
w.shutdown(); w.close(); app.processEvents()
print("DONE", flush=True)
'''


def test_embedded_webengine_load_inside_launcher_main_window(lib_index, isolated_home):
    """The reproduced crash: real launcher MainWindow (build()), Medical, WebEngine reader, zim:// load.
    Unpatched launcher 0.3.6: exit -11 (SIGSEGV) on the first load. Runs in a subprocess."""
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    ip, z, ids = lib_index
    from task_launcher import paths
    guard = paths.state_dir() / "medical-webengine-guard.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               # test harness only (container, root): the product never sets these
               QTWEBENGINE_DISABLE_SANDBOX="1", QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu")
    r = subprocess.run([sys.executable, "-c", CHILD, str(CHILD_ROOT), str(RES), str(ids["md"]), str(guard)],
                       env=env, capture_output=True, text=True, timeout=180)
    out = r.stdout
    if "engine webengine" not in out and r.returncode == 0:
        pytest.skip(f"WebEngine reader not available here: {out.splitlines()[:1]}")
    assert r.returncode == 0, (r.returncode, out, r.stderr[-3000:])
    assert out.count("loaded True") == 2 and "guard_file False" in out and "DONE" in out
    assert not guard.exists()


def test_known_crash_marker_makes_medical_use_light_reader_with_retry(mwin, lib_index, isolated_home, monkeypatch):
    from task_launcher import paths
    from task_resources.viewer.guard import fingerprint
    from test_p4f3_medical import open_medical
    from task_launcher import __version__
    g = paths.state_dir() / "medical-webengine-guard.json"
    g.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    g.write_text(json.dumps({"state": "armed", "pid": p.pid, "started": 1.0,
                             "fingerprint": fingerprint(f"task-launcher {__version__}")}))
    from task_launcher.services import resources_embed
    monkeypatch.setattr(resources_embed, "engine", lambda guard=None: "webengine")   # as on the Pi (auto)
    w, _ = mwin()
    page = open_medical(w)
    rp = page.browser.reader
    assert rp.engine == "lightweight" and not rp.guard_bar.isHidden()
    assert "Try enhanced reader" in rp.try_web_btn.text()
    assert json.loads(g.read_text())["state"] == "crashed"
    page.shutdown() if hasattr(page, "shutdown") else None
