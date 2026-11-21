# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""H1 regression: hot-unplug is reflected, and a dead udev monitor is not silent.

Joshua's Phase 2 hardware acceptance (2026-10-08): unplugging the RTL-SDR Blog V4
(0bda:2838, dev_ca4a208a9242de2c) left device.list at connected:true and produced
no device.disappeared and no device.counts, while udevd and task-core stayed active.

These tests drive the real UdevEnumerator (start, the rain-udev thread, _dispatch,
reconcile) with a stand-in pyudev Monitor, and read the results over the socket API.
The monitor can raise OSError(ENOBUFS) from poll() and can fail to open, which is
what pyudev 0.24 does when the netlink receive buffer overflows or the socket
cannot be created. Nothing here touches real hardware or a real netlink socket.
"""

import errno
import time

from conftest import LineClient
from h1_live import LiveContext, LiveEnumerator, _fast, wait_until
from p2fixtures import CP2102_ID, SDR_ID, UBLOX_ID, V2Client, fixture_devices_json, login, p2env  # noqa: F401
from test_hotplug_parent_dedup import (
    PORTS,
    by_id,
    cp2102,
    noise,
    rtlsdr,
    ublox,
)

SDR_PATH = PORTS[2][1]
GPS_PATH = PORTS[0][1]
GPS_TTY_PATH = f"{GPS_PATH}/{GPS_PATH.rsplit('/', 1)[-1]}:1.0/tty/ttyACM0"
ETH_PATH = "/sys/devices/platform/axi/1000120000.pcie/1f00100000.ethernet/net/eth0"
V1_HEALTH_KEYS = {"ok", "version", "uid", "uptime_seconds"}


def boot(env, devices, failures=None, state_dir=None, **options):
    context = LiveContext(devices)
    enum = LiveEnumerator(context, failures, **_fast(**options))
    core = env(enumerator_factory=lambda: enum, state_dir=state_dir)
    return core, enum, context, LineClient(core.config.socket)


def sdr_remove_events(sdr):
    """udev order observed for a bare usb_device unplug: unbind, then remove."""
    return [sdr.at("unbind"), sdr.at("remove")]


def strip_ids(device):
    """A remove event whose udev properties carry no identity at all."""
    bare = device.at("remove")
    bare.properties = {}
    return bare


def connected_ids(client):
    return sorted(item["id"] for item in client.request("device.list")["result"]["devices"]
                  if item["connected"])


def record(client, device_id):
    for item in client.request("device.list")["result"]["devices"]:
        if item["id"] == device_id:
            return item
    return None


def v1_topics(client, name):
    return [event["topic"] for event in client.request("events.recent")["result"]["events"]
            if event["topic"] == name]


def v2_counts(core):
    client = V2Client(core.config.socket)
    try:
        return client.call("device.counts")["result"]
    finally:
        client.close()


# ---------------------------------------------------------------- events


def test_h1_sdr_unplug_is_reflected_over_v1_and_v2(env):
    sdr = rtlsdr()
    gps, tty = ublox()
    core, enum, context, client = boot(env, [gps, tty, sdr])
    assert record(client, SDR_ID)["connected"] is True
    context.drop(sdr)
    context.push(*sdr_remove_events(sdr))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)
    assert record(client, SDR_ID)["devnode"] is None
    disappeared = [event for event in client.request("events.recent")["result"]["events"]
                   if event["topic"] == "device.disappeared" and event["data"]["id"] == SDR_ID]
    assert len(disappeared) == 1 and disappeared[0]["data"]["logical"] is None
    counts = v2_counts(core)
    assert counts == {"total": 2, "connected": 1, "disconnected": 1}
    assert record(client, UBLOX_ID)["connected"] is True  # unrelated device untouched


def test_h1_sdr_replug_keeps_the_same_id(env):
    sdr = rtlsdr()
    core, enum, context, client = boot(env, [sdr])
    context.drop(sdr)
    context.push(*sdr_remove_events(sdr))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)
    context.add(sdr)
    context.push(sdr.at("add"), sdr.at("bind"))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is True)
    assert record(client, SDR_ID)["devnode"] == "/dev/bus/usb/003/002"
    assert sorted(item["id"] for item in client.request("device.list")["result"]["devices"]) == [SDR_ID]


def test_h1_repeated_hotplug_cycles_do_not_accumulate(env):
    sdr = rtlsdr()
    core, enum, context, client = boot(env, [sdr])
    for _ in range(5):
        context.drop(sdr)
        context.push(*sdr_remove_events(sdr))
        assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)
        context.add(sdr)
        context.push(sdr.at("add"))
        assert wait_until(lambda: record(client, SDR_ID)["connected"] is True)
    assert sorted(item["id"] for item in client.request("device.list")["result"]["devices"]) == [SDR_ID]
    assert len(v1_topics(client, "device.disappeared")) == 5
    assert len(v1_topics(client, "device.appeared")) == 6  # startup plus five replugs


def test_h1_propertyless_remove_still_matches(env):
    """A remove event that lost ID_VENDOR_ID/ID_MODEL_ID/ID_SERIAL_SHORT must still
    disconnect the device it was announced as (identity comes from the stored record)."""
    sdr = rtlsdr()
    core, enum, context, client = boot(env, [sdr])
    context.drop(sdr)
    context.push(strip_ids(sdr))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)
    assert record(client, SDR_ID)["vid"] == "0bda" and record(client, SDR_ID)["serial"] == "00000001"


def test_h1_gps_unplug_and_replug_preserves_the_assignment(env, tmp_path):
    gps, tty = ublox()
    state = tmp_path / "state"
    state.mkdir()
    before = fixture_devices_json()
    (state / "devices.json").write_bytes(before)
    core, enum, context, client = boot(env, [gps, tty], state_dir=state)
    assert record(client, UBLOX_ID)["logical"] == "gps.primary"
    assert record(client, UBLOX_ID)["alias"] == "smoke"
    context.drop(gps)
    context.drop(tty)
    context.push(tty.at("remove"), gps.at("unbind"), strip_ids(gps))
    assert wait_until(lambda: record(client, UBLOX_ID)["connected"] is False)
    kept = record(client, UBLOX_ID)
    assert kept["logical"] == "gps.primary" and kept["alias"] == "smoke"
    assert (state / "devices.json").read_bytes() == before  # nothing is rewritten
    context.add(gps)
    context.add(tty)
    context.push(gps.at("add"), gps.at("bind"), tty.at("add"))
    assert wait_until(lambda: record(client, UBLOX_ID)["connected"] is True)
    back = record(client, UBLOX_ID)
    assert back["logical"] == "gps.primary" and back["alias"] == "smoke"
    assert back["devnode"] == "/dev/ttyACM0"
    assert (state / "devices.json").read_bytes() == before
    assert by_id(client, "dev_621b7d85c708289b") is None  # the parent does not linger


def test_h1_unrelated_devices_are_untouched_by_an_sdr_cycle(env):
    sdr = rtlsdr()
    gps, tty = ublox()
    cp, cp_tty = cp2102()
    net = noise()[-1]
    core, enum, context, client = boot(env, [gps, tty, cp, cp_tty, sdr, net])
    before = {item["id"]: item["connected"] for item in client.request("device.list")["result"]["devices"]}
    context.drop(sdr)
    context.push(*sdr_remove_events(sdr))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)
    after = {item["id"]: item["connected"] for item in client.request("device.list")["result"]["devices"]}
    del after[SDR_ID]
    assert after == {key: value for key, value in before.items() if key != SDR_ID}
    assert record(client, UBLOX_ID)["connected"] and record(client, CP2102_ID)["connected"]
    net_id = next(item["id"] for item in client.request("device.list")["result"]["devices"]
                  if item["subsystem"] == "net")
    assert after[net_id] is True


# ---------------------------------------------------------------- sessions


def boot_p2(p2env, devices, **options):
    """The Phase 2 environment (accounts dragon/op, sessions.toml, 0.1.1 devices.json)
    with the live enumerator instead of the fake one."""
    context = LiveContext(devices)
    enum = LiveEnumerator(context, **_fast(**options))
    core = p2env(do_open=False)
    core.enumerator_factory = lambda: enum
    core.open()
    return core, enum, context, LineClient(core.config.socket)


def test_h1_removal_reaches_active_v2_sessions_and_a_v1_client(p2env):
    """Removal while an operator and an administrator hold v2 streams and a v1 client is connected."""
    sdr = rtlsdr()
    gps, tty = ublox()
    core, enum, context, v1 = boot_p2(p2env, [gps, tty, sdr])
    admin_token = login(core, "dragon")
    admin = V2Client(core.config.socket)
    assert admin.call("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID, "alias": "sdr"},
                      session=admin_token)["ok"]
    assigned = (core.config.state_dir / "devices.json").read_bytes()
    admin_stream = V2Client(core.config.socket)
    assert admin_stream.call("events.subscribe", {"topics": []}, session=admin_token)["ok"]
    public_stream = V2Client(core.config.socket)
    assert public_stream.call("events.subscribe", {"topics": []})["ok"]
    token = login(core, "op")
    stream = V2Client(core.config.socket)
    assert stream.call("events.subscribe", {"topics": ["device."]}, session=token)["ok"]
    v1.request("core.health")  # the v1 client stays connected throughout
    context.drop(sdr)
    context.push(*sdr_remove_events(sdr))
    seen = []
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not {"device.disappeared", "device.counts"} <= set(seen):
        frame = stream.try_read(0.2)
        if frame and "event" in frame:
            seen.append(frame["event"]["topic"])
    assert "device.disappeared" in seen and "device.counts" in seen
    assert v1.request("device.get", {"id": SDR_ID})["result"]["device"]["connected"] is False
    health = v1.request("core.health")["result"]
    assert set(health) == V1_HEALTH_KEYS  # v1 wire format unchanged
    v1_disappeared = [event for event in v1.request("events.recent")["result"]["events"]
                      if event["topic"] == "device.disappeared"]
    assert v1_disappeared[-1]["data"] == {"id": SDR_ID, "logical": "sdr.primary"}
    assert "seq" not in v1_disappeared[-1]
    assert not v1_topics(v1, "device.counts")  # v2-only topic stays out of the v1 ring
    admin_topics, public_topics = _drain(admin_stream), _drain(public_stream)
    assert "device.disappeared" in admin_topics and "device.counts" in admin_topics
    assert "device.counts" in public_topics and "device.disappeared" not in public_topics
    for session in (admin_token, token):
        check = V2Client(core.config.socket)
        assert check.call("session.whoami", session=session)["ok"]  # sessions survive the removal
        check.close()
    gone = admin.call("device.get", {"id": SDR_ID}, session=admin_token)["result"]["device"]
    assert gone["connected"] is False and gone["logical"] == "sdr.primary"
    assert (core.config.state_dir / "devices.json").read_bytes() == assigned
    context.add(sdr)
    context.push(sdr.at("add"), sdr.at("bind"))
    assert wait_until(lambda: record(v1, SDR_ID)["connected"] is True)
    assert record(v1, SDR_ID)["logical"] == "sdr.primary"
    assert (core.config.state_dir / "devices.json").read_bytes() == assigned
    for client in (stream, admin_stream, public_stream, admin):
        client.close()


def _drain(client, quiet=0.4):
    topics = []
    while True:
        frame = client.try_read(quiet)
        if frame is None:
            return topics
        if "event" in frame:
            topics.append(frame["event"]["topic"])


def test_h1_v2_health_reports_the_monitor_and_v1_health_does_not(env):
    core, enum, context, v1 = boot(env, [rtlsdr()])
    assert wait_until(lambda: enum.status()["state"] == "running")
    v2 = V2Client(core.config.socket)
    hotplug = v2.call("core.health")["result"]["hotplug"]
    assert hotplug["state"] == "running" and hotplug["restarts"] == 0 and hotplug["last_error"] is None
    assert set(v1.request("core.health")["result"]) == V1_HEALTH_KEYS
    v2.close()


# ---------------------------------------------------------------- monitor failure


def test_h1_enobufs_restarts_the_monitor_and_reconciles(env):
    """poll() raising ENOBUFS (pyudev re-raises it) must not end hot-plug for good:
    the monitor reopens and a removal that happened while it was down is reconciled."""
    sdr = rtlsdr()
    core, enum, context, client = boot(env, [sdr])
    assert wait_until(lambda: enum.status()["events"] >= 0 and enum.opens)
    context.blocked = True
    assert wait_until(lambda: enum.status()["restarts"] >= 1)
    assert enum.status()["last_error"] == "ENOBUFS"
    context.drop(sdr)
    context.push(*sdr_remove_events(sdr))  # lost: dropped with the overflow
    context.blocked = False
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False, timeout=4)
    assert enum.status()["missed"] >= 1
    assert wait_until(lambda: enum.status()["state"] == "running")
    # and live events work again afterwards
    context.add(sdr)
    context.push(sdr.at("add"))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is True)


def test_h1_monitor_that_cannot_open_is_degraded_and_still_tracks_removal(env):
    sdr = rtlsdr()
    core, enum, context, client = boot(
        env, [sdr], failures=[OSError(errno.EPERM, "operation not permitted")],
        restart_backoff=(60.0,), degraded_interval=0.05,
    )
    assert wait_until(lambda: enum.status()["state"] == "degraded")
    v2 = V2Client(core.config.socket)
    hotplug = v2.call("core.health")["result"]["hotplug"]
    assert hotplug["state"] == "degraded" and hotplug["last_error"] == "EPERM"
    v2.close()
    context.drop(sdr)
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False, timeout=4)
    assert record(client, SDR_ID)["vid"] == "0bda"


def test_h1_startup_enumeration_works_when_the_monitor_cannot_open(env):
    sdr = rtlsdr()
    gps, tty = ublox()
    core, enum, context, client = boot(
        env, [gps, tty, sdr], failures=[OSError(errno.EACCES, "permission denied")],
        restart_backoff=(60.0,),
    )
    assert connected_ids(client) == sorted([SDR_ID, UBLOX_ID])
    assert wait_until(lambda: enum.status()["state"] == "degraded")
    assert enum.status()["last_error"] == "EACCES"


def test_h1_monitor_is_opened_before_the_scan(env):
    """A device plugged while the initial scan runs must not be lost (0.2.0 opened
    the monitor only after the scan, so its add event went nowhere)."""
    sdr = rtlsdr()
    order = []

    class Scanning(LiveContext):
        def list_devices(self, subsystem):
            order.append(("scan", subsystem))
            listed = super().list_devices(subsystem)
            if subsystem == "usb" and sdr not in self.devices:
                self.devices.append(sdr)  # plugged just after the usb list was taken
                self.push(sdr.at("add"), sdr.at("bind"))
            return listed

    context = Scanning([])
    enum = LiveEnumerator(context, **_fast(rescan_interval=0))
    core = env(enumerator_factory=lambda: enum)
    client = LineClient(core.config.socket)
    assert order and order[0] == ("scan", "tty")
    assert wait_until(lambda: (record(client, SDR_ID) or {}).get("connected") is True)
    assert enum.status()["missed"] == 0  # delivered by the monitor, not by a rescan
    client.close()


def test_h1_deaf_monitor_is_backstopped_by_a_confirmed_rescan(env):
    """A monitor that opens but never delivers (as a socket that stopped receiving
    would) is backstopped: a difference seen by two rescans is applied and counted."""
    sdr = rtlsdr()
    core, enum, context, client = boot(env, [sdr], rescan_interval=0.1, confirm_delay=0.05)
    context.drop(sdr)  # no event is ever delivered
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False, timeout=4)
    status = enum.status()
    assert status["missed"] == 1 and status["state"] == "running" and status["restarts"] == 0


def test_h1_a_single_rescan_does_not_preempt_udev(env):
    """While the monitor runs, one rescan alone never applies a change (udev may still
    be processing the event); the second, CONFIRM_DELAY later, does."""
    sdr = rtlsdr()
    core, enum, context, client = boot(env, [sdr], rescan_interval=0)
    context.drop(sdr)
    pending = enum._resync(confirm=True)
    assert pending is not None
    assert record(client, SDR_ID)["connected"] is True
    assert enum._resync(confirm=True, pending=pending) is None
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)


def test_h1_dispatch_error_is_counted_and_monitoring_continues(env, monkeypatch):
    sdr = rtlsdr()
    gps, tty = ublox()
    core, enum, context, client = boot(env, [gps, tty, sdr], rescan_interval=0)
    original = enum._on_disappear
    calls = []

    def flaky(raw, replaced=False):
        calls.append(raw)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return original(raw, replaced=replaced)

    enum._on_disappear = flaky
    context.drop(tty)
    context.push(tty.at("remove"))  # fails inside the callback
    assert wait_until(lambda: enum.status()["dispatch_errors"] == 1)
    context.drop(sdr)
    context.push(*sdr_remove_events(sdr))
    assert wait_until(lambda: record(client, SDR_ID)["connected"] is False)
    assert enum.status()["state"] == "running"


def test_h1_close_stops_the_monitor_thread(env):
    core, enum, context, client = boot(env, [rtlsdr()])
    assert enum._thread.is_alive()
    client.close()
    core.close()
    enum._thread.join(2)
    assert not enum._thread.is_alive()
    assert enum.status()["state"] == "stopped"


def test_h1_removal_is_resolved_against_the_announced_record():
    from task_core.devices import RawDevice
    from task_core.enumerator import apply_event, seed_state

    announced = RawDevice(devnode="/dev/bus/usb/003/002", vid="0bda", pid="2838", serial="00000001",
                          subsystem="usb", bus_path="platform-xhci-hcd.1-usb-0:1")
    tty = RawDevice(devnode="/dev/ttyACM0", by_id="/dev/serial/by-id/x-if00", subsystem="usb-serial")
    net = RawDevice(subsystem="net", mac="2c:cf:67:00:00:01")
    state = seed_state([(announced, SDR_PATH, None), (tty, GPS_TTY_PATH, GPS_PATH), (net, ETH_PATH, None)])
    bare = RawDevice(subsystem="usb", bus_path="3-1")
    assert apply_event(state, bare, SDR_PATH, None, "remove") == [("disappear", announced)]
    assert apply_event(state, RawDevice(subsystem="usb-serial"), GPS_TTY_PATH, None, "remove") == [
        ("disappear", tty)]
    assert GPS_PATH not in state.serial_parents  # the stored parent is released
    assert apply_event(state, RawDevice(subsystem="net"), ETH_PATH, None, "remove") == [("disappear", net)]
    assert state.known_paths() == set()


def test_h1_health_without_a_reporting_enumerator(env):
    core = env(devices=[])  # FakeEnumerator: no status()
    v2 = V2Client(core.config.socket)
    assert v2.call("core.health")["result"]["hotplug"] == {"state": "unknown"}
    v2.close()


def test_h1_removal_during_startup_is_not_lost(env):
    """A device listed by the scan and removed before Core registered the list: the
    queued remove is delivered only after registration (begin()), so it is not dropped
    as 'unknown device' and the record does not stay connected."""
    sdr = rtlsdr()

    class Scanning(LiveContext):
        def list_devices(self, subsystem):
            listed = super().list_devices(subsystem)
            if subsystem == "usb" and sdr in self.devices:
                self.devices.remove(sdr)  # unplugged right after the usb list was taken
                self.push(*sdr_remove_events(sdr))
            return listed

    context = Scanning([sdr])
    enum = LiveEnumerator(context, **_fast(rescan_interval=0))
    core = env(enumerator_factory=lambda: enum)
    client = LineClient(core.config.socket)
    assert wait_until(lambda: (record(client, SDR_ID) or {}).get("connected") is False)
    assert enum.status()["missed"] == 0
    client.close()
