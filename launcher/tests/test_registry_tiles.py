# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Registry statuses and launcher-side tile customisation (tiles.json). TEST DATA only."""

import json

import pytest

from conftest import make_exec, write_desktop
from task_launcher.registry import desktop as D
from task_launcher.registry.discovery import BUNDLED_APPS_DIR
from task_launcher.registry.registry import Registry
from task_launcher.registry.tilestore import TileStore

BUILTIN_KEYS = ["app:task.mesh", "app:task.maps", "app:task.radio", "app:task.sdr", "app:task.library",
                "app:task.mission-planner", "app:task.medical", "app:task.weather", "app:task.devices",
                "app:task.files", "app:task.system", "app:task.app-manager"]


def make_registry(tmp_path, desktop_dirs=None, manifest_dirs=None, core_version=None):
    reg = Registry(manifest_dirs=manifest_dirs or [(BUNDLED_APPS_DIR, "package")], desktop_dirs=desktop_dirs or [],
                   store=TileStore(tmp_path / "tiles.json"), desktops=["labwc"],
                   core_version_fn=lambda: core_version)
    reg.set_desktop_entries(reg.scan_desktop())
    reg.build()
    return reg


def test_default_tiles_and_honest_statuses(tmp_path):
    reg = make_registry(tmp_path)
    assert [t.key for t in reg.visible()] == BUILTIN_KEYS
    st = {t.key: (t.status, t.reason) for t in reg.tiles}
    # Phase 4A: only Mission Planner stays Planned. Exec tiles are Unavailable on this box (the apps
    # are not installed here); the native windows are Available.
    assert st["app:task.mission-planner"][0] == "Planned"
    for k in ("app:task.mesh", "app:task.maps", "app:task.sdr"):
        assert st[k][0] == "Unavailable" and st[k][1].startswith("not installed"), (k, st[k])
    for k in ("app:task.radio", "app:task.library", "app:task.medical", "app:task.weather"):
        assert st[k][0] == "Available", (k, st[k])
    assert st["app:task.devices"] == ("Unavailable", "task-console not installed")   # not on this box
    assert st["app:task.system"][0] == "Available" and st["app:task.app-manager"][0] == "Available"
    assert all(t.source == "builtin" for t in reg.tiles if t.builtin)


def test_devices_available_when_rain_console_present(tmp_path, safe_dir):
    rc = make_exec(safe_dir / "bin", "task-console")
    mdir = tmp_path / "m"
    mdir.mkdir()
    text = (BUNDLED_APPS_DIR / "090-devices.toml").read_text().replace('"/usr/local/bin/task-console"', f'"{rc}"')
    (mdir / "090-devices.toml").write_text(text)
    reg = make_registry(tmp_path, manifest_dirs=[(mdir, "package")])
    t = reg.get("app:task.devices")
    assert t.status == "Available" and t.argv == [str(rc)]


def test_core_min_version_gate(tmp_path):
    reg = make_registry(tmp_path, core_version="0.1.1")
    t = reg.get("app:task.devices")
    assert t.status == "Unavailable" and "requires task-core 0.2.0" in t.reason


def test_add_rename_icon_remove_persist(tmp_path, safe_dir):
    apps = tmp_path / "apps"
    exe = make_exec(safe_dir / "bin", "editor")
    p = write_desktop(apps, "org.example.Editor.desktop", Name="Editor", Exec=f"{exe} %F", Icon="accessories-text-editor")
    before = p.read_bytes()
    reg = make_registry(tmp_path, desktop_dirs=[apps])
    key = reg.add_desktop("org.example.Editor.desktop")
    reg.build()
    assert [t.key for t in reg.visible()] == BUILTIN_KEYS + [key]   # appended after the 12 built-ins
    t = reg.get(key)
    assert t.source == "desktop" and t.status == "Available" and t.argv == [str(exe)]
    assert t.icon == ("theme", "accessories-text-editor")
    reg.store.rename("org.example.Editor.desktop", "  My   Editor ")
    reg.store.set_icon("org.example.Editor.desktop", "/nonexistent.png")
    reg2 = make_registry(tmp_path, desktop_dirs=[apps])            # reload from tiles.json
    t2 = reg2.get(key)
    assert t2.name == "My Editor" and t2.icon == "shapes"          # invalid icon path -> fallback
    assert p.read_bytes() == before                               # .desktop never modified
    doc = json.loads((tmp_path / "tiles.json").read_text())
    assert doc["schema"] == 1 and doc["custom"][0]["desktop_id"] == "org.example.Editor.desktop"
    assert oct((tmp_path / "tiles.json").stat().st_mode & 0o777) == "0o600"
    assert reg2.remove_tile(key) is True
    reg2.build()
    assert key not in [t.key for t in reg2.tiles]
    assert p.exists()                                             # removing a tile never uninstalls


