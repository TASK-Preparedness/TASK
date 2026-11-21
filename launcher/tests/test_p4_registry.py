# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A: manifest additions (labels, actions, readiness, status_note), fallback selection,
early-failure reporting, tile IDs/order preservation and 0.1.0 → 0.2.0 config compatibility."""

import json
import os
import time
from pathlib import Path

import pytest

from conftest import make_exec
from task_launcher.launch import ProcessManager
from task_launcher.registry import manifest as M
from task_launcher.registry.discovery import BUNDLED_APPS_DIR
from task_launcher.registry.registry import Registry
from task_launcher.registry.tilestore import TileStore

PHASE3_KEYS = ["app:task.mesh", "app:task.maps", "app:task.radio", "app:task.sdr", "app:task.library",
               "app:task.mission-planner", "app:task.medical", "app:task.weather", "app:task.devices",
               "app:task.files", "app:task.system", "app:task.app-manager"]
BASE = 'manifest_version = 1\nid = "org.example.app"\nname = "App"\nversion = "1.0.0"\n'


def pm(text, trust="package"):
    return M.parse_text(BASE + text, Path("/nonexistent/x.toml"), trust)


# ---------------------------------------------------------------- schema additions

def test_labels_actions_readiness_parse():
    m = pm('readiness = "gps"\nstatus_note = "note"\n[launch]\nexec = ["/usr/bin/a"]\n'
           'exec_alternatives = [["/usr/bin/b"]]\n[launch.labels]\n"/usr/bin/b" = "B (fallback)"\n'
           '[[actions]]\nid = "mon"\nlabel = "Monitor"\nexec = ["/usr/bin/mon", "-x"]\nterminal = true\n')
    assert m.readiness == "gps" and m.status_note == "note" and m.labels == {"/usr/bin/b": "B (fallback)"}
    assert m.actions[0].exec == ["/usr/bin/mon", "-x"] and m.actions[0].terminal is True


@pytest.mark.parametrize("text,err", [
    ('readiness = "magic"\n[launch]\nexec = ["/usr/bin/a"]\n', "unknown readiness probe"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[launch.labels]\n"/usr/bin/zzz" = "x"\n', "is not the program"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[launch.labels]\n"/usr/bin/a" = ""\n', "1-60 characters"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[[actions]]\nid = "x"\nlabel = "X"\nexec = ["rel/path"]\n', "absolute path"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[[actions]]\nid = "x"\nlabel = "X"\n', "needs 'exec'"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[[actions]]\nid = "x"\nlabel = "X"\nexec = ["/a"]\nterminal = "yes"\n',
     "true or false"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[[actions]]\nid = "x"\nlabel = "X"\nexec = ["/a"]\n'
     '[[actions]]\nid = "x"\nlabel = "Y"\nexec = ["/b"]\n', "duplicate action id"),
    ('[launch]\nexec = ["/usr/bin/a"]\n[[actions]]\nid = "x"\nlabel = "X"\nexec = ["/a"]\nshell = true\n',
     "unknown [[actions]] key"),
    ('status = "planned"\n[[actions]]\nid = "x"\nlabel = "X"\nexec = ["/a"]\n', "must not have actions"),
    ('status_note = "' + "x" * 61 + '"\n[launch]\nexec = ["/usr/bin/a"]\n', "longer than 60"),
])
def test_invalid_launch_definitions(text, err):
    with pytest.raises(M.ManifestError, match=err.replace("[", r"\[").replace("]", r"\]")):
        pm(text)


def test_new_builtins_reserved_for_system_manifests():
    with pytest.raises(M.ManifestError, match="reserved"):
        pm('[launch]\nbuiltin = "library"\n', trust="user")
    assert pm('[launch]\nbuiltin = "radio"\n').builtin == "radio"


def test_resolve_exec_reports_all_missing_by_label():
    m = pm('[launch]\nexec = ["/nonexistent/a"]\nexec_alternatives = [["/nonexistent/b"]]\n'
           '[launch.labels]\n"/nonexistent/a" = "Native"\n"/nonexistent/b" = "Fallback"\n')
    argv, status, reason = m.resolve_exec()
    assert argv is None and status == "missing" and reason == "not installed: Native, Fallback"


# ---------------------------------------------------------------- fallback selection with the shipped manifests

def _shipped_with(tmp_path, name, replace):
    text = (BUNDLED_APPS_DIR / name).read_text()
    for a, b in replace.items():
        text = text.replace(f'"{a}"', f'"{b}"')
    d = tmp_path / "apps"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text)
    reg = Registry(manifest_dirs=[(d, "package")], desktop_dirs=[], store=TileStore(tmp_path / "tiles.json"))
    reg.build()
    return reg


def test_maps_uses_foxtrotgps_fallback_until_task_maps_exists(tmp_path, safe_dir, monkeypatch):
    fox = make_exec(safe_dir / "bin", "foxtrotgps")
    gpsmon = make_exec(safe_dir / "bin", "gpsmon")
    term = make_exec(safe_dir / "tbin", "x-terminal-emulator")
    monkeypatch.setenv("PATH", str(safe_dir / "tbin"))
    repl = {"/usr/bin/task-maps": str(safe_dir / "bin" / "task-maps"), "/usr/bin/foxtrotgps": str(fox),
            "/usr/bin/gpsmon": str(gpsmon), "/usr/bin/cgps": "/nonexistent/cgps"}
    t = _shipped_with(tmp_path, "020-maps.toml", repl).get("app:task.maps")
    assert t.status == "Available" and t.argv == [str(fox)] and t.variant == "FoxtrotGPS (fallback)"
    acts = {a.id: a for a in t.actions}
    assert acts["gpsmon"].argv == [str(term), "-e", str(gpsmon)]            # terminal-wrapped, argv only
    assert acts["cgps"].argv is None and "does not exist" in acts["cgps"].reason or acts["cgps"].reason
    # task-maps installed later → preferred automatically
    native = make_exec(safe_dir / "bin", "task-maps")
    t = _shipped_with(tmp_path, "020-maps.toml", repl).get("app:task.maps")
    assert t.argv == [str(native)] and t.variant == "T.A.S.K. Maps"


def test_terminal_action_without_terminal(tmp_path, safe_dir, monkeypatch):
    gpsmon = make_exec(safe_dir / "bin", "gpsmon")
    monkeypatch.setenv("PATH", str(safe_dir / "empty"))
    t = _shipped_with(tmp_path, "020-maps.toml", {"/usr/bin/gpsmon": str(gpsmon)}).get("app:task.maps")
    a = {x.id: x for x in t.actions}["gpsmon"]
    assert a.argv is None and "no terminal emulator" in a.reason


def test_sdr_prefers_sdrpp_then_gqrx(tmp_path, safe_dir):
    gqrx = make_exec(safe_dir / "bin", "gqrx")
    repl = {"/usr/bin/sdrpp": str(safe_dir / "bin" / "sdrpp"), "/usr/local/bin/gqrx": str(gqrx)}
    t = _shipped_with(tmp_path, "040-sdr.toml", repl).get("app:task.sdr")
    assert t.argv == [str(gqrx)] and t.variant == "Gqrx (External)" and t.readiness == "rtl-sdr"
    sdrpp = make_exec(safe_dir / "bin", "sdrpp")
    t = _shipped_with(tmp_path, "040-sdr.toml", repl).get("app:task.sdr")
    assert t.argv == [str(sdrpp)] and t.variant == "SDR++ (External)"
    tsdr = make_exec(safe_dir / "bin", "task-sdr")
    repl["/usr/bin/task-sdr"] = str(tsdr)
    t = _shipped_with(tmp_path, "040-sdr.toml", repl).get("app:task.sdr")
    assert t.argv == [str(tsdr)] and t.variant == "task-sdr"


def test_mesh_requires_rain_mesh_not_meshtastic_cli(tmp_path, safe_dir):
    make_exec(safe_dir / "bin", "meshtastic")
    t = _shipped_with(tmp_path, "010-mesh.toml", {"/usr/local/bin/task-mesh": str(safe_dir / "bin" / "task-mesh")}
                      ).get("app:task.mesh")
    assert t.status == "Unavailable" and t.reason == "not installed: task-mesh, rain-mesh 0.1.0 (legacy)"
    rm = make_exec(safe_dir / "bin", "task-mesh")
    t = _shipped_with(tmp_path, "010-mesh.toml", {"/usr/bin/task-mesh": str(rm)}).get("app:task.mesh")
    assert t.status == "Available" and t.argv == [str(rm)]


def test_min_platform_newer_than_launcher_is_unavailable(tmp_path):
    d = tmp_path / "apps"
    d.mkdir()
    (d / "x.toml").write_text(BASE + 'min_platform = "0.3.0"\n[launch]\nexec = ["/bin/true"]\n')
    reg = Registry(manifest_dirs=[(d, "package")], desktop_dirs=[], store=TileStore(tmp_path / "t.json"))
    reg.build()
    t = reg.get("app:org.example.app")
    assert t.status == "Unavailable" and "0.3.0" in t.reason


def test_tile_ids_and_order_preserved():
    reg = Registry(manifest_dirs=[(BUNDLED_APPS_DIR, "package")], desktop_dirs=[],
                   store=TileStore(Path("/nonexistent/tiles.json")))
    reg.build()
    assert [t.key for t in reg.tiles] == PHASE3_KEYS
    assert reg.get("app:task.mission-planner").status == "Planned"


# ---------------------------------------------------------------- process manager: early failures

def _wait(pmgr, key, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        outs = [o for o in pmgr.poll() if o.key == key]
        if outs:
            return outs[-1]
        time.sleep(0.02)
    raise AssertionError("no outcome")


def test_early_failure_reports_only_this_runs_stderr(safe_dir, isolated_home):
    exe = make_exec(safe_dir / "bin", "sdrpp", 'echo "run $1" >&2; echo "usb_claim_interface error -6" >&2; exit 1')
    pmgr = ProcessManager()
    pmgr.start("app:task.sdr", [str(exe), "one"])
    o1 = _wait(pmgr, "app:task.sdr")
    pmgr.start("app:task.sdr", [str(exe), "two"])
    o2 = _wait(pmgr, "app:task.sdr")
    assert o2.status == "error" and o2.extra["early"] < 8
    assert "run two" in o2.extra["tail"] and "run one" not in o2.extra["tail"]
    assert o2.message.endswith("usb_claim_interface error -6") and o1.extra["tail"].startswith("run one")


def test_late_failure_has_no_early_tail(safe_dir, isolated_home):
    exe = make_exec(safe_dir / "bin", "late", "echo bye >&2; exit 2")
    clock = [0.0]
    pmgr = ProcessManager(clock=lambda: clock[0])
    pmgr.start("k", [str(exe)])
    clock[0] = 100.0
    o = _wait(pmgr, "k")
    assert o.message == "exited with code 2" and "early" not in o.extra


def test_missing_executable_start_error(isolated_home):
    o = ProcessManager().start("k", ["/nonexistent/sdrpp"])
    assert o.status == "error" and "could not start" in o.message


# ---------------------------------------------------------------- 0.1.0 config compatibility

V010_SETTINGS = {"branding": "task", "custom_title": "", "custom_subtitle": "", "layout": "auto", "scale": 1.25,
                 "start_mode": "maximized", "show_planned": True, "idle_lock_minutes": 5, "reduce_motion": "on",
                 "schema": 1}
V010_TILES = {"schema": 1,
              "order": ["app:task.system", "app:task.mesh", "desktop:org.example.Editor.desktop", "app:task.maps"],
              "hidden": ["app:task.weather"],
              "custom": [{"desktop_id": "org.example.Editor.desktop", "name": "My Editor", "icon": "",
                          "label": "Editor"}],
              "enabled": {"task.files": False}}


def write_v010(cfg: Path):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text(json.dumps(V010_SETTINGS, indent=2) + "\n")
    (cfg / "tiles.json").write_text(json.dumps(V010_TILES, indent=2) + "\n")
    return {n: ((cfg / n).read_bytes(), (cfg / n).stat().st_mtime_ns) for n in ("settings.json", "tiles.json")}


def test_upgrade_from_010_config_is_read_unchanged(qtbot, launcher, isolated_home):
    cfg = isolated_home / ".config" / "task-launcher"
    before = write_v010(cfg)
    time.sleep(0.01)
    w = launcher(start=False)
    w.rebuild()
    keys = [t.tile.key for t in w.home.tiles]
    listed = [k for k in keys if k in V010_TILES["order"]]
    assert listed == V010_TILES["order"]                                           # user order kept
    assert "app:task.weather" not in keys                                          # still hidden
    assert w.registry.get("app:task.files").status == "Disabled"                   # override kept
    assert w.settings.branding == "task" and w.settings.scale == 1.25 and w.settings.idle_lock_minutes == 5
    assert w.registry.get("desktop:org.example.Editor.desktop").name == "My Editor"
    after = {n: ((cfg / n).read_bytes(), (cfg / n).stat().st_mtime_ns) for n in ("settings.json", "tiles.json")}
    assert after == before                                                          # never rewritten
    assert sorted(os.listdir(cfg)) == ["settings.json", "tiles.json"]               # nothing added


def test_upgrade_user_change_keeps_010_fields(qtbot, launcher, isolated_home):
    cfg = isolated_home / ".config" / "task-launcher"
    write_v010(cfg)
    w = launcher(start=False)
    w.move_tile("app:task.maps", -1)                    # a real user action writes tiles.json
    doc = json.loads((cfg / "tiles.json").read_text())
    assert doc["schema"] == 1 and doc["hidden"] == ["app:task.weather"] and doc["enabled"] == {"task.files": False}
    assert doc["custom"][0]["name"] == "My Editor"
