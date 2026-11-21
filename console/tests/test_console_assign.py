# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tests 60, 61, 69 and 72 (assign flow, warnings, forbidden, keyboard only). TEST DATA only."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox

from helpers import gone, payload_spy
from p2fixtures import CP2102_ID, DRAGON_PW, SDR_ID, UBLOX_ID, V2Client, login
from test_console_panels import ch340

DISPLACE_LINE = f"gps.primary will be removed from u-blox 7 - GPS/GNSS Receiver ({UBLOX_ID})"


def assigns(seen):
    return [p for p in seen if p["method"] == "device.assign"]


def open_assign(c, device_id):
    w = c.window
    w.show_panel("devices")
    assert w.devices.select_device(device_id)
    c.settle(50)
    dialog = w.devices._open_assign()
    assert dialog is not None, (w.devices.detail.device, w.devices.selected_id, c.controller.live, c.controller.role)
    return dialog


def choose(c, dialog, logical):
    dialog.radios[logical].setChecked(True)
    dialog.next.click()
    c.qtbot.waitUntil(lambda: dialog.stack.currentIndex() == 1 and dialog.effects is not None, timeout=3000)


def lines_of(dialog):
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in dialog.confirm_page.findChildren(QLabel)]


def test_60_assign_flow(p2env, console):
    core = p2env()
    seen = payload_spy(core)
    c = console(core.config.socket)
    c.sign_in("dragon")
    # displacing assign: every effect listed, Cancel is the default, Cancel sends nothing
    dialog = open_assign(c, CP2102_ID)
    choose(c, dialog, "gps.primary")
    text = lines_of(dialog)
    assert f"\u2022 gps.primary \u2192 CP2102 USB to UART Bridge Controller ({CP2102_ID})" in text
    assert "\u2022 " + DISPLACE_LINE in text
    assert "\u26a0 task-core will accept this, but this device is not classified for gps.position." in text
    assert dialog.assign.text() == "Assign and replace"
    assert dialog.cancel.isDefault() and not dialog.assign.isDefault()
    assert not dialog.assign.isEnabled()  # class-mismatch checkbox required
    dialog.cancel.click()
    c.settle(200)
    assert assigns(seen) == []
    # non-displacing: confirm_displace is not sent
    dialog = open_assign(c, SDR_ID)
    choose(c, dialog, "sdr.primary")
    assert dialog.radios["sdr.primary"].text() == "sdr.primary \u2014 matches device class"
    assert dialog.assign.text() == "Assign" and dialog.assign.isEnabled()
    dialog.alias.setText("sdr")
    dialog.assign.click()
    c.qtbot.waitUntil(lambda: gone(dialog), timeout=3000)
    assert assigns(seen)[-1]["params"] == {"logical": "sdr.primary", "device_id": SDR_ID, "alias": "sdr"}
    assert c.window.banner.text.text() == f"Assigned sdr.primary \u2192 Blog V4 ({SDR_ID})"
    # displacing with the checkbox: confirm_displace true, banner lists the displaced entry
    dialog = open_assign(c, CP2102_ID)
    choose(c, dialog, "gps.primary")
    dialog.checks[0].setChecked(True)
    assert dialog.assign.isEnabled()
    dialog.assign.click()
    c.qtbot.waitUntil(lambda: gone(dialog), timeout=3000)
    assert assigns(seen)[-1]["params"] == {"logical": "gps.primary", "device_id": CP2102_ID,
                                           "confirm_displace": True}
    assert c.window.banner.text.text() == (
        f"Assigned gps.primary \u2192 CP2102 USB to UART Bridge Controller ({CP2102_ID}); "
        f"gps.primary removed from u-blox 7 - GPS/GNSS Receiver ({UBLOX_ID})")
    # would-displace race: the state changes after the confirmation was built
    dialog = open_assign(c, UBLOX_ID)
    choose(c, dialog, "mesh.primary")
    assert dialog.assign.text() == "Assign" and not any("removed" in t for t in lines_of(dialog))
    dialog.checks[0].setChecked(True)  # u-blox is not classified for mesh.messaging
    other = V2Client(core.config.socket)
    token = login(core, "dragon", client=other)
    assert other.call("device.assign", {"logical": "mesh.primary", "device_id": SDR_ID,
                                        "confirm_displace": True}, session=token)["ok"]
    count = len(assigns(seen))
    dialog.assign.click()
    c.qtbot.waitUntil(lambda: any("will be removed from Blog V4" in t for t in lines_of(dialog)), timeout=3000)
    assert len(assigns(seen)) == count + 1  # one attempt only; never retried with confirm_displace
    assert "confirm_displace" not in assigns(seen)[-1]["params"]
    assert any("The assignments changed after the confirmation was built." in t for t in lines_of(dialog))
    assert dialog.assign.text() == "Assign and replace" and dialog.cancel.isDefault()
    c.settle(300)
    assert len(assigns(seen)) == count + 1
    other.close()


