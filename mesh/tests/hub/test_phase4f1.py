# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F.1 acceptance A01–A20 (mocked transports; no RF, no real radio, no real desktop)."""
import json
import logging
import os
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from task_comms.notifications import NotificationStore
from task_mesh.hub.devices import Assignments
from task_mesh.hub.engine import Hub, SendRefused
from task_mesh.hub.ipc import HubClient, HubSubscriber, IpcServer
from task_mesh.hub.model import LIVE, HubMessage, dedupe_key
from task_mesh.hub.notifier import EXPIRE_MS, TITLE, NotificationManager, NotifySettings, format_notification
from task_mesh.hub.store import HubStore

SECRET = "rendezvous grid 18T 0583"


def msg(proto="meshcore", sender="cafe00112233", conv="dm:cafe00112233", text="hi", key=None, ts=None):
    return HubMessage(protocol=proto, device="d0", key=key or dedupe_key(proto, sender, text, ts or time.time()),
                      direction="in", kind="dm" if conv.startswith("dm:") else "channel", conversation=conv,
                      sender=sender, sender_label="Alice", text=text, ts=ts or time.time(), origin=LIVE)


class Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, args, replaces_id=0):
        self.calls.append((args, replaces_id))
        return 100 + len(self.calls) if replaces_id == 0 else replaces_id


class FakeAdapter:
    def __init__(self, protocol, key):
        self.protocol, self.key, self.sent = protocol, key, []

    def send_text(self, conv, text):
        self.sent.append((conv, text))
        return "sent"

    def start(self):
        pass

    def stop(self, timeout=1):
        pass


@pytest.fixture
def hub(tmp_path):
    s = Sender()
    h = Hub(HubStore(tmp_path / "hub.sqlite3"), NotificationStore(tmp_path / "n.sqlite"),
            Assignments(tmp_path / "rp.json"), {}, "service", sender=s, scan=lambda: {},
            session_role=lambda t: {"op": "operator"}.get(t))
    h.sender = s
    yield h
    h.shutdown()


@pytest.fixture
def served(hub, tmp_path):
    path = tmp_path / "mesh.sock"
    srv = IpcServer(hub.api, path, on_close=hub.drop_client)
    hub.listeners.append(srv.publish)
    srv.start()
    yield hub, srv, path
    srv.stop()


def wait(cond, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ---- IPC / service-client ---------------------------------------------------------------------------
def test_A01_client_cannot_spoof_server_only_params(served):
    hub, srv, path = served
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(path))
    try:
        s.sendall(b'{"id": 1, "method": "focus", "params": {"focused": true, "ttl": 5, "_conn": "victim"}}\n')
        reply = json.loads(s.makefile("rb").readline())
        assert reply["ok"] and reply["result"]["focused"] is True
        assert "victim" not in hub._focus and len(hub._focus) == 1     # lease keyed by the real connection id
    finally:
        s.close()
    assert wait(lambda: not hub._focus)


def test_A02_subscription_streams_live_messages(served):
    hub, srv, path = served
    got = []
    sub = HubSubscriber(lambda k, d: got.append((k, d)), path)
    sub.start()
    try:
        assert wait(lambda: srv.subscribers() == 1)
        hub.on_message(msg(key="live1", text=SECRET))
        assert wait(lambda: any(k == "message" for k, _ in got))
        ev = [d for k, d in got if k == "message"][0]
        assert ev["protocol"] == "meshcore" and SECRET not in json.dumps(ev)   # events carry ids/counts, no content
    finally:
        sub.stop()


def test_A03_subscriber_survives_service_restart(hub, tmp_path):
    path = tmp_path / "mesh.sock"
    srv = IpcServer(hub.api, path, on_close=hub.drop_client)
    srv.start()
    got = []
    sub = HubSubscriber(lambda k, d: got.append(k), path)
    sub.start()
    try:
        assert wait(lambda: "_connected" in got)
        srv.stop()
        assert wait(lambda: "_disconnected" in got)
        srv2 = IpcServer(hub.api, path, on_close=hub.drop_client)
        srv2.start()
        assert wait(lambda: got.count("_connected") >= 2, 8)
        srv2.stop()
    finally:
        sub.stop()


