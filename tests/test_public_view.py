# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 36-40: the D5 public view is enforced by task-core."""

import json
import os
import threading
import time

from conftest import LineClient
from p2fixtures import (CP2102_ID, SDR_ID, UBLOX_ID, V2Client, identifying_findings, login, p2env,  # noqa: F401
                        rtlsdr, ublox)

PUBLIC_CALLS = [("core.protocol", {}), ("core.health", {}), ("module.list", {}), ("capability.list", {}),
                ("device.counts", {}), ("session.whoami", {})]


def _collect_stream(client, sink, stop):
    while not stop.is_set():
        frame = client.try_read(0.2)
        if frame is not None:
            sink.append(frame)


def test_36_no_identifying_data_via_any_public_method(p2env):
    core = p2env()
    public = V2Client(core.config.socket)
    stream = V2Client(core.config.socket)
    subscribed = stream.call("events.subscribe", {"topics": []})
    assert subscribed["result"]["role"] == "public"
    frames, stop = [], threading.Event()
    reader = threading.Thread(target=_collect_stream, args=(stream, frames, stop), daemon=True)
    reader.start()
    results = [subscribed]
    for method, params in PUBLIC_CALLS:
        results.append(public.call(method, params))
    # hot-plug cycle and an administrator assign
    fake = core._fake
    gps = fake.devices[0]
    fake.remove(gps)
    fake.add(gps)
    token = login(core)
    admin = V2Client(core.config.socket)
    assert admin.call("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID, "alias": "smoke"},
                      session=token)["ok"]
    assert admin.call("device.assign", {"logical": "gps.primary", "device_id": CP2102_ID, "confirm_displace": True},
                      session=token)["ok"]
    time.sleep(0.5)
    since = public.call("events.since", {"seq": 0, "boot_id": core.bus.boot_id})
    results.append(since)
    stop.set()
    reader.join(2)
    results += frames
    assert any("event" in frame and frame["event"]["topic"] == "device.counts" for frame in frames)
    assert since["result"]["events"], "events.since returned events"
    for item in results:
        assert identifying_findings(item) == [], json.dumps(item)[:400]
    # the operator view of the same ring does contain device data (sanity check of the scan)
    full = admin.call("events.recent", session=token)
    assert identifying_findings(full) != []
    for client in (public, stream, admin):
        client.close()


def test_37_operator_methods_refuse_public(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    cases = [("device.list", {}), ("device.get", {"id": UBLOX_ID}), ("device.get", {"logical": "gps.primary"}),
             ("events.recent", {}), ("device.assign", {"logical": "gps.primary", "device_id": SDR_ID}),
             ("device.unassign", {"logical": "gps.primary"})]
    for method, params in cases:
        reply = client.call(method, params)
        assert reply["error"]["code"] == "forbidden"
        assert identifying_findings(reply) == []
    client.close()


def _counts_match(client, token):
    listing = client.call("device.list", session=token)["result"]["devices"]
    counts = client.call("device.counts")["result"]
    connected = sum(1 for d in listing if d["connected"])
    assert counts == {"total": len(listing), "connected": connected, "disconnected": len(listing) - connected}
    return counts


def test_38_counts_follow_device_list_and_events(p2env):
    core = p2env()
    token = login(core, "op")
    client = V2Client(core.config.socket)
    stream = V2Client(core.config.socket)
    stream.call("events.subscribe", {})
    frames, stop = [], threading.Event()
    reader = threading.Thread(target=_collect_stream, args=(stream, frames, stop), daemon=True)
    reader.start()
    seen = [_counts_match(client, token)]
    fake = core._fake
    gps, sdr = fake.devices[0], fake.devices[1]
    steps = [lambda: fake.remove(gps), lambda: fake.remove(sdr), lambda: fake.add(sdr), lambda: fake.add(gps)]
    for step in steps:
        step()
        seen.append(_counts_match(client, token))
    assert seen[1] == {"total": 3, "connected": 2, "disconnected": 1}  # disconnected assigned record kept
    time.sleep(0.6)
    stop.set()
    reader.join(2)
    counts_events = [f["event"]["data"] for f in frames if "event" in f and f["event"]["topic"] == "device.counts"]
    assert counts_events == seen[1:]
    topics = {f["event"]["topic"] for f in frames if "event" in f}
    assert "capability.changed" in topics
    assert {t for t in topics if t.startswith("device.")} == {"device.counts"}
    client.close()
    stream.close()


def test_39_redacted_module_list(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    public = client.call("module.list")["result"]
    operator = client.call("module.list", session=login(core, "op"))["result"]
    admin = client.call("module.list", session=login(core, "dragon"))["result"]
    expected = {"modules": [{k: v for k, v in m.items() if k != "logical_devices"} for m in operator["modules"]]}
    assert public == expected
    assert any("logical_devices" in m for m in operator["modules"])
    v1 = LineClient(core.config.socket)
    v1_modules = v1.request("module.list")["result"]
    assert operator == admin == v1_modules
    v1.close()
    client.close()


def test_40_v1_public_exposure_pinned(p2env):
    core = p2env(peers={os.geteuid() + 1: "administrator"})  # the test uid is public in v1
    v1 = LineClient(core.config.socket)
    health = v1.request("core.health")["result"]
    assert set(health) == {"ok", "version", "uid", "uptime_seconds"}
    modules = v1.request("module.list")["result"]["modules"]
    assert all("logical_devices" in module for module in modules)
    assert any("gps.primary" in module["logical_devices"] for module in modules)
    caps = v1.request("capability.list")["result"]["capabilities"]
    assert all(set(item) == {"name", "kind", "status"} for item in caps)
    for method in ("device.list", "device.get", "device.assign", "device.unassign", "events.recent"):
        assert v1.request(method, {"id": UBLOX_ID})["error"]["code"] == "forbidden"
    v1.close()
