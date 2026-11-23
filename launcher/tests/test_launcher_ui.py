# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Launcher window: tiles, activation, customisation, App Manager, rescan, settings. TEST DATA."""

import json
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import make_exec, write_desktop
from task_launcher.layout import layout
from task_launcher.theme import C, CONTRAST_REQUIREMENTS, contrast
from task_launcher.ui.dialogs import InfoSheet

REFERENCE = ["Mesh Network", "Maps & GPS", "Radio / APRS", "SDR", "Library", "Mission Planner", "Medical",
             "Weather", "Devices", "Files", "System", "App Manager"]


def sheets():
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, InfoSheet) and w.isVisible()]


def test_reference_tiles_and_chrome(launcher):
    w = launcher(start=False)
    h = w.home
    assert [t.tile.name for t in h.tiles] == REFERENCE
    assert h.title.text() == "T.A.S.K." and h.subtitle.text() == "Tactical Access Support Kit"
    assert h.auth_chip.text() == "Public · Sign in"
    assert h.settings_btn.accessibleName() == "Settings"
    assert h.footer_right_plain() == "Internet: unknown · Offline-first"
    assert w.windowFlags() & Qt.WindowType.FramelessWindowHint == Qt.WindowType(0)   # ordinary decorated window
    states = {t.tile.name: t.state_line for t in h.tiles}
    assert states["Mission Planner"] == "Planned"
    assert states["Mesh Network"] == "Unavailable — not installed: task-mesh, rain-mesh 0.1.0 (legacy)"
    assert states["Maps & GPS"] == "Unavailable — not installed: T.A.S.K. Maps, FoxtrotGPS (fallback)"
    assert states["Library"] == "Available — native viewer"
    assert states["Devices"] == "Unavailable — task-console not installed"
    assert states["System"] == ""


@pytest.mark.parametrize("size,mode", [((1920, 1080), "large"), ((1366, 768), "compact"),
                                       ((1280, 720), "compact"), ((1024, 600), "compact")])
def test_layouts(launcher, size, mode):
    w = launcher(size=size, start=False)
    h = w.home
    assert h.L["effective"] == mode, h.L
    assert h.L["cols"] <= 3
    tiles = [t.geometry().translated(h.pager.pos()) for t in h.tiles]
    footer_top = h.core_label.geometry().top()
    header_bottom = max(h.subtitle.geometry().bottom() if h.subtitle.isVisible() else 0, h.auth_chip.geometry().bottom())
    visible = [g for i, g in enumerate(tiles) if h.page_of(i) == 0]
    assert all(g.top() >= header_bottom - 12 and g.bottom() <= footer_top + 12 for g in visible)
    # the title never overlaps the header chips
    assert h.title.geometry().right() < h.auth_chip.geometry().left()
    assert h.core_label.geometry().right() < h.db_icon.geometry().left()


def test_large_layout_numbers_match_spec():
    L = layout(1920, 1014, 1.0, "auto")
    assert L["effective"] == "large" and tuple(L["tile"]) == (576, 168)
    L = layout(1920, 1080, 1.0, "auto")
    assert tuple(L["tile"]) == (576, 185)


def test_contrast_requirements():
    for fg, bg, minimum, *_ in CONTRAST_REQUIREMENTS:
        assert contrast(C[fg], C[bg]) >= minimum, (fg, bg)


def test_branding_switch_without_code_change(launcher, tmp_path):
    from task_launcher.settings import Settings

    w = launcher(start=False, settings=Settings(branding="task"))
    assert w.home.title.text() == "T.A.S.K." and w.home.subtitle.text() == "Tactical Access Support Kit"
    assert w.windowTitle() == "T.A.S.K."
    assert w.home.core_label.text().startswith("T.A.S.K. Core")          # technical name stays
    from task_launcher import branding
    sysfile = tmp_path / "branding.toml"
    sysfile.write_text('preset = "task"\n')
    assert branding.resolve("default", system=branding.system_default(sysfile)) == branding.PRESETS["task"]
    assert branding.resolve("custom", "  My   Kit ", "x" * 80) == ("My Kit", "x" * 60)


def test_planned_tile_opens_info_only(launcher, monkeypatch):
    w = launcher(start=False)
    started = []
    monkeypatch.setattr(w.procs, "start", lambda *a, **k: started.append(a))
    s = w.activate(w.registry.get("app:task.mesh"))
    assert isinstance(s, InfoSheet) and started == []
    s.close()