def test_A04_service_send_needs_explicit_click_and_session_and_keeps_protocols_apart(served):
    hub, srv, path = served
    mc, mt = FakeAdapter("meshcore", "mc0"), FakeAdapter("meshtastic", "mt0")
    hub.devices.adapters.update({"mc0": mc, "mt0": mt})
    c = HubClient(path)
    for kw in ({"session": "op"}, {"explicit_user_action": True}, {"explicit_user_action": True, "session": "bad"}):
        with pytest.raises(Exception):
            c.call("send", protocol="meshcore", conversation="dm:cafe", text="x", **kw)
    c.call("send", protocol="meshcore", conversation="dm:cafe", text="reply", explicit_user_action=True, session="op")
    assert mc.sent == [("dm:cafe", "reply")] and mt.sent == []


def test_A05_gui_close_does_not_affect_reception(served):
    hub, srv, path = served
    sub = HubSubscriber(lambda k, d: None, path)
    sub.start()
    assert wait(lambda: sub.connected.is_set())
    sub.focus(True)
    sub.stop()                                       # window closed
    hub.on_message(msg(key="after-close"))
    assert hub.store.unread()["total"] == 1 and len(hub.sender.calls) == 1


# ---- notifications --------------------------------------------------------------------------------------
def test_A06_title_body_privacy_and_expiry():
    m = msg(text=SECRET)
    allowed = format_notification(m, NotifySettings(show_preview=True), locked=False)
    assert allowed["summary"] == TITLE and allowed["expire_timeout"] == EXPIRE_MS == 5000
    assert "MeshCore" in allowed["body"] and "Alice" in allowed["body"] and SECRET in allowed["body"]
    default = format_notification(m, NotifySettings(), locked=False)
    assert SECRET not in default["body"] and "MeshCore" in default["body"]
    locked = format_notification(m, NotifySettings(show_preview=True), locked=True)
    assert locked["summary"] == TITLE and SECRET not in json.dumps(locked) and "Alice" not in json.dumps(locked) \
        and "MeshCore" not in json.dumps(locked)
    assert allowed["actions"] == ["default", "Open"]


def test_A07_mute_and_quiet_hours_suppress_popups_only(hub):
    hub.notifier.settings.muted_conversations = {"meshcore|ch:1"}
    hub.on_message(msg(conv="ch:1", sender="", key="m1"))
    hub.notifier.settings.muted_conversations = set()
    hub.notifier.settings.quiet_hours = "00:00-23:59"
    hub.on_message(msg(key="m2"))
    assert hub.sender.calls == [] and hub.store.unread()["total"] == 2


def test_A08_bursts_are_grouped(tmp_path):
    s = Sender()
    t = [1000.0]
    nm = NotificationManager(NotificationStore(tmp_path / "n.sqlite"), s, clock=lambda: t[0])
    for i in range(6):
        nm.handle(msg(key=f"b{i}", conv=f"dm:{i:012x}", sender=f"{i:012x}"))
        t[0] += 1
    grouped = [c for c in s.calls if "new mesh messages" in c[0]["body"]]
    assert len(s.calls) == 6 and len(grouped) == 4
    assert len({c[1] for c in grouped[1:]}) == 1 and grouped[1][1] != 0       # one grouped popup, replaced in place
    assert "6 new mesh messages" in grouped[-1][0]["body"]


def test_A09_dedupe_across_reconnect(hub):
    m1 = msg(key="same-packet")
    hub.on_message(m1)
    hub.on_message(msg(key="same-packet"))           # re-delivered after the radio reconnected
    assert len(hub.sender.calls) == 1 and hub.store.unread()["total"] == 1


# ---- focus rule ---------------------------------------------------------------------------------------
def test_A10_focused_window_suppresses_popups_without_marking_read(hub):
    hub.set_focus("w1", True, 15)
    hub.on_message(msg(key="f1"))
    assert hub.sender.calls == [] and hub.store.unread()["total"] == 1
    hub.set_focus("w1", False)
    hub.on_message(msg(key="f2"))
    assert len(hub.sender.calls) == 1