def test_uninstalled_app_becomes_unavailable_and_removable(tmp_path, safe_dir):
    apps = tmp_path / "apps"
    exe = make_exec(safe_dir / "bin", "gone")
    p = write_desktop(apps, "gone.desktop", Name="Gone", Exec=str(exe))
    reg = make_registry(tmp_path, desktop_dirs=[apps])
    key = reg.add_desktop("gone.desktop")
    p.unlink()
    reg.set_desktop_entries(reg.scan_desktop())
    reg.build()
    t = reg.get(key)
    assert t.status == "Unavailable" and "no longer installed" in t.reason and t.name == "Gone"
    assert reg.remove_tile(key)


def test_move_reorder_and_reset(tmp_path):
    reg = make_registry(tmp_path)
    reg.move("app:task.system", -10)
    reg.build()
    assert reg.visible()[0].key == "app:task.system"
    reg.move("app:task.system", 100)
    reg.build()
    assert reg.visible()[-1].key == "app:task.system"
    reg.remove_tile("app:task.mesh")
    reg.build()
    assert "app:task.mesh" not in [t.key for t in reg.visible()]
    reg2 = make_registry(tmp_path)
    assert reg2.visible()[-1].key == "app:task.system"
    reg2.store.reset_layout()
    reg2.build()
    assert [t.key for t in reg2.visible()] == BUILTIN_KEYS


def test_reset_keeps_custom_tiles(tmp_path, safe_dir):
    apps = tmp_path / "apps"
    exe = make_exec(safe_dir / "bin", "a")
    write_desktop(apps, "a.desktop", Name="A", Exec=str(exe))
    write_desktop(apps, "b.desktop", Name="B", Exec=str(exe))
    reg = make_registry(tmp_path, desktop_dirs=[apps])
    reg.add_desktop("a.desktop")
    reg.add_desktop("b.desktop")
    reg.build()
    reg.move("desktop:b.desktop", -20)
    reg.store.reset_layout()
    reg.build()
    assert [t.key for t in reg.visible()] == BUILTIN_KEYS + ["desktop:a.desktop", "desktop:b.desktop"]


def test_app_manager_cannot_be_hidden_or_disabled(tmp_path):
    reg = make_registry(tmp_path)
    with pytest.raises(ValueError):
        reg.remove_tile("app:task.app-manager")
    with pytest.raises(ValueError):
        reg.set_enabled(reg.get("app:task.app-manager"), False)


def test_disable_enable(tmp_path):
    reg = make_registry(tmp_path)
    reg.set_enabled(reg.get("app:task.system"), False)
    reg.build()
    assert reg.get("app:task.system").status == "Disabled"
    reg.set_enabled(reg.get("app:task.system"), True)
    reg.build()
    assert reg.get("app:task.system").status == "Available"
    assert json.loads((tmp_path / "tiles.json").read_text())["enabled"] == {}


@pytest.mark.parametrize("content", [b"{bad json", b'{"schema": 99}', b"[]"])
def test_corrupt_store_falls_back_to_defaults(tmp_path, content):
    (tmp_path / "tiles.json").write_bytes(content)
    reg = make_registry(tmp_path)
    assert [t.key for t in reg.visible()] == BUILTIN_KEYS
    assert reg.store.load_problem


def test_store_sanitises_keys(tmp_path):
    (tmp_path / "tiles.json").write_text(json.dumps({
        "schema": 1, "order": ["app:task.system", "../../etc", "app:task.system"],
        "hidden": ["app:task.app-manager", "app:task.mesh"],
        "custom": [{"desktop_id": "../evil"}, {"desktop_id": "ok.desktop", "name": "x" * 99}], "enabled": {"a": "yes"}}))
    s = TileStore(tmp_path / "tiles.json")
    assert s.order == ["app:task.system"]
    assert s.hidden == {"app:task.mesh"}
    assert [c["desktop_id"] for c in s.custom] == ["ok.desktop"] and len(s.custom[0]["name"]) == 40
    assert s.enabled == {}


def test_desktop_tile_launch_plan_uses_terminal_detection(tmp_path, safe_dir, monkeypatch):
    bindir = safe_dir / "bin"
    make_exec(bindir, "top")
    make_exec(bindir, "foot")
    monkeypatch.setenv("PATH", str(bindir))
    apps = tmp_path / "apps"
    write_desktop(apps, "top.desktop", Name="Top", Exec="top", Terminal="true")
    reg = make_registry(tmp_path, desktop_dirs=[apps])
    reg.add_desktop("top.desktop")
    reg.build()
    assert reg.get("desktop:top.desktop").argv == [str(bindir / "foot"), str(bindir / "top")]
    assert D.find_terminal(str(bindir))[0] == str(bindir / "foot")
