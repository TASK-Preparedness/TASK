# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tests 56, 57, 58, 59, 62, 63, 73 and 74. TEST DATA only (golden fixture)."""

import time

from PySide6.QtCore import QTimer

from helpers import payload_spy, ui_findings
from p2fixtures import CP2102_ID, SDR_ID, UBLOX_ID, V2Client, login, ublox
from task_core.devices import RawDevice

DASH = "\u2014"
OPERATOR_METHODS = {"device.list", "device.get", "device.assign", "device.unassign", "events.recent"}


def public_call(core, method):
    client = V2Client(core.config.socket)
    try:
        return client.call(method)["result"]
    finally:
        client.close()


def ch340(devnode="/dev/ttyUSB1"):
    """A device with no serial and no by-id: identity_stable is false (TEST DATA)."""
    return RawDevice(devnode=devnode, vid="1a86", pid="7523", serial=None, manufacturer="QinHeng",
                     product="USB Serial", subsystem="usb-serial", bus_path="platform-xhci-hcd.0-usb-0:2")


def test_56_home_tiles_mirror_module_and_capability_lists(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    modules = public_call(core, "module.list")["modules"]
    caps = {e["name"]: e["status"] for e in public_call(core, "capability.list")["capabilities"]}
    tiles = c.window.home.tiles
    expected_order = sorted(modules, key=lambda m: (m["id"] != "system", m["id"]))
    assert [t.module_id for t in tiles] == [m["id"] for m in expected_order]
    sent_states = {m["state"] for m in modules}
    for tile, module in zip(tiles, expected_order):
        assert tile.name.text() == module["name"]
        assert tile.state.text() == f"State: {module['state']}"
        assert tile.state.text()[len("State: "):] in sent_states
        assert tile.reason.text() == f"Reason: {module['reason'] if module['reason'] else DASH}"
        requires = module["capabilities"]["requires"]
        assert tile.caps.text() == "Capabilities: " + ("; ".join(f"{n} {caps[n]}" for n in requires) or DASH)
        assert tile.logical.text() == "Logical devices: Sign in to view"
    assert all("available" not in t.state.text() for t in tiles)
    # unknown values render as an em dash
    c.controller.modules[0]["name"] = None
    c.controller.modules[0]["reason"] = None
    c.controller.changed.emit("modules")
    c.settle()
    assert tiles[0].name.text() == DASH and tiles[0].reason.text() == f"Reason: {DASH}"
    # operator: the backing logical device is shown
    c.sign_in("op")
    gps = next(t for t in c.window.home.tiles if t.module_id == "gps")
    assert gps.logical.text() == "Logical devices: gps.primary \u00b7 assigned \u00b7 connected"
    sdr = next(t for t in c.window.home.tiles if t.module_id == "sdr")
    assert sdr.logical.text() == "Logical devices: sdr.primary \u00b7 unassigned"
    system = next(t for t in c.window.home.tiles if t.module_id == "system")
    assert system.logical.text() == f"Logical devices: {DASH}"
    # placeholder
    c.window.open_module("gps")
    assert c.window.module.note.text() == "This module has no interface in Phase 2."
    assert c.window.module.fields["Logical devices"].text() == "gps.primary"


def _core_fields(window):
    return {k: v.text() for k, v in window.core.fields.items() if k not in ("Connection", "Last event seq")}


def test_57_core_status_matches_and_is_identical_for_every_role(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    protocol = V2Client(core.config.socket).call("core.protocol")["result"]
    health = public_call(core, "core.health")
    counts = public_call(core, "device.counts")
    c.window.show_panel("core")
    c.settle()
    fields = c.window.core.fields
    assert fields["Version"].text() == health["version"] == "0.2.1"
    assert fields["Server uid"].text() == str(health["uid"])
    assert fields["Protocol versions"].text() == "1, 2"
    assert fields["Boot id"].text() == protocol["boot_id"][:8] + "\u2026"
    assert fields["Devices"].text() == (f"{counts['total']} total \u00b7 {counts['connected']} connected \u00b7 "
                                        f"{counts['disconnected']} disconnected")
    assert fields["Socket"].text() == core.config.socket
    assert fields["Uptime"].text().endswith("F5 refreshes)")
    public = _core_fields(c.window)
    caps_rows = c.window.core.caps.rowCount()
    for user in ("op", "dragon"):
        if c.controller.signed_in:
            c.controller.lock("test")
            c.controller.continue_public()
        c.sign_in(user)
        c.settle(100)
        now = _core_fields(c.window)
        assert {k: v for k, v in now.items() if k != "Uptime"} == {k: v for k, v in public.items() if k != "Uptime"}
        assert c.window.core.caps.rowCount() == caps_rows


def test_58_public_view_in_the_ui(p2env, console):
    core = p2env()
    seen = payload_spy(core)
    c = console(core.config.socket)
    w = c.window
    for key in ("home", "core", "devices"):
        w.show_panel(key)
        c.settle()
        assert ui_findings(w) == [], key
        assert ui_findings(w, visible_only=False) == [], key
    w.open_module("gps")
    c.settle()
    assert ui_findings(w, visible_only=False) == []
    assert w.module.fields["Logical devices"].text() == "Sign in to view"
    w.show_panel("devices")
    assert w.devices.pages.currentIndex() == 0
    assert w.devices.public_counts.text() == "3 connected \u00b7 0 disconnected \u00b7 3 total"
    assert w.devices.public_prompt.text() == "Sign in as operator or administrator to view devices."
    # a hot-plug while public: counts update, still nothing identifying
    core._fake.add(ch340())
    c.qtbot.waitUntil(lambda: w.devices.public_counts.text().startswith("4 connected"), timeout=2000)
    assert ui_findings(w, visible_only=False) == []
    methods = [p["method"] for p in seen]
    assert "device.counts" in methods
    assert not [m for m in methods if (m.startswith("device.") and m != "device.counts") or m == "events.recent"]
    assert all("session" not in p for p in seen)


def test_59_devices_by_role(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    w = c.window
    w.show_panel("devices")
    c.sign_in("op")
    d = w.devices
    assert d.pages.currentIndex() == 1 and d.model.rowCount() == 3
    assert d.role_note.isVisible() and d.role_note.text() == "Assigning devices requires an administrator."
    assert d.select_device(UBLOX_ID)
    c.settle()
    assert d.detail.values["id"].text() == UBLOX_ID
    assert not d.detail.assign.isVisible()
    assert not any(b.isVisible() for b in d.slot_buttons.values())
    c.controller.lock("test")
    c.controller.continue_public()
    c.sign_in("dragon")
    assert d.select_device(UBLOX_ID)
    c.settle()
    assert d.detail.assign.isVisible() and d.detail.assign.isEnabled()
    assert d.slot_buttons["gps.primary"].isVisible()
    assert not d.slot_buttons["mesh.primary"].isVisible()  # unassigning an empty slot is not offered
    assert not d.role_note.isVisible()


def test_62_slots_always_shown_and_disconnected_assignment(p2env, console):
    core = p2env(devices=[])  # gps.primary assigned in devices.json, device absent: placeholder record
    c = console(core.config.socket)
    c.sign_in("op")
    labels = c.window.devices.slot_labels
    assert list(labels) == ["gps.primary", "mesh.primary", "sdr.primary", "radio.primary"]
    assert labels["gps.primary"].text() == (f'gps.primary: {DASH} \u00b7 {UBLOX_ID} \u00b7 alias "smoke" \u00b7 '
                                            "Disconnected \u2014 assignment kept")
    for logical in ("mesh.primary", "sdr.primary", "radio.primary"):
        assert labels[logical].text() == f"{logical}: Unassigned"
    raw = ublox()
    core._fake.add(raw)
    c.qtbot.waitUntil(lambda: labels["gps.primary"].text().endswith("Connected") and "u-blox 7" in
                      labels["gps.primary"].text(), timeout=2000)
    core._fake.remove(raw)
    c.qtbot.waitUntil(lambda: labels["gps.primary"].text().endswith("Disconnected \u2014 assignment kept"),
                      timeout=2000)
    assert "u-blox 7 - GPS/GNSS Receiver" in labels["gps.primary"].text()


def test_63_live_update_and_no_polling(p2env, console):
    core = p2env()
    seen = payload_spy(core)
    public = console(core.config.socket)
    c = console(core.config.socket)
    c.sign_in("op")
    c.settle(600)
    before = len(seen)
    c.qtbot.wait(1500)  # steady state: nothing is polled
    assert [p["method"] for p in seen[before:]] == []
    start = time.monotonic()
    core._fake.add(ch340())
    c.qtbot.waitUntil(lambda: c.window.devices.model.rowCount() == 4, timeout=1000)
    c.qtbot.waitUntil(lambda: public.window.devices.public_counts.text().startswith("4 connected"), timeout=1000)
    assert time.monotonic() - start < 1.0
    c.settle(400)
    methods = [p["method"] for p in seen[before:]]
    assert set(methods) <= {"device.list"} and 1 <= methods.count("device.list") <= 2
    assert all(p["method"] != "events.since" for p in seen)


def test_73_panel_fault_is_contained(p2env, console, monkeypatch):
    core = p2env()
    c = console(core.config.socket)
    w = c.window

    def boom(area="all"):
        raise RuntimeError("injected panel fault")

    monkeypatch.setattr(w.core, "render", boom)
    w.show_panel("core")
    c.controller.changed.emit("health")
    c.settle()
    host = w.hosts["core"]
    assert host.currentWidget() is host.error_page
    assert host.error_label.text() == "This panel failed. Details are in the log."
    w.show_panel("devices")
    c.controller.changed.emit("counts")
    c.settle()
    assert w.devices.public_counts.text().startswith("3 connected")
    w.show_panel("home")
    assert len(w.home.tiles) == 7
    monkeypatch.undo()
    w.show_panel("core")
    host.reload_button.click()
    assert host.currentWidget() is w.core and w.core.fields["Version"].text() == "0.2.1"


def test_74_burst_keeps_gui_responsive_and_debounces(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    c.sign_in("op")
    c.settle(400)
    stamps = []
    original = core.handle_v2

    def spy(payload, uid):
        if payload.get("method") == "device.list":
            stamps.append(time.monotonic())
        return original(payload, uid)

    core.handle_v2 = spy
    gaps = []
    last = [time.monotonic()]

    def tick():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(10)
    c.qtbot.wait(100)
    for index in range(1000):
        core.bus.publish("device.appeared", "devmgr", {"id": f"dev_{index:016x}"})
    c.qtbot.wait(1500)
    timer.stop()
    assert max(gaps) < 0.100, max(gaps)
    assert stamps, "the burst triggered no device.list"
    assert all(b - a >= 0.195 for a, b in zip(stamps, stamps[1:])), stamps
    assert c.controller.live
