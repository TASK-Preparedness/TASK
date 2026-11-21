# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""RadioWorker state machine through the real queued-signal path, with FakeRadioProvider."""

import threading
import time

import pytest

from task_mesh.core.config import RadioConfig, StateStore
from task_mesh.core.errors import ErrorCode
from task_mesh.database.writer import OP_CONN_EVENT, OP_RADIO
from task_mesh.domain.models import Observation
from task_mesh.radio.discovery import Preflight
from task_mesh.services.backoff import Backoff
from task_mesh.services.radio_service import RadioService, RadioWorker
from tests.fakes.fake_ports import candidate
from tests.fakes.fake_provider import ProviderFactory, Script, err

C1 = candidate("/dev/ttyUSB0", "/dev/serial/by-id/usb-A")
C2 = candidate("/dev/ttyACM0", "/dev/serial/by-id/usb-B")


class Harness:
    def __init__(self, qtbot, tmp_path, ports=(C1,), cfg=None, preflight_fn=None, autostart=True):
        self.qtbot = qtbot
        self.ports = list(ports)
        self.exists = {"ok": True}
        self.factory = ProviderFactory(Script())
        self.script = self.factory.script
        self.records = []
        self.preflights = []
        self.state_store = StateStore(tmp_path / "state.json")
        self.cfg = cfg or RadioConfig(handshake_deadline_s=45, link_probe_s=0, reboot_grace_s=60)

        def pf(path):
            self.preflights.append(path)
            return preflight_fn(path) if preflight_fn else Preflight(True)

        self.worker = RadioWorker(
            self.cfg, self.state_store, record=lambda op, *a: self.records.append((op, a)) or True,
            provider_factory=self.factory, discover=lambda: list(self.ports),
            backoff=Backoff(base=0.1, cap=0.3, jitter=0.0), path_exists=lambda p: self.exists["ok"],
            preflight_fn=pf, watchdog_ms=100, no_device_poll_ms=150)
        self.svc = RadioService(self.worker)
        self.states = []
        self.observations = []
        self.snapshots = []
        self.svc.state_changed.connect(lambda s: self.states.append(s.state))
        self.svc.observation.connect(self.observations.append)
        self.svc.nodes_snapshot.connect(self.snapshots.append)
        if autostart:
            self.svc.start()

    @property
    def state(self):
        return self.svc.last_snapshot.state

    def wait_state(self, st, timeout=3000):
        self.qtbot.waitUntil(lambda: self.state == st, timeout=timeout)

    def conn_events(self):
        return [(a[0].from_state, a[0].to_state) for op, a in self.records if op == OP_CONN_EVENT]

    def stop(self):
        self.script.release.set()
        self.svc.stop()


@pytest.fixture
def h(qtbot, tmp_path):
    hs = []

    def make(**kw):
        x = Harness(qtbot, tmp_path, **kw)
        hs.append(x)
        return x

    yield make
    for x in hs:
        x.stop()


def test_connect_happy_path(h):
    x = h()
    x.wait_state("CONNECTED")
    snap = x.svc.last_snapshot
    assert snap.identity.long_name == "TASK Base" and snap.port == C1
    assert x.conn_events()[:3] == [("IDLE", "SCANNING"), ("SCANNING", "CONNECTING"), ("CONNECTING", "CONNECTED")]
    assert any(op == OP_RADIO for op, _ in x.records)
    assert x.state_store.get("last_success")["by_id"] == "/dev/serial/by-id/usb-A"
    x.qtbot.waitUntil(lambda: len(x.snapshots) == 1)
    assert x.worker.thread().objectName() == "task-radio"


def test_no_device_then_hotplug_connects(h):
    x = h(ports=())
    x.wait_state("NO_DEVICE")
    x.ports.append(C1)
    x.svc.rescan("hotplug_add")
    x.wait_state("CONNECTED")


def test_no_device_poll_backstop_without_hotplug(h):
    x = h(ports=())
    x.wait_state("NO_DEVICE")
    x.ports.append(C1)
    x.wait_state("CONNECTED", 2000)


def test_two_likely_requires_selection_and_pin(h):
    x = h(ports=(C1, C2))
    x.wait_state("AWAITING_SELECTION")
    time.sleep(0.3)
    assert x.script.attempts == []  # no port opened until the user chooses
    assert set(x.svc.last_snapshot.candidates) == {C1, C2}
    x.svc.select(C2, True)
    x.wait_state("CONNECTED")
    assert x.script.attempts == [C2]
    assert x.state_store.get("pinned_port")["by_id"] == "/dev/serial/by-id/usb-B"


