# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4E (launcher 0.3.2): tile routing through the REAL shipped manifests and MainWindow.activate().

Root cause of the 0.3.1 bug: test_l4d only asserted the Registry result (t.argv set). It never called
MainWindow.activate(), where `builtin in NATIVE_WINDOWS` won unless builtin == "radio". These tests use
the shipped apps.d manifests + real Registry + real activate(), with only the process start recorded.
"""

import pytest

from conftest import make_exec
from task_launcher.registry.discovery import BUNDLED_APPS_DIR
from task_launcher.registry.registry import Registry
from task_launcher.registry.tilestore import TileStore


class RecordingProcs:
    def __init__(self):
        self.listeners, self.started = [], []

    def start(self, key, argv, **kw):
        self.started.append((key, list(argv)))
        return None

    def running(self, *a, **k):
        return False

    def poll(self):
        pass

    def shutdown(self):
        pass


def _registry(tmp_path, present):
    """All shipped manifests; each /usr/bin/X in `present` is replaced by a real executable stub."""
    d = tmp_path / "apps"
    d.mkdir()
    bindir = tmp_path / "bin"
    for src in BUNDLED_APPS_DIR.glob("*.toml"):
        text = src.read_text()
        for name in present:
            text = text.replace(f'"/usr/bin/{name}"', f'"{make_exec(bindir, name)}"')
        for name in ("task-resources", "task-aprs", "task-console"):   # absent ones must not resolve to host
            if name not in present:
                text = text.replace(f'"/usr/bin/{name}"', f'"{tmp_path}/missing/{name}"')
        (d / src.name).write_text(text)
    reg = Registry(manifest_dirs=[(d, "package")], desktop_dirs=[], store=TileStore(tmp_path / "tiles.json"))
    reg.build()
    return reg, bindir


@pytest.fixture
def win(launcher, safe_dir):
    def make(tmp_path, present):
        tmp_path = safe_dir / tmp_path.name if tmp_path.name != "b" else safe_dir / "b"
        tmp_path.mkdir(parents=True, exist_ok=True)
        reg, bindir = _registry(tmp_path, present)
        procs = RecordingProcs()
        w = launcher(start=False, scan=False, registry=reg, procs=procs)
        w.open_builtin = lambda name: procs.started.append(("builtin", name)) or name
        return w, procs, bindir
    return make


def test_e01_library_opens_task_resources_when_installed(tmp_path, win):
    w, procs, bindir = win(tmp_path, {"task-resources"})
    w.activate(w.registry.get("app:task.library"))
    assert procs.started == [("app:task.library", [str(bindir / "task-resources")])]


def test_e02_library_falls_back_to_builtin_viewer_when_absent(tmp_path, win):
    w, procs, _ = win(tmp_path, set())
    w.activate(w.registry.get("app:task.library"))
    assert procs.started == [("builtin", "library")]


def test_e03_radio_routing_unchanged(tmp_path, win):
    w, procs, bindir = win(tmp_path, {"task-aprs"})
    w.activate(w.registry.get("app:task.radio"))
    assert procs.started == [("app:task.radio", [str(bindir / "task-aprs")])]
    w2, procs2, _ = win(tmp_path / "b", set())
    w2.activate(w2.registry.get("app:task.radio"))
    assert procs2.started == [("builtin", "radio")]


@pytest.mark.parametrize("tile,builtin", [("app:task.system", "system"), ("app:task.app-manager", "app-manager"),
                                          ("app:task.weather", "weather")])
# app:task.medical: Phase 4F.2 opens the in-window native view instead — see test_p4f2_medical.py
def test_e04_other_builtins_unchanged(tmp_path, win, tile, builtin):
    w, procs, _ = win(tmp_path, {"task-resources", "task-aprs"})
    w.activate(w.registry.get(tile))
    assert procs.started == [("builtin", builtin)]


def test_e05_shipped_library_manifest_preserved():
    text = (BUNDLED_APPS_DIR / "050-library.toml").read_text()
    assert 'builtin = "library"' in text and 'exec = ["/usr/bin/task-resources"]' in text


# ---- Phase 4E: the Pi's desktop is X11 LightDM/LXDE (not labwc); both must work.
@pytest.mark.parametrize("env,desktops", [({"XDG_CURRENT_DESKTOP": "LXDE"}, ["LXDE"]),
                                          ({"XDG_CURRENT_DESKTOP": "labwc:wlroots"}, ["labwc", "wlroots"])])
def test_e06_desktop_visibility_on_lxde_and_labwc(tmp_path, env, desktops):
    from task_launcher.registry import desktop as D
    assert D.current_desktops(env) == desktops
    (tmp_path / "lx.desktop").write_text("[Desktop Entry]\nType=Application\nName=LX\nExec=true\nOnlyShowIn=LXDE;\n")
    (tmp_path / "any.desktop").write_text("[Desktop Entry]\nType=Application\nName=Any\nExec=true\n")
    found = D.scan([tmp_path], langs=[])
    assert D.visibility_problem(found["any.desktop"], desktops) == ""
    assert (D.visibility_problem(found["lx.desktop"], desktops) == "") == (desktops == ["LXDE"])
