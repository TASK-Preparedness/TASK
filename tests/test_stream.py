# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 4 and 24-30: event rings, streams, events.since."""

import os
import socket
import threading
import time

from conftest import LineClient
from p2fixtures import CP2102_ID, SDR_ID, FakeClock, V2Client, login, p2env, rtlsdr  # noqa: F401


def _frames_until(client, predicate, timeout=3.0):
    frames = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = client.try_read(max(0.05, deadline - time.monotonic()))
        if frame is None:
            break
        frames.append(frame)
        if predicate(frame):
            break
    return frames


def test_04_v1_event_view_is_the_0_1_1_ring(p2env):
    core = p2env()
    token = login(core)
    admin = V2Client(core.config.socket)
    admin.call("device.assign", {"logical": "gps.primary", "device_id": CP2102_ID, "confirm_displace": True},
               session=token)
    v1 = LineClient(core.config.socket)
    events = v1.request("events.recent")["result"]["events"]
    topics = {event["topic"] for event in events}
    assert "device.displaced" not in topics and "device.counts" not in topics
    assert all(set(event) == {"v", "id", "topic", "time", "source", "data"} for event in events)
    for index in range(250):
        core.bus.publish("device.appeared", "devmgr", {"n": index})
    before = v1.request("events.recent")["result"]["events"]
    for index in range(500):
        core.bus.publish("device.counts", "devmgr", {"total": index, "connected": 0, "disconnected": index})
        core.bus.publish("device.displaced", "devmgr", {"logical": "x", "id": "y", "by": {}})
    after = v1.request("events.recent")["result"]["events"]
    assert after == before and len(after) == 200
    assert [event["data"]["n"] for event in after] == list(range(50, 250))
    v2_ring = admin.call("events.recent", session=token)["result"]["events"]
    assert {event["topic"] for event in v2_ring} == {"device.counts", "device.displaced"}
    v1.close()
    admin.close()


def test_24_subscribe_and_live_frames(p2env):
    core = p2env(devices=[])
    token = login(core, "op")
    stream = V2Client(core.config.socket)
    reply = stream.call("events.subscribe", {"topics": []}, session=token)["result"]
    assert reply["boot_id"] == core.bus.boot_id and reply["seq"] == core.bus.last_seq()
    assert reply["role"] == "operator" and reply["topics"] == []
    started = time.monotonic()
    core._fake.add(rtlsdr())
    frames = _frames_until(stream, lambda f: f.get("event", {}).get("topic") == "device.appeared", 1.0)
    assert time.monotonic() - started < 1.0
    assert frames[-1]["event"]["topic"] == "device.appeared"
    more = _frames_until(stream, lambda f: f.get("event", {}).get("topic") == "device.counts", 1.0)
    seqs = [f["event"]["seq"] for f in frames + more]
    assert seqs == list(range(reply["seq"] + 1, reply["seq"] + 1 + len(seqs)))
    stream.close()


def test_25_stream_role_filtering(p2env):
    core = p2env()
    token = login(core, "op")
    public = V2Client(core.config.socket)
    operator = V2Client(core.config.socket)
    public.call("events.subscribe", {})
    operator.call("events.subscribe", {}, session=token)
    gps = core._fake.devices[0]
    core._fake.remove(gps)
    core._fake.add(gps)
    core.bus.publish("device.displaced", "devmgr", {"logical": "gps.primary", "id": "x", "by": {}})
    core.bus.publish("core.marker", "test", {})
    pub = _frames_until(public, lambda f: f.get("event", {}).get("topic") == "core.marker")
    op = _frames_until(operator, lambda f: f.get("event", {}).get("topic") == "core.marker")
    pub_topics = [f["event"]["topic"] for f in pub if "event" in f]
    op_topics = [f["event"]["topic"] for f in op if "event" in f]
    assert all(t.startswith(("core.", "module.", "capability.")) or t == "device.counts" for t in pub_topics)
    assert "device.counts" in pub_topics and "capability.changed" in pub_topics
    assert {"device.disappeared", "device.appeared", "device.counts", "device.displaced"} <= set(op_topics)
    # a topic prefix filter narrows further
    narrow = V2Client(core.config.socket)
    narrow.call("events.subscribe", {"topics": ["capability."]}, session=token)
    core._fake.remove(gps)
    core.bus.publish("capability.marker", "test", {})
    got = _frames_until(narrow, lambda f: f.get("event", {}).get("topic") == "capability.marker")
    assert all(f["event"]["topic"].startswith("capability.") for f in got if "event" in f)
    for client in (public, operator, narrow):
        client.close()