def test_61_warnings_need_their_checkbox_and_shared_identity_note(p2env, console):
    core = p2env()
    core._fake.add(ch340())
    c = console(core.config.socket)
    c.sign_in("dragon")
    unstable = next(d for d in c.controller.devices["devices"] if d["vid"] == "1a86")
    assert unstable["identity_stable"] is False
    dialog = open_assign(c, unstable["id"])
    choose(c, dialog, "radio.primary")
    texts = lines_of(dialog)
    assert any(t.startswith("\u26a0 This device has no usable serial number.") for t in texts)
    assert any("not classified for radio.tx" in t for t in texts)
    assert len(dialog.checks) == 2 and not dialog.assign.isEnabled()
    dialog.checks[0].setChecked(True)
    assert not dialog.assign.isEnabled()
    dialog.checks[1].setChecked(True)
    assert dialog.assign.isEnabled()
    dialog.reject()
    detail = c.window.devices.detail
    for device_id in (CP2102_ID, SDR_ID, UBLOX_ID):  # 0001, 00000001, model-only by-id
        assert c.window.devices.select_device(device_id)
        c.settle(30)
        assert detail.shared.isVisible(), device_id
        assert detail.shared.text().startswith("Identical units of this model may share this id.")
    assert c.window.devices.select_device(unstable["id"])
    c.settle(30)
    assert detail.unstable.isVisible()


def test_69_forbidden_shows_message_calls_whoami_and_rerenders(p2env, console):
    core = p2env()
    seen = payload_spy(core)
    c = console(core.config.socket)
    c.sign_in("dragon")
    spied = core.handle_v2

    def inject(payload, uid):
        if payload.get("method") == "device.unassign":
            return ({"v": 2, "id": payload["id"], "ok": False,
                     "error": {"code": "forbidden", "message": "administrator required"}}, None)
        if payload.get("method") == "session.whoami":
            spied(payload, uid)
            return ({"v": 2, "id": payload["id"], "ok": True,
                     "result": {"role": "operator", "username": "dragon", "idle_timeout_s": 7200,
                                "expires_in_s": 43000}}, None)
        return spied(payload, uid)

    core.handle_v2 = inject
    c.window.show_panel("devices")
    dialog = c.window.devices._open_unassign("gps.primary")
    dialog.ok.click()
    c.qtbot.waitUntil(lambda: c.controller.role == "operator", timeout=3000)
    assert c.window.banner.text.text() == "task-core refused: administrator required"
    assert [p["method"] for p in seen][-1] == "session.whoami"
    assert c.window.strip.identity.text() == "dragon \u00b7 operator"
    assert not any(b.isVisible() for b in c.window.devices.slot_buttons.values())
    assert c.window.devices.role_note.text() == "Assigning devices requires an administrator."
    assert gone(dialog)
    assert sum(1 for p in seen if p["method"] == "device.unassign") == 0  # injected before the spy; never retried


