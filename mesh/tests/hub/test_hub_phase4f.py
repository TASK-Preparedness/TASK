# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4F hub tests: store, notifications, auth, IPC, locks, devices, probe, adapters (mocks + simulated
packets only; no hardware). Numbered T01..T24 to match docs/phase4f/TEST-MATRIX.md."""
import json
import logging
import os
import socket
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from task_comms.notifications import NotificationStore
from task_mesh.hub import probe
from task_mesh.hub.bridge import Bridge, BridgeDisabled
from task_mesh.hub.devices import Assignments, DeviceManager
from task_mesh.hub.engine import Hub, SendRefused
from task_mesh.hub.ipc import HubClient, IpcServer
from task_mesh.hub.locks import Busy, device_lock, instance_lock, service_running
from task_mesh.hub.model import LIVE, SYNC, HubMessage, dedupe_key
from task_mesh.hub.notifier import NotificationManager, NotifySettings
from task_mesh.hub.store import HubStore

SECRET_TEXT = "the eagle lands at 0400"


def msg(proto="meshtastic", sender="!a1b2c3d4", conv="dm:!a1b2c3d4", text="hello", origin=LIVE, key=None, **kw):
    return HubMessage(protocol=proto, device="dev0", key=key or dedupe_key(proto, sender, text, origin),
                      direction="in", kind="dm" if conv.startswith("dm:") else "channel", conversation=conv,
                      sender=sender, sender_label="Alice", text=text, ts=time.time(), origin=origin, **kw)


class Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, args, replaces_id=0):
        self.calls.append((args, replaces_id))
        return len(self.calls)


class FakeAdapter:
    protocol = "meshcore"

    def __init__(self, key="mc0"):
        self.key, self.sent = key, []

    def send_text(self, conv, text):
        self.sent.append((conv, text))
        return "sent"

    def start(self):
        pass

    def stop(self, timeout=1):
        pass


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir(mode=0o700)
    sender = Sender()
    roles = {"good-op": "operator", "viewer": "viewer"}
    h = Hub(HubStore(tmp_path / "hub.sqlite3"), NotificationStore(tmp_path / "n.sqlite"),
            Assignments(tmp_path / "radio-protocols.json"), {}, "test", notify_config=tmp_path / "notifications.json",
            sender=sender, scan=lambda: {}, session_role=lambda s: roles.get(s))
    h.sender = sender
    yield h
    h.shutdown()


# ---- store / unread ---------------------------------------------------------------------------------
def test_T01_store_is_0600_and_dedupes(tmp_path):
    s = HubStore(tmp_path / "hub.sqlite3")
    assert stat.S_IMODE(os.stat(tmp_path / "hub.sqlite3").st_mode) == 0o600
    m = msg(key="k1")
    assert s.add(m) is not None
    assert s.add(msg(key="k1")) is None            # same dedupe key -> ignored
    assert s.unread()["total"] == 1


def test_T02_history_sync_is_stored_but_not_unread(tmp_path):
    s = HubStore(tmp_path / "hub.sqlite3")
    s.add(msg(key="old", origin=SYNC))
    s.add(msg(key="new"))
    assert len(s.messages()) == 2
    assert s.unread()["total"] == 1


def test_T03_no_identity_merge_across_protocols(tmp_path):
    s = HubStore(tmp_path / "hub.sqlite3")
    s.add(msg("meshtastic", sender="!a1b2c3d4", conv="dm:alice", key="a"))
    s.add(msg("meshcore", sender="a1b2c3d4e5f6", conv="dm:alice", key="a"))   # same key + conv, other protocol
    convs = s.conversations()
    assert {(c["protocol"], c["conversation"]) for c in convs} == {("meshtastic", "dm:alice"), ("meshcore", "dm:alice")}
    assert s.mark_read("meshcore", "dm:alice") == 1
    u = s.unread()["by_protocol"]
    assert u["meshtastic"]["unread"] == 1 and u["meshcore"]["unread"] == 0


def test_T04_mark_read_only_explicit_and_unread_is_readonly(tmp_path):
    s = HubStore(tmp_path / "hub.sqlite3")
    s.add(msg(key="x"))
    for _ in range(3):
        s.unread()
        s.conversations()
        s.messages()
    assert s.unread()["total"] == 1


def test_T05_priority_only_from_metadata_or_rule_and_labelled(hub, tmp_path):
    hub.on_message(msg(key="plain", text="URGENT help now"))          # words alone never set priority
    assert hub.store.unread()["priority"] == 0
    hub.on_message(msg(key="bel", priority="alert", priority_source="protocol:meshtastic-bell"))
    from task_mesh.hub.engine import Rule
    hub.rules = [Rule(name="family", protocol="meshcore", senders={"cafe00112233"}, conversations=set())]
    m = msg("meshcore", sender="cafe00112233", conv="dm:cafe00112233", key="rule")
    hub.on_message(m)
    assert m.priority == "alert" and m.priority_source == "user-rule:family"
    rows = {r["key"]: r for r in hub.store.messages()}
    assert rows["bel"]["priority_source"] == "protocol:meshtastic-bell"
    assert rows["plain"]["priority"] is None
    assert hub.store.unread()["priority"] == 2


# ---- notifications --------------------------------------------------------------------------------
def test_T06_locked_or_unknown_shows_generic_notification(hub):
    assert hub._auth in ("unknown", "locked")
    hub.on_message(msg(key="g", text=SECRET_TEXT))
    args, _ = hub.sender.calls[-1]
    blob = json.dumps(args)
    assert "New Mesh Message" in blob and SECRET_TEXT not in blob and "Alice" not in blob
    assert hub.store.unread()["total"] == 1       # count kept


def test_T07_unlocked_preview_off_by_default_and_mute_rules(hub, tmp_path):
    hub.set_auth("good-op")
    assert hub._auth == "unlocked"
    hub.on_message(msg(key="p1", text=SECRET_TEXT))
    assert SECRET_TEXT not in json.dumps(hub.sender.calls[-1][0])       # preview off by default
    n = len(hub.sender.calls)
    hub.notifier.settings.muted_protocols = {"meshtastic"}
    hub.on_message(msg(key="p2"))
    hub.notifier.settings.muted_protocols = set()
    hub.notifier.settings.muted_conversations = {"meshcore|ch:0"}
    hub.on_message(msg("meshcore", sender="", conv="ch:0", key="p3"))
    assert len(hub.sender.calls) == n                                    # both muted
    assert hub.store.unread()["total"] == 3                              # still counted
    hub.notifier.settings.show_preview = True
    hub.on_message(msg(key="p4", text=SECRET_TEXT))
    assert SECRET_TEXT in json.dumps(hub.sender.calls[-1][0])


def test_T08_viewer_role_does_not_unlock(hub):
    assert hub.set_auth("viewer") != "unlocked"
    assert hub.set_auth("forged-token") != "unlocked"
    assert hub.set_auth(None) != "unlocked"


def test_T09_sync_and_duplicates_never_pop_up(hub):
    hub.on_message(msg(key="h", origin=SYNC))
    hub.on_message(msg(key="d"))
    hub.on_message(msg(key="d"))
    assert len(hub.sender.calls) == 1


def test_T10_sound_hint_follows_setting(tmp_path):
    def hints(sound):
        snd = Sender()
        nm = NotificationManager(NotificationStore(tmp_path / f"{sound}.sqlite"), snd, NotifySettings(sound=sound))
        nm.handle(msg(key=f"s{sound}"))
        return json.dumps(snd.calls[-1][0])
    assert "suppress-sound" in hints(False)
    assert "suppress-sound\": true" not in hints(True).replace(" ", "")


def test_T11_jeepney_notify_on_real_session_bus():
    """Runs under dbus-run-session: a fake org.freedesktop.Notifications server receives a typed Notify."""
    pytest.importorskip("jeepney")
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        pytest.skip("no session bus")
    from jeepney import new_method_return
    from jeepney.bus_messages import message_bus
    from jeepney.io.blocking import open_dbus_connection
    from task_mesh.hub.notifier import JeepneySender
    got, ready = [], threading.Event()

    def server():
        conn = open_dbus_connection(bus="SESSION")
        conn.send_and_get_reply(message_bus.RequestName("org.freedesktop.Notifications"))
        ready.set()
        deadline = time.time() + 10
        while time.time() < deadline and not got:
            try:
                m = conn.receive(timeout=0.5)
            except TimeoutError:
                continue
            if m.header.fields.get(3) == "Notify":
                got.append(m.body)
                conn.send(new_method_return(m, "u", (42,)))
            elif m.header.fields.get(3) == "GetServerInformation":
                conn.send(new_method_return(m, "ssss", ("fake", "test", "1", "1.2")))
        conn.close()
    t = threading.Thread(target=server, daemon=True)
    t.start()
    assert ready.wait(5)
    js = JeepneySender()
    nid = js({"app_name": "T.A.S.K. Mesh", "summary": "New Mesh Message", "body": "", "hints": {}, "timeout": 5000})
    t.join(10)
    assert nid == 42 and got and got[0][3] == "New Mesh Message"


# ---- auth / send -------------------------------------------------------------------------------------
def test_T12_send_needs_explicit_action_and_operator_session(hub):
    ad = FakeAdapter()
    hub.devices.adapters["mc0"] = ad
    for kw in ({"explicit_user_action": False, "session": "good-op"},
               {"explicit_user_action": True, "session": None},
               {"explicit_user_action": True, "session": "viewer"},
               {"explicit_user_action": "yes", "session": "good-op"}):
        with pytest.raises(SendRefused):
            hub.send("meshcore", "dm:cafe", "hi", **kw)
    assert ad.sent == []
    with pytest.raises(SendRefused):
        hub.send("meshcore", "dm:cafe", "x" * 151, explicit_user_action=True, session="good-op")
    hub.send("meshcore", "dm:cafe", "hi", explicit_user_action=True, session="good-op")
    assert ad.sent == [("dm:cafe", "hi")]
    assert hub.store.unread()["total"] == 0     # own message never unread


def test_T13_api_send_without_flag_is_refused(hub):
    hub.devices.adapters["mc0"] = ad = FakeAdapter()
    with pytest.raises(Exception):
        hub.api("send", {"protocol": "meshcore", "conversation": "dm:cafe", "text": "hi", "session": "good-op"})
    assert ad.sent == []


def test_T14_no_secrets_or_message_text_in_logs(hub, caplog):
    caplog.set_level(logging.DEBUG)
    hub.set_auth("good-op")
    hub.on_message(msg(key="l", text=SECRET_TEXT))
    hub.devices.adapters["mc0"] = FakeAdapter()
    hub.send("meshcore", "dm:cafe", SECRET_TEXT, explicit_user_action=True, session="good-op")
    text = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert SECRET_TEXT not in text and "good-op" not in text


# ---- IPC / instance / locks -----------------------------------------------------------------------
def test_T15_ipc_socket_0600_and_roundtrip(hub, tmp_path):
    srv = IpcServer(hub.api, tmp_path / "run" / "mesh.sock")
    srv.start()
    try:
        assert stat.S_IMODE(os.stat(srv.path).st_mode) == 0o600
        c = HubClient(srv.path, timeout=2)
        assert c.available()
        hub.on_message(msg(key="ipc"))
        assert c.call("unread")["total"] == 1
        assert c.call("unread")["total"] == 1          # badge read is read-only
    finally:
        srv.stop()


def test_T16_ipc_rejects_other_uid(hub, tmp_path, monkeypatch):
    import task_mesh.hub.ipc as ipc
    monkeypatch.setattr(ipc, "peer_uid", lambda s: os.getuid() + 1)
    srv = IpcServer(hub.api, tmp_path / "run" / "mesh.sock")
    srv.start()
    try:
        with pytest.raises(Exception):
            HubClient(srv.path, timeout=1).call("unread")
    finally:
        srv.stop()


def test_T17_single_instance_lock(tmp_path):
    env = {"XDG_RUNTIME_DIR": str(tmp_path)}
    a = instance_lock(env).acquire()
    assert service_running(env)
    with pytest.raises(Busy):
        instance_lock(env).acquire()
    a.release()
    assert not service_running(env)


def test_T18_device_lock_gui_vs_service(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    s = device_lock("/dev/serial/by-id/usb-X-if00", "service").acquire()
    with pytest.raises(Busy) as e:
        device_lock("/dev/serial/by-id/usb-X-if00", "gui").acquire()
    assert "service" in e.value.owner
    s.release()
    device_lock("/dev/serial/by-id/usb-X-if00", "gui").acquire().release()


def test_T19_gui_locking_provider_never_opens_busy_port(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    from task_mesh.radio.locking import LockingProvider
    opened = []
    inner = SimpleNamespace(connect=lambda c, g: opened.append(c), close=lambda: None, shutdown=lambda: None)
    held = device_lock("/dev/ttyACM0", "service").acquire()
    lp = LockingProvider(inner)
    with pytest.raises(Exception):
        lp.connect(SimpleNamespace(path="/dev/ttyACM0", device="/dev/ttyACM0"), 1)
    assert opened == []
    held.release()


# ---- devices / probe --------------------------------------------------------------------------------
def test_T20_unassigned_and_ignored_ports_are_never_opened(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    started = []
    asg = Assignments(tmp_path / "a.json")
    asg.set("usb-B", "ignore")
    sink = SimpleNamespace(on_device=lambda st: None)
    dm = DeviceManager(asg, {"meshcore": lambda path, key, sink: started.append(path) or FakeAdapter(key)}, sink, "test",
                       scan=lambda: {"usb-A": "/dev/a", "usb-B": "/dev/b"})
    dm.poll()
    assert started == [] and {s.state for s in dm.status.values()} == {"unassigned", "ignored"}
    assert stat.S_IMODE(os.stat(tmp_path / "a.json").st_mode) == 0o600
    asg.set("usb-A", "meshcore")
    dm.poll()
    assert started == ["/dev/a"]
    dm.shutdown()


def test_T21_probe_writes_only_allowed_frames_and_want_config_matches_protobuf():
    from meshtastic.protobuf import mesh_pb2
    tr = mesh_pb2.ToRadio(want_config_id=int.from_bytes(probe.MT_WANT_CONFIG[-5:], "little") and 0)
    body = probe.MT_WANT_CONFIG[8:]
    parsed = mesh_pb2.ToRadio()
    parsed.ParseFromString(body)
    assert parsed.WhichOneof("payload_variant") == "want_config_id"
    assert int.from_bytes(probe.MT_WANT_CONFIG[6:8], "big") == len(body)
    assert tr is not None

    class Port:
        def __init__(self):
            self.writes = []

        def read(self, n):
            return b""

        def write(self, b):
            self.writes.append(bytes(b))
            return len(b)

        def reset_input_buffer(self):
            pass

        def close(self):
            pass
    p = Port()
    t = [0.0]

    def clock():
        t[0] += 0.5
        return t[0]
    assert probe.probe_port(lambda: p, clock=clock) == (None, "no-answer")
    assert p.writes and all(w in probe.ALLOWED_WRITES for w in p.writes)


# ---- adapters (simulated) ---------------------------------------------------------------------------
class Sink:
    def __init__(self):
        self.msgs, self.nodes, self.st = [], [], []

    def on_message(self, m):
        self.msgs.append(m)

    def on_node(self, n):
        self.nodes.append(n)

    def on_adapter_status(self, k, **f):
        self.st.append(f)


def wait(cond, t=8.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_T22_meshcore_sync_vs_live_no_tx_and_no_ble_pin():
    from tests.fakes.fake_meshcore import SimCompanion, chan_v3, dm_v3, sim_connect_factory
    from task_mesh.protocols.meshcore.adapter import COMMANDS_USED, MeshCoreAdapter
    sim = SimCompanion(queued=[dm_v3("a1b2c3d4e5f6", "queued", 100), chan_v3(0, "Bob: old", 101)])
    sk = Sink()
    a = MeshCoreAdapter("/dev/sim", "sim0", sk, connect=sim_connect_factory([sim]))
    a.start()
    try:
        assert a.connected.wait(10)
        assert wait(lambda: len(sk.msgs) >= 2)
        assert {m.origin for m in sk.msgs[:2]} == {SYNC}
        ch = [m for m in sk.msgs if m.kind == "channel"][0]
        assert ch.sender == "" and "claimed" in ch.sender_label.lower()     # unauthenticated channel name
        a.loop.call_soon_threadsafe(sim.push_waiting, dm_v3("a1b2c3d4e5f6", "live", 102))
        assert wait(lambda: any(m.text == "live" for m in sk.msgs))
        assert [m.origin for m in sk.msgs if m.text == "live"] == [LIVE]
        assert not any(w[0] in (0x02, 0x03) for w in sim.writes)            # no TX without explicit send
        assert "123456" not in json.dumps([str(s) for s in sk.st])         # BLE PIN dropped
        assert "send_msg" in COMMANDS_USED
    finally:
        a.stop()


def test_T23_meshcore_reconnects_after_drop():
    from tests.fakes.fake_meshcore import SimCompanion, sim_connect_factory
    from task_mesh.protocols.meshcore.adapter import MeshCoreAdapter
    s1, s2 = SimCompanion(), SimCompanion()
    sk = Sink()
    a = MeshCoreAdapter("/dev/sim", "sim0", sk, connect=sim_connect_factory([s1, s2]), backoff=(0.1,))
    a.start()
    try:
        assert a.connected.wait(10)
        a.loop.call_soon_threadsafe(s1.drop)
        assert wait(lambda: s2.open, 10)
    finally:
        a.stop()


def test_T24_meshtastic_text_to_hub_sync_rule_and_bell_priority():
    from task_mesh.protocols.meshtastic_adapter import text_to_hub
    t = SimpleNamespace(from_num=0xA1B2C3D4, to_num=0xFFFFFFFF, channel=0, text="\x07help", rx_time=1000,
                        is_direct=False, packet_id=7, snr=5.0, rssi=-90, hops=1, priority=None)
    live = text_to_hub(t, "d", clock=1100, session_start=1050)
    assert live.origin == LIVE and live.priority == "alert" and live.priority_source.startswith("protocol:")
    t.rx_time = 100
    assert text_to_hub(t, "d", clock=1100, session_start=1050).origin == SYNC


def test_T25_bridge_is_a_disabled_stub():
    with pytest.raises(BridgeDisabled):
        Bridge().forward(msg(), "meshcore")


def test_T26_restart_keeps_history_and_unread(tmp_path):
    s = HubStore(tmp_path / "hub.sqlite3")
    s.add(msg(key="r1"))
    s.close()
    s2 = HubStore(tmp_path / "hub.sqlite3")
    assert s2.unread()["total"] == 1 and len(s2.messages()) == 1


def test_T29_quiet_mode_and_quiet_hours_suppress_popups_not_counts(hub):
    hub.notifier.settings.quiet = True
    hub.on_message(msg(key="q1"))
    assert hub.sender.calls == [] and hub.store.unread()["total"] == 1
    s = NotifySettings(quiet_hours="00:00-23:59")
    assert s.is_quiet(time.mktime((2026, 10, 13, 12, 0, 0, 0, 0, -1)))
    s = NotifySettings(quiet_hours="22:00-07:00")
    assert s.is_quiet(time.mktime((2026, 10, 13, 23, 0, 0, 0, 0, -1)))
    assert not s.is_quiet(time.mktime((2026, 10, 13, 12, 0, 0, 0, 0, -1)))
    assert not NotifySettings(quiet_hours="garbage").is_quiet()


def test_T30_history_retention_keeps_unread(tmp_path):
    s = HubStore(tmp_path / "hub.sqlite3")
    old = msg(key="old-read")
    old.ts, old.read = 1000.0, True
    s.add(old)
    u = msg(key="old-unread")
    u.ts = 1000.0
    s.add(u)
    s.add(msg(key="new"))
    assert s.prune(30) == 1
    assert {r["key"] for r in s.messages()} == {"old-unread", "new"}
    assert s.prune(0) == 0