def test_devices_falls_back_to_native_read_only_view(launcher):
    w = launcher(start=False)
    win = w.activate(w.registry.get("app:task.devices"))
    assert win is w.devices_window and win.isVisible()
    assert win.counts.text() == "task-core unavailable"


def test_devices_launches_rain_console_when_installed(launcher, tmp_path, safe_dir, monkeypatch):
    from task_launcher.registry.discovery import BUNDLED_APPS_DIR
    from task_launcher.registry.registry import Registry
    from task_launcher.registry.tilestore import TileStore

    rc = make_exec(safe_dir / "bin", "task-console", "exec sleep 20")
    m = tmp_path / "m"
    m.mkdir()
    for p in BUNDLED_APPS_DIR.glob("*.toml"):
        (m / p.name).write_text(p.read_text().replace('exec = ["/usr/bin/task-console"]', f'exec = ["{rc}"]'))
    reg = Registry(manifest_dirs=[(m, "package")], desktop_dirs=[], store=TileStore(tmp_path / "t.json"))
    w = launcher(start=False, registry=reg)
    t = reg.get("app:task.devices")
    out = w.activate(t)
    assert out.status == "running"
    assert w.home.tile_widget(t.key).state_line == "● Running"
    out2 = w.activate(t)                      # task-console raises its own window (relaunch helper)
    assert out2.status == "running" and len(w.procs.helpers) == 1
    for p in [w.procs.procs[t.key]] + w.procs.helpers:
        p.popen.kill()
        p.popen.wait()


def test_files_opens_home_with_xdg_open(launcher, monkeypatch):
    w = launcher(start=False)
    calls = []
    monkeypatch.setattr(w.procs, "start", lambda key, argv, **k: calls.append((key, argv, k)))
    w.activate(w.registry.get("app:task.files"))
    assert calls[0][1] == ["/usr/bin/xdg-open", os.path.expanduser("~")]
    assert calls[0][2]["single_instance"] is False


def test_failed_launch_shows_error_state(qtbot, launcher, safe_dir, isolated_home):
    exe = make_exec(safe_dir / "bin", "crash", "echo boom >&2; exit 7")
    apps = isolated_home / ".local/share/applications"
    write_desktop(apps, "crash.desktop", Name="Crashy", Exec=str(exe))
    w = launcher(start=False)
    key = w.add_desktop("crash.desktop")
    w.activate(w.registry.get(key))
    qtbot.waitUntil(lambda: w.runtime.get(key, {}).get("status") == "Error", timeout=5000)
    assert w.home.tile_widget(key).state_line.startswith("Error — exited with code 7")
    assert w.home.tile_widget(key).state_line.endswith("after start: boom")     # Phase 4A early-failure tail
    w.clear_error(key)
    assert w.home.tile_widget(key).state_line == ""


def test_system_window_shows_real_or_dash(qtbot, launcher):
    w = launcher(start=False)
    sw = w.open_builtin("system")
    qtbot.waitUntil(lambda: sw.fields["Hostname"].text() != "—", timeout=5000)
    assert sw.fields["Core version"].text() == "—"
    assert sw.fields["Core link"].text().startswith("T.A.S.K. Core ·")
    sw.close()
    assert sw.worker is None


def test_add_application_dialog_search_and_add(qtbot, launcher, isolated_home):
    apps = isolated_home / ".local/share/applications"
    write_desktop(apps, "org.test.Calc.desktop", Name="Calculator", Comment="Do sums", Keywords="math;", Exec="/bin/true")
    write_desktop(apps, "org.test.Term.desktop", Name="Terminal", Exec="/bin/true")
    write_desktop(apps, "org.test.Hidden.desktop", Name="Hidden", Exec="/bin/true", NoDisplay="true")
    write_desktop(apps, "org.test.Root.desktop", Name="Root tool", Exec="pkexec /bin/true")
    w = launcher(start=False)
    am = w.open_builtin("app-manager")
    assert not am.install_btn.isEnabled() and "Not available in Phase 3" in am.install_btn.toolTip()
    assert not am.uninstall_btn.isEnabled() and not am.update_btn.isEnabled()
    am.open_add()
    dlg = am.add_dialog
    names = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    assert any(n.startswith("Calculator") for n in names) and not any("Hidden" in n for n in names)
    assert not any("Root tool" in n for n in names)
    dlg.show_admin.setChecked(True)
    assert any("Root tool" in dlg.list.item(i).text() for i in range(dlg.list.count()))
    dlg.search.setText("math")
    vis = [dlg.list.item(i) for i in range(dlg.list.count()) if not dlg.list.item(i).isHidden()]
    assert len(vis) == 1 and vis[0].text().startswith("Calculator")
    dlg.list.setCurrentItem(vis[0])
    dlg.add_selected()
    assert w.home.tile_widget("desktop:org.test.Calc.desktop") is not None
    item = next(dlg.list.item(i) for i in range(dlg.list.count()) if dlg.list.item(i).text().startswith("Calculator"))
    assert not item.flags() & Qt.ItemFlag.ItemIsEnabled                   # already added
    dlg.close()


