# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Pins upstream meshtastic 2.7.11 behaviours T.A.S.K. depends on (design report §7 item 4, AT-25).

Runs the REAL library against tests/fakes/pty_radio.py. A library bump that changes any of these
must fail here first.
"""

import fcntl
import os
import threading
import time

import pytest
from pubsub import pub

import meshtastic
import meshtastic.serial_interface as si
from tests.fakes.pty_radio import MY, NUMBER_ONLY, OTHER, PtyRadio


class Rec:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()
        pub.subscribe(self.cb, "meshtastic")

    def cb(self, topic=pub.AUTO_TOPIC, **kw):
        with self.lock:
            self.events.append((topic.getName(), threading.current_thread().name, kw))

    def names(self):
        with self.lock:
            return [e[0] for e in self.events]

    def count(self, name):
        return self.names().count(name)

    def wait(self, name, n=1, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.count(name) >= n:
                return True
            time.sleep(0.02)
        return False

    def clear(self):
        with self.lock:
            self.events.clear()

    def close(self):
        pub.unsubscribe(self.cb, "meshtastic")


@pytest.fixture
def rec():
    r = Rec()
    yield r
    r.close()


@pytest.fixture
def iface(pty_radio, rec):
    i = si.SerialInterface(devPath=str(pty_radio.link), timeout=300)
    # connection.established is delivered asynchronously by the 'publishing' thread after the
    # constructor returns (verified); let it drain, then start each test with a clean record.
    assert rec.wait("meshtastic.connection.established")
    time.sleep(0.2)
    rec.clear()
    yield i
    i.close()


def test_library_version_is_vendored_pin():
    from importlib.metadata import version

    try:
        v = version("meshtastic")
    except Exception:  # noqa: BLE001 - vendored without dist-info
        v = getattr(meshtastic, "__version__", None)
    assert v in (None, "2.7.11") or v.startswith("2.7.11")


def test_handshake_completes_and_nodedb_shape(iface, rec):
    assert iface.isConnected.is_set()
    assert iface.myInfo.my_node_num == MY
    assert iface.metadata.firmware_version == "2.7.15.567b8ea"
    other = iface.nodesByNum[OTHER]
    assert other["user"]["longName"] == "Ridge Relay" and other["hopsAway"] == 2
    assert other["position"]["latitude"] == pytest.approx(40.1234567)
    assert "rssi" not in str(other).lower()
    ph = iface.nodesByNum[NUMBER_ONLY]["user"]
    assert ph["longName"] == "Meshtastic 7788" and ph["hwModel"] == "UNSET"  # library placeholder


def test_private_rx_thread_attribute_exists(iface):
    assert isinstance(iface._rxThread, threading.Thread) and iface._rxThread.is_alive()
    assert iface.stream is not None


def test_node_updated_only_during_config_runtime_packets_silent(pty_radio, iface, rec):
    assert rec.count("meshtastic.node.updated") == 0  # we subscribed after config
    pty_radio.send_position(OTHER, 401000000, -1050000000, rx_time=1790000000, snr=-3.5, rssi=-97,
                            hop_start=3, hop_limit=1)
    pty_radio.send_telemetry(OTHER, 55)
    assert rec.wait("meshtastic.receive.telemetry")
    assert rec.count("meshtastic.node.updated") == 0
    o = iface.nodesByNum[OTHER]
    assert o["position"]["latitude"] == pytest.approx(40.1) and o["deviceMetrics"]["batteryLevel"] == 55
    pos = next(e for e in rec.events if e[0] == "meshtastic.receive.position")
    assert pos[1] == "publishing"
    pkt = pos[2]["packet"]
    assert pkt["rxRssi"] == -97 and pkt["hopStart"] == 3 and pkt["hopLimit"] == 1 and pkt["from"] == OTHER


def test_node_updated_fires_during_config(pty_radio, rec):
    i = si.SerialInterface(devPath=str(pty_radio.link), timeout=300)
    try:
        assert rec.wait("meshtastic.connection.established")
        assert rec.count("meshtastic.node.updated") >= 3
        names = rec.names()
        assert max(i for i, n in enumerate(names) if n == "meshtastic.node.updated") < \
            names.index("meshtastic.connection.established")
        assert all(e[1] == "publishing" for e in rec.events if e[0] == "meshtastic.node.updated")
    finally:
        i.close()


def test_log_line_on_stream_reader_thread(pty_radio, iface, rec):
    pty_radio.write(b"INFO  | 12:00:00 1 [Router] hello from device\r\n")
    assert rec.wait("meshtastic.log.line")
    ev = next(e for e in rec.events if e[0] == "meshtastic.log.line")
    assert ev[1] == "stream reader"


def test_reader_survives_malformed_frames(pty_radio, iface, rec):
    pty_radio.send_malformed_suite()
    pty_radio.write(b"\x94\xc3" * 32768)  # 64 KiB of start bytes
    time.sleep(0.8)
    assert iface._rxThread.is_alive() and iface.isConnected.is_set()
    pty_radio.send_telemetry(OTHER, 44)
    assert rec.wait("meshtastic.receive.telemetry")


def test_rebooted_lost_then_established_same_instance(pty_radio, iface, rec):
    reader = iface._rxThread
    pty_radio.send_rebooted()
    assert rec.wait("meshtastic.connection.lost")
    assert rec.wait("meshtastic.connection.established")
    assert iface._rxThread is reader and reader.is_alive() and iface.stream is not None
    names = rec.names()
    assert names.index("meshtastic.connection.lost") < names.index("meshtastic.connection.established")


def test_pty_close_lost_and_no_auto_reconnect(pty_radio, iface, rec):
    pty_radio.unplug()
    assert rec.wait("meshtastic.connection.lost")
    time.sleep(1.5)
    assert not iface._rxThread.is_alive() and iface.stream is None
    assert rec.count("meshtastic.connection.established") == 0


def test_missing_path_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        si.SerialInterface(devPath=str(tmp_path / "nope"), timeout=300)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permissions")
def test_no_permission_raises_permissionerror(tmp_path):
    f = tmp_path / "ttyUSB9"
    f.write_text("")
    f.chmod(0)
    try:
        with pytest.raises(PermissionError):
            si.SerialInterface(devPath=str(f), timeout=300)
    finally:
        f.chmod(0o600)


def test_locked_port_raises_serialexception(pty_radio):
    import serial

    holder = serial.Serial(str(pty_radio.link), exclusive=True)
    try:
        with pytest.raises(serial.SerialException, match="exclusively lock"):
            si.SerialInterface(devPath=str(pty_radio.link), timeout=300)
    finally:
        holder.close()


def test_devpath_none_with_two_ports_exits(monkeypatch):
    import meshtastic.util

    monkeypatch.setattr(meshtastic.util, "findPorts", lambda *a, **k: ["/dev/ttyUSB0", "/dev/ttyUSB1"])
    with pytest.raises(SystemExit):
        si.SerialInterface(devPath=None, timeout=300)


@pytest.mark.slow
@pytest.mark.timeout(90)
def test_silent_device_times_out_after_about_30s(tmp_path):
    r = PtyRadio(tmp_path / "by-id", silent=True).plug()
    try:
        t0 = time.monotonic()
        from meshtastic.mesh_interface import MeshInterface

        with pytest.raises(MeshInterface.MeshInterfaceError, match="Timed out"):
            si.SerialInterface(devPath=str(r.link), timeout=300)
        assert 25 <= time.monotonic() - t0 <= 40
    finally:
        r.unplug()


def test_flock_semantics_documented():
    assert hasattr(fcntl, "flock")
