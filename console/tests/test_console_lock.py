# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tests 64-67: core stop/start, lock with core reachable and unreachable, idle timers (D11). TEST DATA only."""

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from helpers import gone, payload_spy, ui_findings
from p2fixtures import CP2102_ID, DRAGON_PW, V2Client

DASH = "\u2014"
PRIVILEGED = {"device.list", "device.get", "device.assign", "device.unassign", "events.recent"}


def whoami(core, token):
    client = V2Client(core.config.socket)
    try:
        return client.call("session.whoami", session=token)
    finally:
        client.close()


def test_64_core_stop_restart_and_stream_only_loss(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    w = c.window
    c.sign_in("dragon")
    w.show_panel("devices")
    assert w.devices.select_device(CP2102_ID)
    c.settle(50)
    base, state = core._base, core.config.state_dir
    old_boot = c.controller.boot_id
    core.close()
    c.qtbot.waitUntil(lambda: c.controller.link == "offline", timeout=3000)
    d = w.devices
    assert d.counts.text() == f"Devices: {DASH} unavailable"
    assert d.detail.values["connected"].text() == f"{DASH} unavailable"
    assert d.detail.values["devnode"].text() == f"{DASH} unavailable"
    assert d.detail.values["id"].text() == CP2102_ID  # identity stays, marked stale
    assert d.detail.stale.isVisible() and d.detail.stale.text().startswith("stale since ")
    assert not d.detail.assign.isEnabled() and d.detail.unavailable.text() == "task-core unavailable"
    assert not d.slot_buttons["gps.primary"].isEnabled()
    statuses = {d.model.item(r, 3).text() for r in range(d.model.rowCount())}
    assert statuses == {f"{DASH} unavailable"}
    assert w.core.fields["Version"].text() == f"{DASH} unavailable"
    assert c.controller.client.has_token  # kept for a same-boot reconnect
    # restart: a new boot_id signs out with a message and reloads everything
    core2 = p2env(base=base, state_dir=state)
    seen = payload_spy(core2)
    c.controller.retry_now()
    c.qtbot.waitUntil(lambda: c.controller.live and c.controller.counts is not None, timeout=3000)
    c.settle(200)
    assert c.controller.boot_id != old_boot
    assert c.controller.role == "public" and not c.controller.client.has_token
    assert "task-core restarted \u2014 please sign in again" in [n.text for n in w.notifier.history]
    assert {"core.health", "module.list", "capability.list", "device.counts"} <= {p["method"] for p in seen}
    assert all("session" not in p for p in seen)
    assert d.pages.currentIndex() == 0
    # stream-only loss (same boot): resync via events.since, session kept
    c.sign_in("dragon")
    token = c.controller.client._token
    seen.clear()
    streams = list(core2.streams._streams)
    assert len(streams) == 1
    streams[0].close()
    c.qtbot.waitUntil(lambda: c.controller.link == "offline", timeout=3000)
    c.controller.retry_now()
    c.qtbot.waitUntil(lambda: c.controller.live and c.client.stream_active, timeout=3000)
    c.settle(200)
    since = [p for p in seen if p["method"] == "events.since"]
    assert len(since) == 1 and since[0]["session"] == token and since[0]["params"]["boot_id"] == c.controller.boot_id
    assert c.controller.role == "administrator"
    assert [s.role for s in core2.streams._streams] == ["administrator"]
    assert d.detail.values["connected"].text() in ("yes", DASH)


def _trigger(c, how):
    w = c.window
    if how == "ctrl+l":
        # typed into whatever console window has focus: here the open assign dialog
        target = QApplication.focusWidget() or QApplication.activeWindow() or w
        assert target.window() is not w
        QTest.keyClick(target, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    elif how == "button":
        w.strip.action.click()
    else:
        c.idle_clock.advance(600)
        assert w.idle.check() is True


@pytest.mark.parametrize("how", ["ctrl+l", "button", "idle"])
def test_65_lock_with_core_reachable(p2env, console, how):
    core = p2env()
    c = console(core.config.socket)
    w = c.window
    c.sign_in("dragon")
    w.show_panel("devices")
    assert w.devices.select_device(CP2102_ID)
    c.settle(50)
    dialog = w.devices._open_assign()
    dialog.activateWindow()
    c.qtbot.waitUntil(dialog.isActiveWindow, timeout=2000)
    old = c.client._token
    seen = payload_spy(core)
    late = []
    c.controller.fetch_devices(lambda result, reply: late.append(reply))  # (f) sent just before the lock
    _trigger(c, how)
    # (a) same event-loop turn: no token, controls hidden, dialog closed unsent, nothing identifying rendered
    assert c.controller.locked and not c.client.has_token
    assert w.overlay.isVisible() and w.overlay.state.text() == "\U0001f512 Locked \u2014 signed out"
    assert w.strip.identity.text() == "Public"
    assert gone(dialog)
    assert not w.devices.detail.assign.isVisible()
    assert not any(b.isVisible() for b in w.devices.slot_buttons.values())
    assert c.controller.devices is None and w.devices.model.rowCount() == 0
    assert ui_findings(w) == []
    assert ui_findings(w, visible_only=False) == []
    c.settle(400)
    # (b) exactly one logout with the old token; nothing else carries it; no privileged request
    carrying = [p for p in seen if p.get("session") == old]
    assert [p["method"] for p in carrying] == ["device.list", "session.logout"]  # device.list was sent pre-lock
    after = seen[[p["method"] for p in seen].index("session.logout"):]
    assert not [p for p in after if p["method"] in PRIVILEGED]
    assert all("session" not in p for p in after[1:])
    # (f) the response to the pre-lock request was discarded
    assert late == [] and c.controller.devices is None
    # (c) the old token is dead server-side
    assert whoami(core, old)["error"] == {"code": "unauthenticated", "message": "session invalid"}
    # (d) the session-bound stream was replaced by a public one
    c.qtbot.waitUntil(lambda: [s.role for s in core.streams._streams] == ["public"], timeout=2000)
    assert [s.session for s in core.streams._streams] == [None]
    # (e) unlock: continue as public gives public; a wrong password stays locked; the right one gives a new token
    signin = w.request_sign_in()
    signin.username.setText("dragon")
    signin.password.edit.setText("wrong password")
    signin.submit.click()
    c.qtbot.waitUntil(lambda: signin.message.text() == "task-core: invalid credentials", timeout=3000)
    assert c.controller.locked and c.controller.role == "public" and w.overlay.isVisible()
    signin.reject()
    w.overlay.public.click()
    assert not c.controller.locked and c.controller.role == "public" and not w.overlay.isVisible()
    c.controller.lock("again")
    c.sign_in("dragon")
    assert not c.controller.locked and c.controller.role == "administrator"
    assert c.client._token != old


def test_66_lock_with_core_unreachable(p2env, console):
    core = p2env()
    c = console(core.config.socket)
    c.sign_in("dragon")
    old = c.client._token
    boot = c.controller.boot_id
    sock = core.config.socket
    os.rename(sock, sock + ".away")  # unreachable, same Core and boot_id
    for stream in list(core.streams._streams):
        stream.close()
    c.qtbot.waitUntil(lambda: c.controller.link == "offline", timeout=3000)
    seen = payload_spy(core)
    QTest.keyClick(c.window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert c.controller.locked and not c.client.has_token and c.window.overlay.isVisible()
    c.settle(300)
    assert seen == []
    os.rename(sock + ".away", sock)
    c.controller.retry_now()
    c.qtbot.waitUntil(lambda: c.controller.live and c.client.stream_active, timeout=3000)
    c.settle(300)
    assert c.controller.boot_id == boot
    assert c.controller.role == "public" and c.controller.locked
    assert all(p.get("session") != old for p in seen)
    assert "session.logout" not in [p["method"] for p in seen]
    assert whoami(core, old)["ok"] is True  # not revoked: it was discarded locally only
    core._clock.advance(7201)
    assert whoami(core, old)["error"]["code"] == "unauthenticated"


def test_67_idle_timers(p2env, console, isolated_home):
    core = p2env(stream_check_interval=0.05)
    c = console(core.config.socket)
    w = c.window
    assert w.idle.limit_seconds == 600
    c.idle_clock.advance(599)
    assert w.idle.check() is False
    QTest.keyClick(w, Qt.Key.Key_Shift)  # input at 9 min 59 s resets the timer
    c.idle_clock.advance(599)
    assert w.idle.check() is False and not c.controller.locked
    c.idle_clock.advance(1)
    assert w.idle.check() is True and c.controller.locked
    c.controller.continue_public()
    # preference: 1-10, larger values clamp to 10
    from task_console.prefs import Prefs

    config = isolated_home / ".config" / "task-console" / "console.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    for value, expected in ((30, 10), (0, 1), (5, 5), (10, 10), ("x", 10)):
        config.write_text(f"idle_lock_minutes = {value if not isinstance(value, str) else repr(value)}\n")
        assert Prefs().idle_lock_minutes == expected
    w.idle.set_minutes(99)
    assert w.idle.limit_seconds == 600
    # runs while unfocused and while the core is offline
    w.clearFocus()
    core.close()
    c.qtbot.waitUntil(lambda: c.controller.link == "offline", timeout=3000)
    c.idle_clock.advance(600)
    assert w.idle.check() is True and c.controller.locked


@pytest.mark.parametrize("which", ["idle", "absolute"])
def test_67_core_expiry_first_shows_session_expired(p2env, console, which):
    core = p2env(stream_check_interval=0.05)
    c = console(core.config.socket)
    c.sign_in("op")
    if which == "idle":
        core._clock.advance(7201)
    else:
        for _ in range(6):
            core._clock.advance(7000)
            c.controller.reload()  # activity keeps the idle timer alive
            c.qtbot.waitUntil(lambda: not c.controller._devices_inflight, timeout=2000)
            c.settle(100)
            assert c.controller.role == "operator"
        core._clock.advance(1201)  # 43201 s after login
    c.qtbot.waitUntil(lambda: c.controller.role == "public", timeout=3000)
    assert "Session expired \u2014 please sign in again" in [n.text for n in c.window.notifier.history]
    assert not c.controller.locked and c.window.strip.identity.text() == "Public"
    assert c.controller.devices is None
