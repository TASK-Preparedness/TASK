# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 46-50: Phase 1 behaviour that 0.1.1 had but did not test (F4/K4).

Added before any Phase 2 feature code; they pass against 0.1.1 unchanged.
"""

import os
import stat
import tempfile
from pathlib import Path

from task_core import api as api_module
from task_core.bus import RING_SIZE

from conftest import LineClient, ublox


def test_46_socket_mode_group_and_parent_dir(env, monkeypatch):
    calls = []

    class FakeGroup:
        gr_gid = 4242

    import grp

    monkeypatch.setattr(grp, "getgrnam", lambda name: calls.append(("getgrnam", name)) or FakeGroup())
    real_chown = os.chown

    def spy_chown(path, uid, gid):
        calls.append(("chown", str(path), uid, gid))

    monkeypatch.setattr(os, "chown", spy_chown)
    base = Path(tempfile.mkdtemp(prefix="rn", dir="/tmp"))
    old_umask = os.umask(0o022)
    try:
        state = base / "state"
        state.mkdir()
        core = env(state_dir=state, do_open=False)
        core.config.socket = str(base / "run" / "rain" / "core.sock")
        core.open()
    finally:
        os.umask(old_umask)
    sock_path = Path(core.config.socket)
    mode = stat.S_IMODE(sock_path.stat().st_mode)
    assert mode == 0o660
    assert stat.S_IMODE(sock_path.parent.stat().st_mode) == 0o755
    assert ("getgrnam", "rain-core") in calls
    assert ("chown", str(sock_path), -1, 4242) in calls
    monkeypatch.setattr(os, "chown", real_chown)
    client = LineClient(core.config.socket)
    assert client.request("core.health")["result"]["ok"] is True
    client.close()


def test_47_v1_path_rejects_other_versions(env):
    core = env()
    client = LineClient(core.config.socket)
    for raw in (
        b'{"v":0,"id":"a","method":"core.health"}\n',
        b'{"v":"1","id":"a","method":"core.health"}\n',
        b'{"id":"a","method":"core.health"}\n',
        b'{"v":3,"id":"a","method":"core.health"}\n',
        b'{"v":null,"id":"a","method":"core.health"}\n',
    ):
        client.send_raw(raw)
        reply = client.read_json()
        assert reply == {
            "v": 1,
            "id": "a",
            "ok": False,
            "error": {"code": "bad-request", "message": "unsupported version"},
        }
    client.close()


def test_48_events_recent_over_socket(env):
    public_uid = os.geteuid() + 7000
    holder = {"uid": os.geteuid()}
    core = env(
        peers={os.geteuid(): "operator"},
        peer_uid_fn=lambda _conn: holder["uid"],
    )
    holder["uid"] = public_uid
    public = LineClient(core.config.socket)
    assert public.request("core.health")["ok"] is True
    denied = public.request("events.recent")
    assert denied["error"] == {"code": "forbidden", "message": "events.recent requires operator"}
    holder["uid"] = os.geteuid()
    operator = LineClient(core.config.socket)
    for index in range(RING_SIZE + 25):
        core.bus.publish("device.appeared", "devmgr", {"n": index})
    events = operator.request("events.recent")["result"]["events"]
    assert len(events) == RING_SIZE == 200
    numbers = [event["data"]["n"] for event in events]
    assert numbers == list(range(25, RING_SIZE + 25))
    assert all(set(event) == {"v", "id", "topic", "time", "source", "data"} for event in events)
    public.close()
    operator.close()


def test_49_invalid_logical_device_everywhere(env):
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    expected = {"code": "invalid-logical-device", "message": "invalid logical device"}
    assert client.request("device.assign", {"logical": "gps.secondary", "device_id": device_id})["error"] == expected
    assert client.request("device.unassign", {"logical": "gps.secondary"})["error"] == expected
    assert client.request("device.get", {"logical": "gps.secondary"})["error"] == expected
    client.close()


def test_50_unassign_event_shape(env):
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assert client.request("device.assign", {"logical": "gps.primary", "device_id": device_id})["ok"]
    start = len(client.request("events.recent")["result"]["events"])
    result = client.request("device.unassign", {"logical": "gps.primary"})
    assert result["result"] == {"logical": "gps.primary", "device_id": None}
    events = client.request("events.recent")["result"]["events"][start:]
    unassigned = [event for event in events if event["topic"] == "device.unassigned"]
    assert len(unassigned) == 1
    assert unassigned[0]["data"] == {"logical": "gps.primary"}
    assert "id" not in unassigned[0]["data"]
    client.close()


def test_api_constants_unchanged():
    assert api_module.MAX_CLIENTS == 8
    assert api_module.MAX_REQUEST == 65536
    assert api_module.MAX_RESPONSE == 262144
    assert api_module.IDLE_TIMEOUT == 30
