# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-mesh 0.2.0 messaging: delivery states, auth gate, private history (automated, fake radio)."""

from __future__ import annotations

import stat

import pytest

from task_comms.auth import SessionGate
from task_mesh.messaging.packets import BROADCAST_NUM, RoutingPacket, TextPacket, parse_routing, parse_text
from task_mesh.messaging.service import ACK_TIMEOUT_S, MessageError, MessageService
from task_mesh.messaging.store import MessageStore

LOCAL, PEER, RELAY = 0xA1B2C3D4, 0x11223344, 0x55667788


class FakeClient:
    def __init__(self, role="operator"):
        self.token, self.username, self.role = None, None, None
        self._role = role

    def login(self, u, s):
        if s != "pw":
            raise PermissionError("bad")
        self.token, self.username, self.role = "T", u, self._role
        return {"username": u, "role": self._role}

    def logout(self):
        self.token = self.username = self.role = None

    def has_role(self, needed):
        order = {"operator": 1, "administrator": 2}
        return self.role is not None and order.get(self.role, 0) >= order[needed]


@pytest.fixture
def svc(tmp_path):
    t = [1000.0]
    sent = []
    gate = SessionGate(FakeClient())
    store = MessageStore(tmp_path / "data/task-mesh/messages.sqlite3")
    pid = iter(range(500, 600))

    def sender(text, dest, ch):
        sent.append((text, dest, ch))
        return next(pid)
    s = MessageService(store, gate, sender, clock=lambda: t[0], run_async=lambda fn: fn())
    s.local_num = LOCAL
    s._t, s._sent = t, sent
    return s


def test_mm01_locked_until_sign_in(svc):
    with pytest.raises(MessageError, match="sign in"):
        svc.send("hello", channel=0)
    with pytest.raises(MessageError):
        svc.conversation(0, "^all")
    assert svc._sent == []  # nothing transmitted without a session
    svc.on_text(TextPacket(1, PEER, LOCAL, 0, "secret DM", None, False))
    assert svc.unread == 1 and not svc.store.is_open  # counted, not stored or shown while locked


def test_mm02_dm_delivered_only_on_destination_ack(svc):
    svc.gate.sign_in("op", "pw")
    lid = svc.send("meet at 1400", dest="!11223344")
    row = svc.store.get(lid)
    assert row["state"] == "sent" and row["packet_id"] == 500 and svc._sent == [("meet at 1400", PEER, 0)]
    svc.on_routing(RoutingPacket(500, LOCAL, "NONE"))   # implicit ACK (heard rebroadcast)
    assert svc.store.get(lid)["state"] == "relayed"
    svc.on_routing(RoutingPacket(500, PEER, "NONE"))    # explicit ACK from destination
    assert svc.store.get(lid)["state"] == "delivered"
    svc.on_routing(RoutingPacket(500, PEER, "MAX_RETRANSMIT"))
    assert svc.store.get(lid)["state"] == "delivered"   # final states never regress


def test_mm03_broadcast_never_delivered(svc):
    svc.gate.sign_in("op", "pw")
    lid = svc.send("net check", channel=1)
    assert svc._sent[-1] == ("net check", BROADCAST_NUM, 1)
    svc.on_routing(RoutingPacket(500, RELAY, "NONE"))
    svc.on_routing(RoutingPacket(500, PEER, "NONE"))
    assert svc.store.get(lid)["state"] == "relayed"


def test_mm04_nak_and_timeout(svc):
    svc.gate.sign_in("op", "pw")
    a = svc.send("one", dest="!11223344")
    b = svc.send("two", dest="!11223344")
    svc.on_routing(RoutingPacket(500, LOCAL, "NO_ROUTE"))
    assert svc.store.get(a)["state"] == "failed" and svc.store.get(a)["detail"] == "NO_ROUTE"
    svc._t[0] += ACK_TIMEOUT_S + 1
    svc.check_timeouts()
    assert svc.store.get(b)["state"] == "no-ack"