def test_rename_icon_remove_via_window(qtbot, launcher, isolated_home, monkeypatch):
    apps = isolated_home / ".local/share/applications"
    p = write_desktop(apps, "org.test.Ed.desktop", Name="Editor", Exec="/bin/true", Icon="text-editor")
    before = p.read_bytes()
    w = launcher(start=False)
    key = w.add_desktop("org.test.Ed.desktop")
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Notes", True)))
    w.rename_tile(w.registry.get(key), w)
    assert w.home.tile_widget(key).tile.name == "Notes"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    assert w.remove_tile(key, confirm_parent=w)
    assert w.home.tile_widget(key) is None
    assert p.read_bytes() == before
    assert not w.remove_tile("app:task.app-manager")


def test_tile_context_menu_actions(launcher, isolated_home):
    apps = isolated_home / ".local/share/applications"
    write_desktop(apps, "a.desktop", Name="A", Exec="/bin/true")
    w = launcher(start=False)
    key = w.add_desktop("a.desktop")
    m = w.tile_menu(w.home.tile_widget(key), None)
    labels = [a.text() for a in m.actions() if a.text()]
    assert labels[:5] == ["Open", "Move left", "Move right", "Move up", "Move down"]
    assert "Rename…" in labels and "Change icon…" in labels and "Remove from dashboard" in labels
    m.close()
    m2 = w.tile_menu(w.home.tile_widget("app:task.app-manager"), None)
    assert "Remove from dashboard" not in [a.text() for a in m2.actions()]
    m2.close()


def test_rescan_is_debounced_and_non_blocking(qtbot, launcher, isolated_home):
    apps = isolated_home / ".local/share/applications"
    w = launcher(start=False, scan=False, start_workers=True, net_reader=lambda: None)
    qtbot.waitUntil(lambda: not w.scanning, timeout=5000)
    assert str(apps) in w.watcher.directories()
    write_desktop(apps, "new.app.desktop", Name="Brand New", Exec="/bin/true")
    qtbot.waitUntil(lambda: "new.app.desktop" in w.registry.desktop_entries, timeout=8000)
    (apps / "new.app.desktop").unlink()
    qtbot.waitUntil(lambda: "new.app.desktop" not in w.registry.desktop_entries, timeout=8000)


def test_scan_runs_in_worker_thread(qtbot, launcher):
    import threading
    seen = []

    def scan():
        seen.append(threading.current_thread() is threading.main_thread())
        return {}

    w = launcher(start=False, scan=False, desktop_scan=scan)
    w.rescan()
    qtbot.waitUntil(lambda: not w.scanning, timeout=5000)
    assert seen == [False]


def test_settings_dialog_persists_atomically(qtbot, launcher, isolated_home):
    w = launcher(start=False)
    dlg = w.open_settings()
    s = dlg.result_settings()
    s.branding = "task"
    dlg.result_settings = lambda: s
    dlg.autostart_wanted = lambda: None
    dlg.accept()
    path = isolated_home / ".config/task-launcher/settings.json"
    doc = json.loads(path.read_text())
    assert doc["schema"] == 1 and doc["branding"] == "task"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert w.home.title.text() == "T.A.S.K."
    assert not list(path.parent.glob("*.tmp*"))


def test_settings_corrupt_and_normalised(isolated_home):
    from task_launcher import settings as S

    p = isolated_home / "s.json"
    p.write_text("{nope")
    assert S.load(p) == S.Settings()
    p.write_text(json.dumps({"scale": 9, "idle_lock_minutes": 99, "layout": "huge", "reduce_motion": 3}))
    s = S.load(p)
    assert s.scale == 1.5 and s.idle_lock_minutes == 10 and s.layout == "auto" and s.reduce_motion == "system"