def key(widget, k, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(widget, k, modifier)


def focus():
    return QApplication.focusWidget()


def tab_to(c, predicate, limit=80):
    for _ in range(limit):
        if predicate(focus()):
            return focus()
        target = focus() or c.window
        key(target, Qt.Key.Key_Tab)
    raise AssertionError(f"could not reach the widget with Tab (focus {focus()!r})")


def test_72_keyboard_only(p2env, console):
    core = p2env()
    seen = payload_spy(core)
    c = console(core.config.socket)
    w = c.window
    # every panel via the rail (F6 then arrows) and via shortcuts
    key(w, Qt.Key.Key_F6)
    if focus() is not w.rail:
        key(focus(), Qt.Key.Key_F6)
    assert focus() is w.rail
    key(w.rail, Qt.Key.Key_Down)
    assert w.current_panel_key() == "core"
    key(w.rail, Qt.Key.Key_Down)
    assert w.current_panel_key() == "devices"
    key(w, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert w.current_panel_key() == "home"
    key(w, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert w.current_panel_key() == "core"
    key(w, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    tile = tab_to(c, lambda f: f in w.home.tiles)
    key(tile, Qt.Key.Key_Right)
    key(focus(), Qt.Key.Key_Return)
    assert w.current_panel_key() == "module"
    key(focus(), Qt.Key.Key_Space)  # Back button has focus
    assert w.current_panel_key() == "home"
    # sign in
    key(w, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    c.qtbot.waitUntil(lambda: focus() is not None and focus().accessibleName() == "Username", timeout=2000)
    QTest.keyClicks(focus(), "dragon")
    key(focus(), Qt.Key.Key_Tab)
    assert focus().accessibleName() == "Password"
    QTest.keyClicks(focus(), DRAGON_PW)
    key(focus(), Qt.Key.Key_Return)
    c.qtbot.waitUntil(lambda: c.controller.role == "administrator" and c.controller.devices is not None,
                      timeout=3000)
    c.settle(200)
    w.activateWindow()
    c.qtbot.waitUntil(w.isActiveWindow, timeout=2000)
    # assign with displacement confirmation (CP2102 -> gps.primary)
    key(w, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    table = w.devices.table
    tab_to(c, lambda f: f is table)
    for _ in range(4):
        if w.devices.detail.device and w.devices.detail.device["id"] == CP2102_ID:
            break
        key(table, Qt.Key.Key_Down)
    if not (w.devices.detail.device and w.devices.detail.device["id"] == CP2102_ID):
        for _ in range(4):
            key(table, Qt.Key.Key_Up)
            if w.devices.detail.device and w.devices.detail.device["id"] == CP2102_ID:
                break
    assert w.devices.detail.device["id"] == CP2102_ID
    tab_to(c, lambda f: f is w.devices.detail.assign)
    key(focus(), Qt.Key.Key_Space)
    c.qtbot.waitUntil(lambda: focus() is not None and focus().window() is not w, timeout=2000)
    dialog = focus().window()
    assert dialog.radios["gps.primary"].isChecked()
    key(focus(), Qt.Key.Key_Return)  # Continue is the default on the first step
    c.qtbot.waitUntil(lambda: dialog.stack.currentIndex() == 1, timeout=3000)
    assert focus() is dialog.cancel and dialog.cancel.isDefault()
    check = tab_to(c, lambda f: isinstance(f, QCheckBox))
    key(check, Qt.Key.Key_Space)
    assert check.isChecked()
    tab_to(c, lambda f: f is dialog.assign)
    key(focus(), Qt.Key.Key_Space)
    c.qtbot.waitUntil(lambda: gone(dialog), timeout=3000)
    c.qtbot.waitUntil(lambda: (c.controller.devices["assignments"].get("gps.primary") or {}).get("device_id")
                      == CP2102_ID, timeout=3000)
    w.activateWindow()
    c.qtbot.waitUntil(w.isActiveWindow, timeout=2000)
    # unassign: Enter on the confirmation cancels (Cancel is the default); then confirm with Tab + Space
    button = w.devices.slot_buttons["gps.primary"]
    tab_to(c, lambda f: f is button)
    key(button, Qt.Key.Key_Space)
    c.qtbot.waitUntil(lambda: focus() is not None and focus().window() is not w, timeout=2000)
    dialog = focus().window()
    assert focus() is dialog.cancel
    key(focus(), Qt.Key.Key_Return)
    c.qtbot.waitUntil(lambda: gone(dialog), timeout=2000)
    assert not [p for p in seen if p["method"] == "device.unassign"]
    w.activateWindow()
    c.qtbot.waitUntil(w.isActiveWindow, timeout=2000)
    tab_to(c, lambda f: f is button)
    key(button, Qt.Key.Key_Space)
    c.qtbot.waitUntil(lambda: focus() is not None and focus().window() is not w, timeout=2000)
    dialog = focus().window()
    tab_to(c, lambda f: f is dialog.ok)
    key(focus(), Qt.Key.Key_Space)
    c.qtbot.waitUntil(lambda: gone(dialog), timeout=3000)
    assert [p["params"] for p in seen if p["method"] == "device.unassign"] == [{"logical": "gps.primary"}]
    w.activateWindow()
    c.qtbot.waitUntil(w.isActiveWindow, timeout=2000)
    # lock and unlock
    key(w, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert c.controller.locked and focus() is w.overlay.sign_in
    key(focus(), Qt.Key.Key_Space)
    c.qtbot.waitUntil(lambda: focus() is not None and focus().accessibleName() == "Username", timeout=2000)
    QTest.keyClicks(focus(), "dragon")
    key(focus(), Qt.Key.Key_Tab)
    QTest.keyClicks(focus(), DRAGON_PW)
    key(focus(), Qt.Key.Key_Return)
    c.qtbot.waitUntil(lambda: c.controller.role == "administrator" and not c.controller.locked, timeout=3000)
    assert not w.overlay.isVisible()