def test_pinned_device_autoconnects_on_restart(h, tmp_path):
    StateStore(tmp_path / "state.json").set("pinned_port", C2.identity())
    x = h(ports=(C1, C2))
    x.wait_state("CONNECTED")
    assert x.script.attempts == [C2]


def test_permission_denied_no_retry_storm(h):
    x = h(preflight_fn=lambda p: Preflight(False, ErrorCode.PERMISSION_DENIED, "group dialout"))
    x.wait_state("PERMISSION_DENIED")
    time.sleep(0.8)
    assert len(x.preflights) == 1 and x.script.attempts == []
    snap = x.svc.last_snapshot
    assert snap.error_code == "PERMISSION_DENIED" and snap.retry_at_local is None
    x.svc.rescan("hotplug_change")
    x.qtbot.waitUntil(lambda: len(x.preflights) == 2)
    time.sleep(0.5)
    assert len(x.preflights) == 2  # exactly one attempt per hot-plug event
    assert x.state == "PERMISSION_DENIED"


def test_permission_error_from_constructor(h):
    x = h(autostart=False)
    x.script.connect_errors = [err(ErrorCode.PERMISSION_DENIED)]
    x.svc.start()
    x.wait_state("PERMISSION_DENIED")
    x.svc.connect_radio()  # user "Retry now"
    x.wait_state("CONNECTED")


def test_port_busy_then_backoff_then_success(h):
    x = h(autostart=False)
    x.script.connect_errors = [err(ErrorCode.PORT_BUSY, "Could not exclusively lock port")]
    x.svc.start()
    x.wait_state("CONNECTED")
    seq = x.conn_events()
    assert ("CONNECTING", "PORT_BUSY") in seq and ("PORT_BUSY", "BACKOFF") in seq
    assert x.svc.last_snapshot.error_code == "PORT_BUSY"  # last error remains visible after recovery


def test_handshake_timeout_backoff_and_retry(h):
    x = h(autostart=False)
    x.script.connect_errors = [err(ErrorCode.HANDSHAKE_TIMEOUT), err(ErrorCode.HANDSHAKE_TIMEOUT)]
    x.svc.start()
    x.wait_state("CONNECTED", 5000)
    assert x.conn_events().count(("CONNECTING", "BACKOFF")) == 2
    assert len(x.script.attempts) == 3


def test_unplug_disconnecting_backoff_and_reconnect(h):
    x = h()
    x.wait_state("CONNECTED")
    old = x.factory.last
    x.exists["ok"] = False
    x.ports.clear()
    t0 = time.monotonic()
    old.drop()
    x.qtbot.waitUntil(lambda: x.state in ("BACKOFF", "NO_DEVICE"), timeout=3000)
    assert time.monotonic() - t0 < 3.0
    assert old.closed
    seq = x.conn_events()
    assert ("CONNECTED", "DISCONNECTING") in seq and ("DISCONNECTING", "BACKOFF") in seq
    assert x.svc.last_snapshot.error_code == "CONNECTION_LOST"
    x.wait_state("NO_DEVICE")
    x.exists["ok"] = True
    x.ports.append(C1)
    x.svc.rescan("hotplug_add")
    x.wait_state("CONNECTED")
    assert x.factory.last is not old


def test_events_from_old_provider_ignored_after_teardown(h):
    x = h()
    x.wait_state("CONNECTED")
    old = x.factory.last
    x.ports.clear()
    old.drop().join()
    x.qtbot.waitUntil(lambda: x.state in ("BACKOFF", "NO_DEVICE"))
    n = len(x.observations)
    old.emit_packet(Observation(5, 1)).join()
    x.qtbot.wait(150)
    assert len(x.observations) == n


def test_reboot_same_interface_no_teardown(h):
    x = h()
    x.wait_state("CONNECTED")
    prov = x.factory.last
    prov.reboot(0.3)
    x.wait_state("DEVICE_REBOOTING")
    x.wait_state("CONNECTED")
    assert not prov.closed and len(x.factory.instances) == 1
    assert ("CONNECTED", "DEVICE_REBOOTING") in x.conn_events()
    assert ("DEVICE_REBOOTING", "CONNECTED") in x.conn_events()


