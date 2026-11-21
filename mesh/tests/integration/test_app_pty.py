# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Full stack: build_application + MeshtasticProvider + real meshtastic 2.7.11 + pty radio + SQLite.

Covers AT-01, AT-06..AT-12, AT-19, AT-24 at the application level (offscreen, no hardware).
"""

import socket
import sqlite3
import sys
import time

import pytest
from PySide6.QtCore import Qt

from task_mesh.app import build_application
from task_mesh.domain.models import Classification, PortCandidate
from task_mesh.radio.hotplug import PollingHotplugWatcher
from task_mesh.ui.node_table import COLUMNS
from tests.fakes.pty_radio import MY, NUMBER_ONLY, OTHER, PtyRadio

DASH = "—"


def discover_for(radio):
    def discover():
        if not radio.link.exists():
            return []
        return [PortCandidate(device=radio.slave_path, by_id=str(radio.link), vid=0x10C4, pid=0xEA60,
                              serial_number="0001", manufacturer="Silicon Labs", product="CP2102",
                              classification=Classification.LIKELY, open_path=str(radio.link))]
    return discover


class App:
    def __init__(self, qtbot, xdg, radio):
        self.qtbot = qtbot
        self.radio = radio
        self.watcher = PollingHotplugWatcher(lambda: (radio.link.exists(), radio.slave_path), interval_ms=200,
                                             debounce_ms=100)
        self.ctx = build_application(env=xdg, discover=discover_for(radio), hotplug=self.watcher, console_log=False)
        self.ctx.window.resize(1024, 600)
        self.ctx.window.show()

    @property
    def state(self):
        return self.ctx.radio.last_snapshot.state

    def wait_state(self, *states, timeout=15000):
        self.qtbot.waitUntil(lambda: self.state in states, timeout=timeout)

    def wait_rows(self, n=3, timeout=3000):
        self.qtbot.waitUntil(lambda: self.ctx.model.rowCount() >= n, timeout=timeout)

    def cell(self, node_num, col_name):
        m = self.ctx.model
        for r in range(m.rowCount()):
            if m.record(r).node_num == node_num:
                return m.data(m.index(r, COLUMNS.index(col_name)), Qt.ItemDataRole.DisplayRole)
        raise KeyError(node_num)

    def tooltip(self, node_num, col_name):
        m = self.ctx.model
        for r in range(m.rowCount()):
            if m.record(r).node_num == node_num:
                return m.data(m.index(r, COLUMNS.index(col_name)), Qt.ItemDataRole.ToolTipRole)
        raise KeyError(node_num)

    def close(self):
        self.ctx.shutdown()
        self.ctx.window.close()


@pytest.fixture
def app_factory(qtbot, xdg):
    apps = []

    def make(radio):
        a = App(qtbot, xdg, radio)
        apps.append(a)
        return a

    yield make
    for a in apps:
        a.close()


@pytest.fixture
def excepthook_spy(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: seen.append(a))
    return seen


def test_at01_fresh_start_no_device_creates_dirs_and_db(app_factory, xdg, tmp_path, qtbot):
    radio = PtyRadio(tmp_path / "by-id")  # never plugged
    t0 = time.monotonic()
    a = app_factory(radio)
    a.wait_state("NO_DEVICE", timeout=2000)
    assert time.monotonic() - t0 < 2.0
    assert a.ctx.window.radio_panel.badge.text() == "DISCONNECTED"
    p = a.ctx.paths
    for d in (p.config_dir, p.state_dir, p.data_dir, p.log_dir, p.cache_dir):
        assert d.is_dir()
    v = sqlite3.connect(p.db_file).execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    assert v == 1


def test_at06_to_at09_connect_nodes_live_updates_and_malformed(app_factory, pty_radio, qtbot, excepthook_spy):
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    qtbot.waitUntil(lambda: a.ctx.model.rowCount() == 3, timeout=3000)
    panel = a.ctx.window.radio_panel
    assert panel.badge.text() == "CONNECTED"
    assert "TASK Base" in panel.device_value.text() and "HELTEC_V3" in panel.device_value.text()
    assert "usb-Silicon_Labs" in panel.port_value.text().replace("\u200b", "")
    # AT-06: placeholder suppressed, Powered, RSSI unknown until a packet arrives
    assert a.cell(NUMBER_ONLY, "Long Name") == DASH and a.cell(NUMBER_ONLY, "Hardware") == DASH
    assert a.cell(NUMBER_ONLY, "Node ID") == "!55667788"
    assert a.cell(MY, "Battery") == "Powered"
    for n in (MY, OTHER, NUMBER_ONLY):
        assert a.cell(n, "RSSI") == DASH
    assert a.cell(OTHER, "Hops") == "2"  # node DB value, plain (AT-08)
    # AT-07: runtime position + telemetry update cells within 1 s (no node.updated from the library)
    t0 = time.monotonic()
    pty_radio.send_position(OTHER, 401299999, -1051200000, rx_time=int(time.time()), snr=-3.5, rssi=-97,
                            hop_start=3, hop_limit=1)
    pty_radio.send_telemetry(OTHER, 55, 3.9, snr=-4.0, rssi=-101)
    qtbot.waitUntil(lambda: a.cell(OTHER, "Battery") == "55 %" and a.cell(OTHER, "RSSI") == "-101 dBm",
                    timeout=1000)
    assert time.monotonic() - t0 < 1.0
    assert a.cell(OTHER, "Latitude") == "40.13000" and a.cell(OTHER, "Longitude") == "-105.12000"
    assert a.cell(OTHER, "SNR") == "-4.00 dB"
    assert a.cell(OTHER, "Hops") == "2"  # node DB still wins over calculated
    # AT-08: calculated hops for a node with no node-DB hopsAway
    pty_radio.send_position(0x0BADCAFE, 1, 1, snr=1.0, rssi=-70, hop_start=4, hop_limit=1)
    qtbot.waitUntil(lambda: a.ctx.model.rowCount() == 4, timeout=2000)
    assert a.cell(0x0BADCAFE, "Hops") == "3 calc" and "Calculated" in a.tooltip(0x0BADCAFE, "Hops")
    # AT-09: malformed suite -> app alive, reader alive, nothing reaches Qt/excepthook
    pty_radio.send_malformed_suite()
    qtbot.wait(800)
    assert a.state == "CONNECTED"
    assert a.ctx.radio.worker._provider.is_alive()
    pty_radio.send_telemetry(OTHER, 33)
    qtbot.waitUntil(lambda: a.cell(OTHER, "Battery") == "33 %", timeout=2000)
    assert excepthook_spy == []


def test_at09_bad_packet_counter_via_bridge(app_factory, pty_radio, qtbot):
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    from pubsub import pub

    iface = a.ctx.radio.worker._provider._iface
    pub.sendMessage("meshtastic.receive", packet={"bogus": 1}, interface=iface)
    qtbot.waitUntil(lambda: a.ctx.status.info.bad_packets >= 1, timeout=4000)
    assert "Bad packets: 1" in a.ctx.window.status.bad_label.text()


def test_at10_unplug_backoff_and_auto_reconnect(app_factory, pty_radio, qtbot):
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    a.wait_rows()
    old_iface = a.ctx.radio.worker._provider._iface
    t0 = time.monotonic()
    pty_radio.unplug()
    a.wait_state("BACKOFF", "NO_DEVICE", timeout=3000)
    assert time.monotonic() - t0 < 3.0
    assert a.ctx.window.radio_panel.badge.text() == "DISCONNECTED"
    qtbot.waitUntil(lambda: old_iface.heartbeatTimer is None or not old_iface.heartbeatTimer.is_alive(),
                    timeout=3000)
    assert a.ctx.model.rowCount() == 3  # nodes stay visible as last known
    pty_radio.plug()  # replug: new pty behind the same by-id link
    a.wait_state("CONNECTED", timeout=10000)
    assert a.ctx.radio.worker._provider._iface is not old_iface
    a.ctx.writer.flush(5)
    seq = [r for r in sqlite3.connect(a.ctx.paths.db_file).execute(
        "SELECT from_state, to_state FROM connection_events ORDER BY id")]
    i = seq.index(("CONNECTED", "DISCONNECTING"))
    assert seq[i + 1][0] == "DISCONNECTING" and seq[i + 1][1] == "BACKOFF"
    assert seq[-1] == ("CONNECTING", "CONNECTED")


def test_at11_rebooted_frame_same_interface(app_factory, pty_radio, qtbot):
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    qtbot.wait(300)
    iface = a.ctx.radio.worker._provider._iface
    states = []
    a.ctx.radio.state_changed.connect(lambda s: states.append(s.state))
    pty_radio.send_rebooted()
    qtbot.waitUntil(lambda: "DEVICE_REBOOTING" in states and a.state == "CONNECTED", timeout=5000)
    assert a.ctx.radio.worker._provider._iface is iface
    assert "DISCONNECTING" not in states


def test_at12_port_busy_then_success_after_release(app_factory, pty_radio, qtbot):
    import serial

    holder = serial.Serial(str(pty_radio.link), exclusive=True)
    a = app_factory(pty_radio)
    qtbot.waitUntil(lambda: a.ctx.radio.last_snapshot.error_code == "PORT_BUSY", timeout=5000)
    assert "Another program" in a.ctx.window.radio_panel.remedy_label.text()
    holder.close()
    a.wait_state("CONNECTED", timeout=15000)


def test_at19_restart_persistence_marks_last_known(app_factory, pty_radio, qtbot, xdg):
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    qtbot.waitUntil(lambda: a.ctx.model.rowCount() == 3)
    before = {a.ctx.model.record(r).node_num: a.ctx.model.record(r) for r in range(3)}
    a.close()
    pty_radio.unplug()
    b = app_factory(pty_radio)
    b.wait_state("NO_DEVICE", timeout=3000)
    assert b.ctx.model.rowCount() == 3
    for r in range(3):
        rec = b.ctx.model.record(r)
        assert rec.stale and "Last known" in b.tooltip(rec.node_num, "Long Name")
        old = before[rec.node_num]
        assert (rec.long_name, rec.hw_model, rec.battery_level, rec.latitude, rec.snr, rec.hops_away) == \
            (old.long_name, old.hw_model, old.battery_level, old.latitude, old.snr, old.hops_away)
    pty_radio.plug()
    b.wait_state("CONNECTED", timeout=10000)
    qtbot.waitUntil(lambda: not any(b.ctx.model.record(r).stale for r in range(3)), timeout=3000)


def test_at24_offline_no_network_attempts(app_factory, pty_radio, qtbot, monkeypatch):
    attempts = []
    real_connect = socket.socket.connect

    def guard(self, addr):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append(addr)
            raise OSError("network disabled by test")
        return real_connect(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: attempts.append(a) or (_ for _ in ()).throw(
        OSError("network disabled by test")))
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    a.wait_rows()
    pty_radio.send_position(OTHER, 401000000, -1050000000, rssi=-90)
    qtbot.waitUntil(lambda: a.cell(OTHER, "RSSI") == "-90 dBm", timeout=2000)
    pty_radio.unplug()
    a.wait_state("BACKOFF", "NO_DEVICE", timeout=3000)
    assert attempts == []


def test_at21_psk_not_in_logs_or_db_during_session(app_factory, pty_radio, qtbot):
    import base64

    psk = bytes(range(200, 232))
    a = app_factory(pty_radio)
    a.wait_state("CONNECTED")
    a.wait_rows()
    pty_radio.send_channel_with_psk(psk)
    pty_radio.send_telemetry(OTHER, 50)
    qtbot.waitUntil(lambda: a.cell(OTHER, "Battery") == "50 %", timeout=2000)
    a.ctx.writer.flush(5)
    a.close()
    blobs = [base64.b64encode(psk), psk.hex().encode(), psk]
    for f in list(a.ctx.paths.log_dir.glob("*")) + list(a.ctx.paths.data_dir.glob("*")):
        data = f.read_bytes()
        for b in blobs:
            assert b not in data, f