def test_26_heartbeat_after_quiet_interval(p2env):
    core = p2env(heartbeat_interval=0.3)
    stream = V2Client(core.config.socket)
    seq = stream.call("events.subscribe", {})["result"]["seq"]
    started = time.monotonic()
    frame = stream.try_read(3)
    elapsed = time.monotonic() - started
    assert set(frame) == {"v", "heartbeat"} and frame["v"] == 2
    assert frame["heartbeat"]["seq"] == seq and frame["heartbeat"]["time"].endswith("Z")
    assert 0.25 <= elapsed < 2.0
    from task_core.stream import HEARTBEAT_INTERVAL

    assert HEARTBEAT_INTERVAL == 10.0
    stream.close()


PROBER = r"""
import json, socket, sys, time
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sys.argv[1])
s.settimeout(5)
buf = b""
def call():
    global buf
    s.sendall(b'{"v":2,"id":"h","method":"core.health"}\n')
    while b"\n" not in buf:
        buf += s.recv(65536)
    line, buf = buf.split(b"\n", 1)
    assert json.loads(line)["ok"] is True
call()
print("ready", flush=True)
sys.stdin.readline()
lat = []
end = time.monotonic() + float(sys.argv[2])
while time.monotonic() < end:
    t = time.monotonic()
    call()
    lat.append(time.monotonic() - t)
    time.sleep(0.002)
print(json.dumps(lat), flush=True)
"""


