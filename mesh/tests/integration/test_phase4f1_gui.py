# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""4F.1 GUI acceptance (G1–G5): service-client mode never opens a port; live switching; click-to-open."""
import time

from task_mesh.app import build_application
from task_mesh.hub.model import LIVE, HubMessage
import task_mesh.ui.hub_controller as hc


class FakeService:
    """Stands in for task-mesh-service: a real Hub behind a client-like call()."""
    def __init__(self, tmp_path):
        from task_comms.notifications import NotificationStore
        from task_mesh.hub.devices import Assignments
        from task_mesh.hub.engine import Hub
        from task_mesh.hub.store import HubStore
        self.hub = Hub(HubStore(tmp_path / "svc-hub.sqlite3"), NotificationStore(tmp_path / "svc-n.sqlite"),
                       Assignments(tmp_path / "svc-rp.json"), {}, "service", scan=lambda: {})
        self.running = True

    def call(self, method, **params):
        if not self.running:
            raise OSError("down")
        return self.hub.api(method, params)


class FakeSub:
    def __init__(self, cb):
        self.cb, self.focus_calls = cb, []

    def start(self):
        self.cb("_connected", {})

    def stop(self):
        pass

    def focus(self, f, ttl=15):
        self.focus_calls.append(f)
        return True


def _ctx(xdg, tmp_path, svc, opened):
    def provider_factory(cand):
        opened.append(cand)
        raise RuntimeError("test provider: must not be used in service mode")
    subs = []
    kw = {"service_running": lambda: svc.running, "client_factory": lambda: svc,
          "subscriber_factory": lambda cb: subs.append(FakeSub(cb)) or subs[-1], "sender": lambda a, r=0: None}
    ctx = build_application(env=xdg, discover=lambda: [], hotplug=None, console_log=False, hub_mode="auto",
                            hub_kwargs=kw, provider_factory=provider_factory)
    return ctx, subs


def test_G1_connect_click_with_service_running_never_opens_port(qtbot, xdg, tmp_path):
    svc, opened = FakeService(tmp_path), []
    ctx, subs = _ctx(xdg, tmp_path, svc, opened)
    try:
        ctl = ctx.window._hub[2]
        ctl.check()
        assert ctl.mode == "service"
        ctx.window.radio_panel.connect_clicked.emit()
        ctx.window.radio_panel.retry_clicked.emit()
        qtbot.wait(300)
        assert opened == [] and not ctx.window.radio_panel.isEnabled()
    finally:
        ctx.shutdown()


def test_G2_messages_from_service_appear_and_gui_does_not_write(qtbot, xdg, tmp_path):
    svc, opened = FakeService(tmp_path), []
    ctx, subs = _ctx(xdg, tmp_path, svc, opened)
    try:
        ctl = ctx.window._hub[2]
        ctl.check()
        svc.hub.on_message(HubMessage(protocol="meshtastic", device="mt0", key="k1", direction="in", kind="channel",
                                      conversation="ch:0", sender="!a1b2c3d4", sender_label="A", text="t", ts=1.0))
        subs[-1].cb("message", {"protocol": "meshtastic"})
        qtbot.wait(100)
        tabs = ctx.window._hub[1]
        assert tabs.mt_msgs.convs.count() == 1
        assert ctx.window._hub[0].local is None              # no local hub → no second writer in service mode
    finally:
        ctx.shutdown()


def test_G3_service_start_makes_direct_window_yield(qtbot, xdg, tmp_path):
    svc, opened = FakeService(tmp_path), []
    svc.running = False
    ctx, subs = _ctx(xdg, tmp_path, svc, opened)
    try:
        ctl = ctx.window._hub[2]
        assert ctl.mode == "direct" and ctx.window._hub[0].local is not None
        released = []
        ctx.window._hub[0].local.devices.shutdown = lambda: released.append(1)
        svc.running = True
        ctl.check()
        assert ctl.mode == "service" and released == [1]
    finally:
        ctx.shutdown()


def test_G4_service_restart_grace_then_direct_without_autoconnect(qtbot, xdg, tmp_path, monkeypatch):
    svc, opened = FakeService(tmp_path), []
    ctx, subs = _ctx(xdg, tmp_path, svc, opened)
    try:
        ctl = ctx.window._hub[2]
        t = [100.0]
        ctl.clock = lambda: t[0]
        svc.running = False
        ctl.check()
        t[0] += 5
        ctl.check()
        assert ctl.mode == "service"                         # restart window: keep waiting
        svc.running = True
        ctl.check()
        svc.running = False
        ctl.check()
        t[0] += hc.SERVICE_GONE_GRACE_S + 1
        ctl.check()
        assert ctl.mode == "direct" and ctx.window.radio_panel.isEnabled()
        qtbot.wait(200)
        assert opened == []                                  # no automatic connect after the switch
    finally:
        ctx.shutdown()


def test_G5_open_message_selects_conversation_and_focus_is_reported(qtbot, xdg, tmp_path):
    svc, opened = FakeService(tmp_path), []
    ctx, subs = _ctx(xdg, tmp_path, svc, opened)
    try:
        ctl = ctx.window._hub[2]
        ctl.check()
        rid = svc.hub.on_message(HubMessage(protocol="meshcore", device="mc0", key="k2", direction="in", kind="dm",
                                            conversation="dm:cafe00112233", sender="cafe00112233", sender_label="B",
                                            text="t", ts=1.0, origin=LIVE))
        assert ctl.open_message(rid)
        tabs = ctx.window._hub[1]
        assert ctx.window.tabs.currentIndex() == 2
        assert tabs.mc_msgs.current is not None and tuple(tabs.mc_msgs.current) == ("meshcore", "dm:cafe00112233")
        assert svc.hub.store.unread()["total"] == 1          # signed out: opening does not mark read
        assert subs[-1].focus_calls                          # lease reported over the window's own connection
        assert ctl.open_message(999999) is False
    finally:
        ctx.shutdown()
