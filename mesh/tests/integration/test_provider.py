# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""MeshtasticProvider against FakeSerialInterface + real pypubsub (design report §7 item 2)."""

import gc
import re
import threading
import time
from pathlib import Path

import pytest
import serial

from task_mesh.core.errors import ErrorCode
from task_mesh.radio.base import ConnectError
from task_mesh.radio.meshtastic.provider import MeshtasticProvider
from tests.fakes.fake_ports import candidate
from tests.fakes.fake_serial_interface import FakeSerialInterface


class Sink:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def _add(self, *a):
        with self.lock:
            self.calls.append(a)

    def on_established(self, g): self._add("est", g)
    def on_lost(self, g): self._add("lost", g)
    def on_nodeinfo(self, g, i): self._add("node", g, i)
    def on_observation(self, g, o): self._add("obs", g, o)
    def on_radio_event(self, g, e): self._add("ev", g, e)

    def kinds(self):
        with self.lock:
            return [c[0] for c in self.calls]

    def wait(self, kind, n=1, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.kinds().count(kind) >= n:
                return True
            time.sleep(0.01)
        return False


@pytest.fixture(autouse=True)
def _reset():
    FakeSerialInterface.reset()
    yield
    FakeSerialInterface.reset()


def factory(**kw):
    return FakeSerialInterface(**kw)


def provider(sink):
    return MeshtasticProvider(sink, interface_factory=factory, library_timeout_s=300)


def test_connect_passes_explicit_by_id_devpath_and_reads_identity():
    s = Sink()
    p = provider(s)
    ident = p.connect(candidate("/dev/ttyUSB0", "/dev/serial/by-id/usb-X"), 1)
    assert FakeSerialInterface.calls[-1]["devPath"] == "/dev/serial/by-id/usb-X"
    assert FakeSerialInterface.calls[-1]["timeout"] == 300
    assert ident.node_num == 0xA1B2C3D4 and ident.long_name == "TASK Base" and ident.hw_model == "HELTEC_V3"
    assert ident.firmware_version == "2.7.15.567b8ea"
    assert s.wait("est")
    assert p.is_alive() and p.port_open()
    p.shutdown()


@pytest.mark.parametrize("exc,code", [
    (FileNotFoundError(2, "No such file"), ErrorCode.NO_DEVICE),
    (PermissionError(13, "Permission denied"), ErrorCode.PERMISSION_DENIED),
    (serial.SerialException("[Errno 11] Could not exclusively lock port /dev/ttyUSB0"), ErrorCode.PORT_BUSY),
    (serial.SerialException("device reports readiness to read but returned no data"), ErrorCode.SERIAL_ERROR),
    (SystemExit(1), ErrorCode.UNEXPECTED),
    (ImportError("no meshtastic"), ErrorCode.LIBRARY_MISSING),
    (RuntimeError("weird"), ErrorCode.UNEXPECTED),
])
def test_constructor_exceptions_mapped(exc, code):
    FakeSerialInterface.raise_on_init = exc
    p = provider(Sink())
    with pytest.raises(ConnectError) as ei:
        p.connect(candidate("/dev/ttyUSB0"), 1)
    assert ei.value.code is code
    assert p.current_generation is None and not p.is_alive()
    p.shutdown()


def test_handshake_timeout_mapped():
    from meshtastic.mesh_interface import MeshInterface

    FakeSerialInterface.raise_on_init = MeshInterface.MeshInterfaceError("Timed out waiting for connection completion")
    p = provider(Sink())
    with pytest.raises(ConnectError) as ei:
        p.connect(candidate("/dev/ttyUSB0"), 1)
    assert ei.value.code is ErrorCode.HANDSHAKE_TIMEOUT
    p.shutdown()


def test_snapshot_suppresses_placeholder_and_survives_concurrent_mutation():
    p = provider(Sink())
    p.connect(candidate("/dev/ttyUSB0"), 1)
    iface = FakeSerialInterface.instances[-1]
    stop = threading.Event()

    def mutate():
        i = 0
        while not stop.is_set():
            iface.nodesByNum[1000 + i % 300] = {"num": 1000 + i % 300}
            iface.nodesByNum.pop(1000 + (i + 150) % 300, None)
            i += 1

    t = threading.Thread(target=mutate)
    t.start()
    try:
        for _ in range(50):
            p.snapshot_nodes()
    finally:
        stop.set()
        t.join()
    nodes = {n.node_num: n for n in p.snapshot_nodes()}
    assert nodes[0x55667788].user.long_name is None
    p.shutdown()


def test_events_from_other_interfaces_are_dropped():
    s = Sink()
    p = provider(s)
    p.connect(candidate("/dev/ttyUSB0"), 7)
    assert s.wait("est")
    from pubsub import pub

    other = object()
    pub.sendMessage("meshtastic.receive.text", packet={"from": 9, "rxRssi": -5}, interface=other)
    pub.sendMessage("meshtastic.receive.text", packet={"from": 9, "rxRssi": -60},
                    interface=FakeSerialInterface.instances[-1])
    assert s.wait("obs")
    obs = [c for c in s.calls if c[0] == "obs"]
    assert len(obs) == 1 and obs[0][1] == 7 and obs[0][2].rx_rssi == -60
    p.shutdown()


def test_malformed_packet_becomes_bad_packet_event():
    s = Sink()
    p = provider(s)
    p.connect(candidate("/dev/ttyUSB0"), 1)
    from pubsub import pub

    pub.sendMessage("meshtastic.receive", packet={"nofrom": True}, interface=FakeSerialInterface.instances[-1])
    pub.sendMessage("meshtastic.node.updated", node="garbage", interface=FakeSerialInterface.instances[-1])
    assert s.wait("ev", 2)
    evs = [c[2] for c in s.calls if c[0] == "ev"]
    assert {e.kind for e in evs} == {"bad_packet"}
    assert p.counters["bad_packets"] == 2
    p.shutdown()


def test_weakref_guard_events_arrive_after_gc():
    """AT-23: pypubsub holds weak refs; our bridge must stay subscribed."""
    s = Sink()
    p = provider(s)
    p.connect(candidate("/dev/ttyUSB0"), 1)
    gc.collect()
    from pubsub import pub

    pub.sendMessage("meshtastic.receive.position", packet={"from": 5, "rxSnr": 1.0},
                    interface=FakeSerialInterface.instances[-1])
    assert s.wait("obs")
    p.shutdown()


def test_unplug_lost_then_close_and_no_events_after_shutdown():
    s = Sink()
    p = provider(s)
    p.connect(candidate("/dev/ttyUSB0"), 1)
    iface = FakeSerialInterface.instances[-1]
    iface.unplug()
    assert s.wait("lost")
    assert not p.is_alive() and not p.port_open()
    p.shutdown()
    assert iface.closed
    n = len(s.calls)
    from pubsub import pub

    pub.sendMessage("meshtastic.receive", packet={"from": 5}, interface=iface)
    time.sleep(0.05)
    assert len(s.calls) == n


def test_heartbeat_and_no_stream():
    p = provider(Sink())
    p.connect(candidate("/dev/ttyUSB0"), 1)
    p.send_heartbeat()
    assert FakeSerialInterface.instances[-1].heartbeats == 1
    FakeSerialInterface.instances[-1].stream = None
    with pytest.raises(ConnectError):
        p.send_heartbeat()
    p.shutdown()


def test_static_no_devpath_none_anywhere():
    """AT-04 (static part): every SerialInterface(...) call passes an explicit, non-None devPath."""
    import ast

    root = Path(__file__).resolve().parents[2] / "task_mesh"
    calls = []
    for f in root.rglob("*.py"):
        if "_vendor" in f.parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "SerialInterface":
                    calls.append((f.name, node))
    assert calls, "expected the provider's factory call"
    for fname, call in calls:
        assert not call.args, f"{fname}: devPath must be passed by keyword"
        kw = {k.arg: k.value for k in call.keywords}
        assert "devPath" in kw, fname
        assert not (isinstance(kw["devPath"], ast.Constant) and kw["devPath"].value is None), fname


def test_runtime_spy_devpath_never_none():
    """AT-04 (runtime part): FakeSerialInterface raises AssertionError on devPath=None; all calls had a path."""
    p = provider(Sink())
    for gen, path in enumerate(["/dev/ttyACM0", "/dev/serial/by-path/x"]):
        p.connect(candidate(path), gen + 1)
    assert all(c["devPath"] for c in FakeSerialInterface.calls)
    p.shutdown()