def test_autostart_optional_and_reversible(isolated_home):
    from task_launcher import autostart

    assert not autostart.is_enabled()
    autostart.enable("T.A.S.K.")
    p = isolated_home / ".config/autostart/task-launcher.desktop"
    assert p.exists() and autostart.MARKER in p.read_text()
    assert autostart.disable() is True and not p.exists()
    p.write_text("[Desktop Entry]\nExec=something-else\n")          # someone else's entry
    with pytest.raises(FileExistsError):
        autostart.enable()
    assert autostart.disable() is False and p.exists()


def test_fullscreen_toggle_and_escape(qtbot, launcher):
    w = launcher(start=False)
    w.toggle_fullscreen()
    assert w.isFullScreen()
    w.toggle_fullscreen()
    assert not w.isFullScreen()


def test_worker_cleanup_on_shutdown(qtbot, launcher):
    from task_launcher.workers import live_workers

    w = launcher(start=False, scan=False, start_workers=True, net_reader=lambda: None)
    w.open_builtin("system")
    qtbot.waitUntil(lambda: not w.scanning, timeout=5000)
    assert live_workers()
    w.shutdown()
    assert live_workers() == []


def test_network_indicator(launcher, tmp_path):
    from task_launcher import netstatus as N

    st = N.from_nm({"State": 70, "Connectivity": 4, "PrimaryConnectionType": "802-11-wireless",
                    "ConnectivityCheckEnabled": True})
    assert (st.network, st.internet, st.kind) == ("Wi-Fi · connected", "online", "wifi")
    st = N.from_nm({"State": 70, "Connectivity": 4, "ConnectivityCheckEnabled": False})
    assert st.internet == "unknown" and "checking is off" in st.detail
    st = N.from_nm({"State": 20, "Connectivity": 1})
    assert st.network == "No network" and st.internet == "none"
    root = tmp_path / "net"
    for name, state, wifi in (("lo", "unknown", False), ("eth0", "down", False), ("wlan0", "up", True),
                              ("docker0", "up", False)):
        d = root / name
        d.mkdir(parents=True)
        (d / "operstate").write_text(state + "\n")
        if name not in ("lo", "docker0"):
            (d / "device").mkdir()
        if wifi:
            (d / "wireless").mkdir()
    st = N.collect(nm_reader=lambda: None, sysfs_root=str(root))
    assert st.source == "sysfs" and st.network == "Wi-Fi · link up" and st.internet == "unknown"
    w = launcher(start=False)
    w._on_net(st)
    assert w.home.net_chip.text() == "Wi-Fi · link up"
    assert w.home.footer_right_plain() == "Internet: unknown · Offline-first"


def test_nm_dbus_reader_on_a_private_bus_returns_none_without_nm():
    """Without NetworkManager on the bus the reader returns None (sysfs fallback)."""
    from PySide6.QtDBus import QDBusConnection

    from task_launcher import netstatus as N

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        pytest.skip("no D-Bus session bus in this environment")
    assert N.read_nm_dbus(bus=bus, timeout_ms=500) is None


def test_offscreen_accessibility_names(launcher):
    w = launcher(start=False)
    for t in w.home.tiles:
        assert t.accessibleName() == t.tile.name
        assert t.accessibleDescription().startswith(t.tile.name)
        assert t.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_focus_ring_is_keyboard_only(qtbot, launcher):
    from PySide6.QtTest import QTest

    from task_launcher.ui import widgets as W

    w = launcher(start=False)
    w.activateWindow()
    qtbot.waitUntil(w.isActiveWindow, timeout=2000)
    W.set_keyboard_mode(False)
    t = w.home.tiles[0]
    t.setFocus()
    assert t.hasFocus() and not W.focus_visible(t)
    # 0.3.7: input is observed on the top-level QWindow (as real X11/Wayland input arrives), not app-wide,
    # so the synthetic events go through the window handle instead of straight to the widget.
    wh = w.windowHandle()
    QTest.keyClick(wh, Qt.Key.Key_Right)
    assert W.focus_visible(w.home.tiles[1])
    pos = w.home.tiles[4].mapTo(w, w.home.tiles[4].rect().center())
    QTest.mousePress(wh, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseRelease(wh, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert not W._FocusVisible.keyboard
    for s in [x for x in QApplication.topLevelWidgets() if x.isVisible() and x is not w]:
        s.close()