def test_reboot_without_return_times_out(h):
    x = h(cfg=RadioConfig(link_probe_s=0, reboot_grace_s=1))
    x.wait_state("CONNECTED")
    x.factory.last.reboot(None)
    x.wait_state("DEVICE_REBOOTING")
    x.qtbot.waitUntil(lambda: ("DEVICE_REBOOTING", "DISCONNECTING") in x.conn_events(), timeout=3000)


def test_user_disconnect_goes_idle_and_stays(h):
    x = h()
    x.wait_state("CONNECTED")
    prov = x.factory.last
    x.svc.disconnect_radio()
    x.wait_state("IDLE")
    assert prov.closed
    time.sleep(0.6)
    assert x.state == "IDLE" and len(x.factory.instances) == 1
    x.svc.connect_radio()
    x.wait_state("CONNECTED")


def test_handshake_deadline_abandons_hung_constructor(h):
    x = h(autostart=False, cfg=RadioConfig(handshake_deadline_s=1, link_probe_s=0))
    x.script.block_forever.set()
    x.svc.start()
    x.wait_state("CONNECTING")
    x.qtbot.waitUntil(lambda: x.svc.last_snapshot.error_code == "HANDSHAKE_TIMEOUT", timeout=3000)
    hung = x.factory.instances[0]
    x.script.block_forever.clear()
    x.script.release.set()  # the hung constructor eventually "succeeds"
    x.wait_state("CONNECTED", 4000)
    x.qtbot.waitUntil(lambda: hung.closed, timeout=2000)  # stale success closed, not adopted
    assert x.worker._provider is not hung


def test_user_stop_during_connecting(h):
    x = h(autostart=False)
    x.script.block_forever.set()
    x.svc.start()
    x.wait_state("CONNECTING")
    x.svc.disconnect_radio()
    x.wait_state("IDLE")
    x.script.release.set()
    x.qtbot.waitUntil(lambda: x.factory.instances[0].closed, timeout=2000)
    assert x.state == "IDLE"


def test_watchdog_reader_died_silently(h):
    x = h()
    x.wait_state("CONNECTED")
    x.factory.last.alive = False  # no connection.lost published
    x.qtbot.waitUntil(lambda: ("CONNECTED", "DISCONNECTING") in x.conn_events(), timeout=2000)
    assert x.svc.last_snapshot.error_code in ("WATCHDOG", "CONNECTION_LOST")


def test_watchdog_device_node_vanished(h):
    x = h()
    x.wait_state("CONNECTED")
    x.exists["ok"] = False
    x.qtbot.waitUntil(lambda: ("CONNECTED", "DISCONNECTING") in x.conn_events(), timeout=2000)


def test_link_probe_failure_tears_down(h):
    x = h(cfg=RadioConfig(link_probe_s=1))
    x.wait_state("CONNECTED")
    x.script.heartbeat_error = OSError(5, "Input/output error")
    x.qtbot.waitUntil(lambda: x.svc.last_snapshot.error_code == "SERIAL_ERROR", timeout=3000)


def test_autoconnect_disabled_starts_idle(h):
    x = h(cfg=RadioConfig(autoconnect=False))
    x.qtbot.wait(300)
    assert x.state == "IDLE" and x.script.attempts == []
    x.svc.connect_radio()
    x.wait_state("CONNECTED")


def test_discovery_exception_is_error_then_retry(h):
    x = h(autostart=False)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("sysfs exploded")
        return [C1]

    x.worker._discover = flaky
    x.svc.start()
    x.wait_state("CONNECTED")
    assert ("SCANNING", "ERROR") in x.conn_events()


def test_worker_never_blocks_gui_during_slow_connect(h, qtbot):
    x = h(autostart=False)
    x.script.connect_delay = 1.0
    ticks = []
    from PySide6.QtCore import QTimer

    t = QTimer()
    t.timeout.connect(lambda: ticks.append(time.monotonic()))
    t.start(50)
    x.svc.start()
    x.wait_state("CONNECTED", 4000)
    t.stop()
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert gaps and max(gaps) < 0.2


def test_shutdown_closes_provider(h):
    x = h()
    x.wait_state("CONNECTED")
    prov = x.factory.last
    x.svc.stop()
    assert prov.closed
    assert not x.svc.thread.isRunning()
