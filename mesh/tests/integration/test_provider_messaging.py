# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-mesh 0.2.0: provider send_text/channels + pubsub text/routing delivery (fake interface, real pypubsub)."""

import logging
import threading
import time

import pytest

from task_mesh.radio.meshtastic.provider import MeshtasticProvider
from tests.fakes.fake_ports import candidate
from tests.fakes.fake_serial_interface import FakeSerialInterface


class Sink:
    def __init__(self):
        self.calls, self.lock = [], threading.Lock()

    def _add(self, *a):
        with self.lock:
            self.calls.append(a)

    def on_established(self, g): self._add("est", g)
    def on_lost(self, g): self._add("lost", g)
    def on_nodeinfo(self, g, i): self._add("node", g, i)
    def on_observation(self, g, o): self._add("obs", g, o)
    def on_radio_event(self, g, e): self._add("ev", g, e)
    def on_text(self, g, t): self._add("text", g, t)
    def on_routing(self, g, r): self._add("routing", g, r)

    def wait(self, kind, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                hit = [c for c in self.calls if c[0] == kind]
            if hit:
                return hit
            time.sleep(0.01)
        return []


@pytest.fixture
def prov():
    FakeSerialInterface.reset()
    sink = Sink()
    p = MeshtasticProvider(sink, interface_factory=lambda **kw: FakeSerialInterface(**kw))
    p.connect(candidate("/dev/ttyUSB0"), 1)
    yield p, sink
    p.shutdown()
    FakeSerialInterface.reset()


def test_mp01_send_text_wants_ack_and_returns_id(prov, caplog):
    p, _ = prov
    caplog.set_level(logging.DEBUG)
    pid = p.send_text("SECRET-BODY", 0x11223344, 1)
    sent = FakeSerialInterface.sent_texts[-1]
    assert pid == sent["id"] and sent["wantAck"] is True and sent["dest"] == 0x11223344 and sent["channel"] == 1
    assert "SECRET-BODY" not in caplog.text


def test_mp02_channels_without_psk(prov):
    p, _ = prov
    chans = p.channels()
    assert chans == [(0, "Primary", "PRIMARY"), (1, "Ops", "SECONDARY")]
    assert "SECRET" not in repr(chans)


def test_mp03_text_and_routing_reach_sink(prov):
    p, sink = prov
    iface = FakeSerialInterface.instances[-1]
    iface.publish("meshtastic.receive", interface=iface, packet={
        "from": 0x11223344, "to": 0xA1B2C3D4, "id": 77, "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hello"}})
    iface.publish("meshtastic.receive", interface=iface, packet={
        "from": 0x11223344, "to": 0xA1B2C3D4, "id": 78,
        "decoded": {"portnum": "ROUTING_APP", "requestId": 4097, "routing": {"errorReason": "NONE"}}})
    t = sink.wait("text")[0][2]
    r = sink.wait("routing")[0][2]
    assert t.text == "hello" and t.is_direct and r.request_id == 4097 and r.error_reason == "NONE"
    assert sink.wait("obs")  # node bookkeeping unchanged


def test_mp04_send_without_link_raises(prov):
    p, _ = prov
    p.close()
    with pytest.raises(Exception):
        p.send_text("x", 0xFFFFFFFF, 0)