def test_A11_focus_lease_expires(hub):
    hub.set_focus("w1", True, 1)
    assert hub.gui_focused()
    time.sleep(1.1)
    assert not hub.gui_focused()                     # crashed/hung window: stale lease ignored
    hub.on_message(msg(key="e1"))
    assert len(hub.sender.calls) == 1


def test_A12_lease_dropped_when_window_socket_closes(served):
    hub, srv, path = served
    sub = HubSubscriber(lambda k, d: None, path)
    sub.start()
    assert wait(lambda: sub.connected.is_set())
    sub.focus(True, 15)
    assert wait(lambda: hub.gui_focused())
    sub.stop()
    assert wait(lambda: not hub.gui_focused())


def test_A13_multiple_windows_and_rapid_toggles(hub):
    hub.set_focus("a", True)
    hub.set_focus("b", False)
    assert hub.gui_focused()
    for i in range(50):
        hub.set_focus("a", i % 2 == 0)
    assert not hub.gui_focused()                     # last toggle (i=49) was unfocused
    hub.set_focus("b", True)
    hub.set_focus("a", True)
    hub.drop_client("a")
    assert hub.gui_focused()
    assert hub.set_focus("x", True, ttl=10_000) and hub._focus["x"] - time.monotonic() <= hub.FOCUS_TTL_MAX


# ---- click action ---------------------------------------------------------------------------------------
def test_A14_click_opens_conversation_by_internal_id_only(hub):
    events, opened = [], []
    hub.listeners.append(lambda k, d: events.append((k, d)))
    hub.opener = lambda ref: opened.append(ref) or True
    hub.on_message(msg(key="c1", text="$(rm -rf ~) ; open me"))
    nid = hub.sender.calls[-1][1] or 101
    nid = list(hub.notifier.refs)[0]
    hub.on_notification_action(nid, "default")
    ref = opened[0]
    assert set(ref) == {"id", "protocol", "conversation"} and isinstance(ref["id"], int)
    assert "rm -rf" not in json.dumps(ref)
    hub.on_notification_action(999999, "default")    # unknown id: ignored
    hub.on_notification_action(nid, "evil-action")   # unknown action: ignored
    assert len(opened) == 1 and [k for k, _ in events].count("open") == 1


def test_A15_launch_gui_uses_argv_and_needs_display(monkeypatch):
    import task_mesh.service as svc
    calls = []
    monkeypatch.setattr(svc.os.path, "exists", lambda p: True)
    monkeypatch.setattr("subprocess.Popen", lambda argv, **kw: calls.append((argv, kw)))
    assert svc.launch_gui(42, env={"PATH": "/usr/bin"}) is False and calls == []
    assert svc.launch_gui(42, env={"DISPLAY": ":0"}) is True
    argv, kw = calls[0]
    assert argv == ["/usr/bin/task-mesh", "--open-message", "42"] and "shell" not in kw
    with pytest.raises((TypeError, ValueError)):
        svc.launch_gui("42; reboot", env={"DISPLAY": ":0"})


def test_A16_service_opener_prefers_attached_window(served, monkeypatch):
    """run() wiring: a subscribed window gets the event; the launcher is only used with no window."""
    hub, srv, path = served
    launched = []
    hub.opener = lambda ref: True if srv.subscribers() else launched.append(ref["id"])
    sub = HubSubscriber(lambda k, d: None, path)
    sub.start()
    assert wait(lambda: srv.subscribers() == 1)
    hub.on_message(msg(key="o1"))
    hub.on_notification_action(list(hub.notifier.refs)[0], "default")
    assert launched == []
    sub.stop()
    assert wait(lambda: srv.subscribers() == 0)
    hub.on_notification_action(list(hub.notifier.refs)[0], "default")
    assert len(launched) == 1