def test_mm05_radio_error_is_failed_not_sent(tmp_path):
    gate = SessionGate(FakeClient())
    def boom(*a):
        raise OSError("serial gone")
    s = MessageService(MessageStore(tmp_path / "m.sqlite3"), gate, boom, run_async=lambda fn: fn())
    gate.sign_in("op", "pw")
    lid = s.send("x")
    assert s.store.get(lid)["state"] == "failed" and "OSError" in s.store.get(lid)["detail"]


def test_mm06_validation(svc):
    svc.gate.sign_in("op", "pw")
    for bad in ("", "   ", "é" * 101):
        with pytest.raises(MessageError):
            svc.send(bad)
    with pytest.raises(ValueError):
        svc.send("x", dest="11223344")
    with pytest.raises(MessageError, match="this radio"):
        svc.send("x", dest="!a1b2c3d4")
    with pytest.raises(MessageError):
        svc.send("x", channel=8)


def test_mm07_receive_dm_channel_and_filter(svc):
    svc.gate.sign_in("op", "pw")
    svc.unlock()
    assert svc.on_text(TextPacket(9, PEER, LOCAL, 0, "hi base", None, False))
    assert svc.on_text(TextPacket(10, RELAY, BROADCAST_NUM, 2, "all hands", None, True))
    assert svc.on_text(TextPacket(11, RELAY, PEER, 0, "not for us", None, False)) is None
    assert svc.on_text(TextPacket(12, LOCAL, BROADCAST_NUM, 0, "echo", None, False)) is None
    assert [r["text"] for r in svc.conversation(0, "!11223344")] == ["hi base"]
    ch = svc.conversation(2, "^all")
    assert ch[0]["detail"] == "via MQTT" and ch[0]["from_id"] == "!55667788"


def test_mm08_history_file_private_and_closed_on_session_end(svc):
    svc.gate.sign_in("op", "pw")
    svc.send("x")
    p = svc.store.path
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    events = []
    svc.listeners.append(lambda k, d: events.append(k))
    svc.gate.session_ended("session-ended")
    assert not svc.store.is_open and "locked" in events
    with pytest.raises(MessageError):
        svc.conversation(0, "^all")


def test_mm09_public_role_cannot_send(tmp_path):
    gate = SessionGate(FakeClient(role="public"))
    s = MessageService(MessageStore(tmp_path / "m.sqlite3"), gate, lambda *a: 1, run_async=lambda fn: fn())
    gate.sign_in("guest", "pw")
    with pytest.raises(MessageError, match="operator"):
        s.send("x")


def test_mm10_packet_parsers():
    t = parse_text({"from": PEER, "to": LOCAL, "id": 7, "channel": 1,
                    "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hey\x00"}})
    assert t.text == "hey" and t.is_direct and t.channel == 1
    assert parse_text({"from": PEER, "decoded": {"portnum": "POSITION_APP"}}) is None
    assert parse_text({"from": 0, "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "x"}}) is None
    r = parse_routing({"from": PEER, "decoded": {"portnum": "ROUTING_APP", "requestId": 500,
                                                 "routing": {"errorReason": "NO_ROUTE"}}})
    assert r == RoutingPacket(500, PEER, "NO_ROUTE")
    assert parse_routing({"from": PEER, "decoded": {"portnum": "ROUTING_APP", "routing": {}}}) is None
    assert parse_routing({"from": PEER, "decoded": {"portnum": "ROUTING_APP", "requestId": 5}}).error_reason == "NONE"


def test_mm11_message_text_never_logged(svc, caplog):
    svc.gate.sign_in("op", "pw")
    import logging
    caplog.set_level(logging.DEBUG)
    svc.send("TOPSECRET-TEXT", dest="!11223344")
    svc.on_text(TextPacket(9, PEER, LOCAL, 0, "TOPSECRET-IN", None, False))
    assert "TOPSECRET" not in caplog.text