def test_27_overflow_publish_never_blocks_and_rpc_stays_fast(p2env):
    """The RPC client runs in its own process, as the console and CLI do."""
    import json
    import subprocess
    import sys

    core = p2env()
    token = login(core, "op")
    stalled = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    stalled.connect(core.config.socket)
    stalled.sendall(b'{"v":2,"id":"s","method":"events.subscribe","params":{},"session":"%s"}\n' % token.encode())
    healthy = V2Client(core.config.socket)
    healthy.call("events.subscribe", {"topics": ["core."]})
    prober = subprocess.Popen([sys.executable, "-c", PROBER, core.config.socket, "1.0"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert prober.stdout.readline().strip() == "ready"
    prober.stdin.write("go\n")
    prober.stdin.flush()
    time.sleep(0.05)
    worst = 0.0
    burst_started = time.monotonic()
    for index in range(10000):
        started = time.monotonic()
        core.bus.publish("test.burst", "test", {"n": index, "pad": "x" * 64})
        worst = max(worst, time.monotonic() - started)
    burst = time.monotonic() - burst_started
    latencies = json.loads(prober.stdout.readline())
    prober.wait(5)
    assert worst < 0.05, worst
    assert burst < 1.0, burst  # the whole burst fell inside the probe window
    assert len(latencies) > 50 and max(latencies) < 0.1, max(latencies)
    # the stalled client now reads: some frames, then stream_end overflow, then EOF
    stalled.settimeout(5)
    data = b""
    while True:
        chunk = stalled.recv(65536)
        if not chunk:
            break
        data += chunk
    last = data.strip().split(b"\n")[-1]
    assert b'"stream_end":{"reason":"overflow"' in last
    assert data.count(b'"event"') < 10000
    core.bus.publish("core.after", "test", {})
    after = _frames_until(healthy, lambda f: f.get("event", {}).get("topic") == "core.after")
    assert after and after[-1]["event"]["topic"] == "core.after"
    stalled.close()
    healthy.close()


def test_28_limits(p2env):
    core = p2env(idle_timeout=0.4)
    streams = []
    for _ in range(4):
        client = V2Client(core.config.socket)
        assert client.call("events.subscribe", {})["ok"] is True
        streams.append(client)
    fifth = V2Client(core.config.socket)
    assert fifth.call("events.subscribe", {})["error"] == {"code": "busy", "message": "too many streams"}
    fifth.close()
    time.sleep(0.1)
    held = [LineClient(core.config.socket, timeout=5) for _ in range(8)]
    for client in held:
        assert client.request("core.health")["ok"] is True
    extra = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    extra.settimeout(2)
    extra.connect(core.config.socket)
    assert extra.recv(16) == b""
    extra.close()
    # RPC clients are closed at the idle timeout; streams are exempt
    time.sleep(1.0)
    for client in held:
        client.sock.settimeout(2)
        assert client.sock.recv(16) == b""
    core.bus.publish("core.marker", "test", {})
    for client in streams:
        frames = _frames_until(client, lambda f: f.get("event", {}).get("topic") == "core.marker")
        assert frames and frames[-1]["event"]["topic"] == "core.marker"
    from task_core.api import IDLE_TIMEOUT, MAX_CLIENTS

    assert (IDLE_TIMEOUT, MAX_CLIENTS) == (30, 8)
    for client in streams:
        client.close()


def test_29_events_since(p2env):
    core = p2env()
    token = login(core, "op")
    client = V2Client(core.config.socket)
    boot = core.bus.boot_id
    start = core.bus.last_seq()
    core.bus.publish("device.appeared", "devmgr", {"id": "dev_x"})
    core.bus.publish("capability.changed", "caps", {"name": "gps.position"})
    op = client.call("events.since", {"seq": start, "boot_id": boot}, session=token)["result"]
    assert op["gap"] is False and [e["seq"] for e in op["events"]] == [start + 1, start + 2]
    pub = client.call("events.since", {"seq": start, "boot_id": boot})["result"]
    assert [e["topic"] for e in pub["events"]] == ["capability.changed"]
    other = client.call("events.since", {"seq": start, "boot_id": "0" * 32})["result"]
    assert other["gap"] is True and other["boot_id"] == boot
    for index in range(250):
        core.bus.publish("core.tick", "test", {"n": index})
    stale = client.call("events.since", {"seq": start, "boot_id": boot})["result"]
    assert stale["gap"] is True and len(stale["events"]) == 200
    fresh = client.call("events.since", {"seq": stale["seq"] - 5, "boot_id": boot})["result"]
    assert fresh["gap"] is False and len(fresh["events"]) == 5
    for bad in ({"seq": -1, "boot_id": boot}, {"seq": True, "boot_id": boot}, {"seq": 1}):
        assert client.call("events.since", bad)["error"]["code"] == "bad-request"
    client.close()


def _end_reason(client, timeout=3.0):
    frames = _frames_until(client, lambda f: "stream_end" in f, timeout)
    ends = [f["stream_end"]["reason"] for f in frames if "stream_end" in f]
    return ends[-1] if ends else None


def test_30_session_end_and_shutdown(p2env):
    clock = FakeClock()
    core = p2env(clock=clock, stream_check_interval=0.05)
    rpc = V2Client(core.config.socket)
    # logout
    token = login(core)
    stream = V2Client(core.config.socket)
    stream.call("events.subscribe", {}, session=token)
    rpc.call("session.logout", session=token)
    assert _end_reason(stream) == "session-ended"
    assert rpc.call("core.health", session=token)["error"]["code"] == "unauthenticated"
    stream.close()
    # idle expiry
    token = login(core)
    stream = V2Client(core.config.socket)
    stream.call("events.subscribe", {}, session=token)
    clock.advance(7201)
    assert _end_reason(stream) == "session-ended"
    assert rpc.call("core.health", session=token)["error"]["code"] == "unauthenticated"
    stream.close()
    # absolute expiry, with activity every hour
    token = login(core)
    stream = V2Client(core.config.socket)
    stream.call("events.subscribe", {}, session=token)
    for _ in range(12):
        clock.advance(3600)
        assert rpc.call("core.health", session=token)["ok"] is True
    clock.advance(1)
    assert _end_reason(stream) == "session-ended"
    stream.close()
    # shutdown
    public = V2Client(core.config.socket)
    public.call("events.subscribe", {})
    core.close()
    frames = _frames_until(public, lambda f: "stream_end" in f)
    assert frames[-2]["event"]["topic"] == "core.stopping"
    assert frames[-1]["stream_end"]["reason"] == "core-stopping"
    public.close()
    rpc.close()


def test_27_event_ids_keep_the_011_shape(p2env):
    """Event ids are generated without releasing the GIL (test 27 latency); the shape stays "evt_" + 16 hex."""
    import re

    core = p2env()
    ids = [core.bus.publish("test.id", "test", {})["id"] for _ in range(2000)]
    assert all(re.fullmatch(r"evt_[0-9a-f]{16}", value) for value in ids)
    assert len(set(ids)) == len(ids)
    recent = V2Client(core.config.socket)
    reply = recent.call("events.recent", version=1)  # v1 view via [peers], as task-smoke sees it
    recent.close()
    assert reply["ok"] is True and reply["result"]["events"]
    assert all(re.fullmatch(r"evt_[0-9a-f]{16}", event["id"]) for event in reply["result"]["events"])