def test_A17_jeepney_sender_notify_args_and_action_signal():
    pytest.importorskip("jeepney")
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        pytest.skip("no session bus")
    from jeepney import MessageType, new_method_return, new_signal
    from jeepney import DBusAddress
    from jeepney.bus_messages import message_bus
    from jeepney.io.blocking import open_dbus_connection
    from task_mesh.hub.notifier import JeepneySender
    got, ready, done = [], threading.Event(), threading.Event()

    def server():
        conn = open_dbus_connection(bus="SESSION")
        conn.send_and_get_reply(message_bus.RequestName("org.freedesktop.Notifications"))
        ready.set()
        end = time.time() + 10
        while time.time() < end and not done.is_set():
            try:
                m = conn.receive(timeout=0.3)
            except TimeoutError:
                continue
            if m.header.message_type == MessageType.method_call and m.header.fields.get(3) == "Notify":
                got.append(m.body)
                conn.send(new_method_return(m, "u", (7,)))
                a = DBusAddress("/org/freedesktop/Notifications", interface="org.freedesktop.Notifications")
                conn.send(new_signal(a, "ActionInvoked", "us", (7, "default")))
        conn.close()
    t = threading.Thread(target=server, daemon=True)
    t.start()
    assert ready.wait(5)
    actions = []
    js = JeepneySender(on_action=lambda nid, act: actions.append((nid, act)))
    args = format_notification(msg(), NotifySettings(), locked=True)
    assert js(args) == 7
    assert wait(lambda: actions, 5)
    done.set()
    js.close()
    body = got[0]
    assert body[3] == TITLE and body[5] == ["default", "Open"] and body[7] == 5000
    assert actions == [(7, "default")]


# ---- opt-in setup + logs ------------------------------------------------------------------------------
def test_A18_notify_setup_is_opt_in_and_reversible(tmp_path, monkeypatch, capsys):
    from task_mesh import notify_setup as ns
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(ns, "DAEMON", "/bin/true")
    monkeypatch.setattr(ns, "UPDATE_ENV", "/bin/true")
    monkeypatch.setattr(ns, "SYSTEM_DIRS", (str(tmp_path / "sys"),))
    ns.check()
    assert not (tmp_path / "data").exists() and not (tmp_path / "cfg").exists()     # check writes nothing
    assert ns.enable() == 0
    sf, af = ns.user_service_file(), ns.autostart_file()
    assert "Exec=/bin/true\n" in sf.read_text() and "Name=org.freedesktop.Notifications" in sf.read_text()
    assert "--systemd DISPLAY XAUTHORITY" in af.read_text()
    assert ns.disable() == 0 and not sf.exists() and not af.exists()
    (tmp_path / "sys").mkdir()
    (tmp_path / "sys/org.freedesktop.Notifications.service").write_text("[D-BUS Service]\nName=org.freedesktop.Notifications\n")
    ns.enable()
    assert not ns.user_service_file().exists()                                 # never a second provider
    af.write_text("[Desktop Entry]\n# someone else's\n")
    ns.disable()
    assert af.exists()                                                         # only our marked files removed


def test_A19_no_private_content_in_logs(served, caplog):
    hub, srv, path = served
    caplog.set_level(logging.DEBUG)
    hub.devices.adapters["mc0"] = FakeAdapter("meshcore", "mc0")
    c = HubClient(path)
    c.call("auth", session="op")
    hub.on_message(msg(key="lg", text=SECRET))
    c.call("send", protocol="meshcore", conversation="dm:cafe", text=SECRET, explicit_user_action=True, session="op")
    c.call("focus", focused=True)
    text = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert SECRET not in text and "'op'" not in text


def test_A20_ipc_socket_private_and_peer_checked(served, monkeypatch):
    import stat
    import task_mesh.hub.ipc as ipc
    hub, srv, path = served
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    monkeypatch.setattr(ipc, "peer_uid", lambda s: os.getuid() + 1)
    sub_events = []
    sub = HubSubscriber(lambda k, d: sub_events.append(k), path)
    sub.start()
    time.sleep(0.5)
    sub.stop()
    assert srv.subscribers() == 0 and not hub.gui_focused()
