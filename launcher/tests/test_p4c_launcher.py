# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4C launcher 0.3.0: rebrand, legacy tile-id aliases, status cards, radio/SDR app preference."""

import json
import os
import re
import time
from pathlib import Path

from conftest import make_exec
from task_launcher import __version__, branding
from task_launcher.registry.discovery import BUNDLED_APPS_DIR
from task_launcher.registry.registry import Registry
from task_launcher.registry.tilestore import TileStore, migrate_key
from task_launcher.services import readiness, statuscards

PKG = Path(__file__).resolve().parents[1] / "task_launcher"
TWELVE = ["task.mesh", "task.maps", "task.radio", "task.sdr", "task.library", "task.mission-planner",
          "task.medical", "task.weather", "task.devices", "task.files", "task.system", "task.app-manager"]


def test_l01_version_and_twelve_task_ids():
    assert __version__ == "0.3.7"
    ids = sorted(re.search(r'^id = "([^"]+)"', p.read_text(), re.M).group(1) for p in BUNDLED_APPS_DIR.glob("*.toml"))
    assert ids == sorted(TWELVE)


def test_l02_saved_rain_layout_is_kept(tmp_path):
    p = tmp_path / "tiles.json"
    p.write_text(json.dumps({"schema": 1, "order": ["app:rain.sdr", "app:rain.mesh", "desktop:foo.desktop"],
                             "hidden": ["app:rain.weather", "app:rain.app-manager"], "custom": [],
                             "enabled": {"rain.medical": False}}))
    st = TileStore(p)
    assert st.order == ["app:task.sdr", "app:task.mesh", "desktop:foo.desktop"]
    assert st.hidden == {"app:task.weather"}  # App Manager stays unhideable after the rename
    assert st.enabled == {"task.medical": False}
    assert migrate_key("desktop:rain.desktop") == "desktop:rain.desktop"
    reg = Registry(desktop_dirs=[], store=st)
    reg.build()
    keys = [t.key for t in reg.visible()]
    assert keys.index("app:task.sdr") < keys.index("app:task.mesh")  # saved relative order honoured
    assert "app:task.weather" not in keys and "app:task.app-manager" in keys


def test_l03_branding_defaults_to_task_and_rain_is_alias():
    assert branding.resolve("default", system=()) == ("T.A.S.K.", "Tactical Access Support Kit")
    assert branding.resolve("rain") == ("T.A.S.K.", "Tactical Access Support Kit")
    assert branding.resolve("custom", "", "", system=()) == ("T.A.S.K.", "Tactical Access Support Kit")


def test_l04_no_rain_branding_in_ui_strings():
    hits = []
    for p in PKG.rglob("*.py"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "R.A.I.N." in line or "Remote Access Information Network" in line:
                hits.append(f"{p.name}:{i}")
    for p in BUNDLED_APPS_DIR.glob("*.toml"):
        if "R.A.I.N." in p.read_text():
            hits.append(p.name)
    assert hits == []


def _card(d, module, **kw):
    doc = {"schema": 1, "module": module, "state": "queued", "device": "Direwolf ch0", "summary": "1 frame queued",
           "counts": {"heard": 4}, "last_error": None, "indicators": ["QUEUED"], "pid": os.getpid(),
           "heartbeat_ts": time.time()}
    doc.update(kw)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{module}.json").write_text(json.dumps(doc))


def test_l05_status_cards_shown_and_stale(tmp_path):
    _card(tmp_path, "task-aprs")
    _card(tmp_path, "task-sdr", state="connected", summary="WFM 101.1 MHz", indicators=[], heartbeat_ts=time.time() - 60)
    (tmp_path / "task-mesh.json").write_text("{broken")
    cards = statuscards.collect(tmp_path)
    assert statuscards.card_text(cards["direwolf"]) == "QUEUED · 1 frame queued · QUEUED"
    assert statuscards.card_text(cards["rtl-sdr"]).startswith("not responding")
    assert statuscards.card_text(cards["mesh"]).startswith("not responding")
    pr = readiness.ProbeResults()
    pr.cards = cards
    line = pr.line("direwolf", None)
    assert line.text.startswith("QUEUED · 1 frame queued")
    assert "ON-AIR" not in line.text
    _card(tmp_path, "task-aprs", pid=999999999)  # dead process
    assert statuscards.read_card("task-aprs", tmp_path)["_stale"]


def test_l06_status_card_absent_means_plain_readiness(tmp_path):
    pr = readiness.ProbeResults()
    pr.cards = statuscards.collect(tmp_path / "none")
    assert pr.line("mesh", None).text == readiness.mesh_readiness(None, None).text


def _shipped(tmp_path, name, repl):
    text = (BUNDLED_APPS_DIR / name).read_text()
    for a, b in repl.items():
        text = text.replace(f'"{a}"', f'"{b}"')
    d = tmp_path / "apps"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text)
    reg = Registry(manifest_dirs=[(d, "package")], desktop_dirs=[], store=TileStore(tmp_path / "tiles.json"))
    reg.build()
    return reg


def test_l07_radio_prefers_task_aprs_else_builtin_monitor(tmp_path, safe_dir):
    t = _shipped(tmp_path, "030-radio.toml", {"/usr/bin/task-aprs": str(safe_dir / "bin" / "task-aprs")}).get("app:task.radio")
    assert t.status == "Available" and t.argv is None and t.variant == "built-in receive-only monitor"
    aprs = make_exec(safe_dir / "bin", "task-aprs")
    t = _shipped(tmp_path, "030-radio.toml", {"/usr/bin/task-aprs": str(aprs)}).get("app:task.radio")
    assert t.status == "Available" and t.argv == [str(aprs)]


def test_l08_mesh_legacy_binary_still_launches(tmp_path, safe_dir):
    legacy = make_exec(safe_dir / "bin", "rain-mesh")
    t = _shipped(tmp_path, "010-mesh.toml", {"/usr/bin/task-mesh": str(safe_dir / "bin" / "task-mesh"),
                                            "/usr/local/bin/task-mesh": str(safe_dir / "bin" / "x"),
                                            "/usr/bin/rain-mesh": str(legacy)}).get("app:task.mesh")
    assert t.argv == [str(legacy)]


def test_l09_launcher_socket_fallback():
    from task_launcher.core.client import resolve_socket
    have = {"/run/rain/core.sock"}
    assert resolve_socket(environ={}, exists=have.__contains__) == "/run/rain/core.sock"
    have.add("/run/task/core.sock")
    assert resolve_socket(environ={}, exists=have.__contains__) == "/run/task/core.sock"


def test_l4d_library_prefers_task_resources_else_builtin_4a_viewer(tmp_path, safe_dir):
    """Phase 4D (launcher 0.3.1): Library tile -> task-resources when installed, 4A window otherwise."""
    t = _shipped(tmp_path, "050-library.toml",
                 {"/usr/bin/task-resources": str(safe_dir / "bin" / "task-resources")}).get("app:task.library")
    assert t.status == "Available" and t.argv is None and t.variant == "native viewer"
    res = make_exec(safe_dir / "bin", "task-resources")
    t = _shipped(tmp_path, "050-library.toml", {"/usr/bin/task-resources": str(res)}).get("app:task.library")
    assert t.status == "Available" and t.argv == [str(res)]
