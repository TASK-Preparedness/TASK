# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 41 and 42: displacement (K1) in v2 and unchanged v1."""

import json
import os
from pathlib import Path

from conftest import LineClient
from p2fixtures import (CP2102_ID, SDR_ID, UBLOX_ID, V2Client, fixture_devices_json, login,  # noqa: F401
                        p2env)

GOLDEN = Path(__file__).resolve().parent / "golden" / "v1_transcript_0.1.1.json"


def _topics_since(client, token, seq):
    events = client.call("events.since", {"seq": seq, "boot_id": "x"}, session=token)
    return events


def test_41_v2_displacement(p2env):
    core = p2env()
    path = core.config.state_dir / "devices.json"
    token = login(core)
    client = V2Client(core.config.socket)
    # (a) gps.primary is held by the u-blox
    before_bytes, before_inode = path.read_bytes(), os.stat(path).st_ino
    seq = core.bus.last_seq()
    refused = client.call("device.assign", {"logical": "gps.primary", "device_id": CP2102_ID}, session=token)
    assert refused["error"] == {"code": "would-displace", "message": "gps.primary is held by " + UBLOX_ID}
    assert path.read_bytes() == before_bytes and os.stat(path).st_ino == before_inode
    assert core.bus.last_seq() == seq
    # (b) the u-blox already holds gps.primary; giving it sdr.primary would drop that
    refused = client.call("device.assign", {"logical": "sdr.primary", "device_id": UBLOX_ID}, session=token)
    assert refused["error"]["code"] == "would-displace" and "gps.primary" in refused["error"]["message"]
    assert path.read_bytes() == before_bytes and core.bus.last_seq() == seq
    # same device, same logical (alias change): not a displacement
    same = client.call("device.assign", {"logical": "gps.primary", "device_id": UBLOX_ID, "alias": "renamed"},
                       session=token)
    assert same["result"]["displaced"] == []
    # confirmed: Phase 1 semantics, displaced list, device.displaced before device.assigned
    seq = core.bus.last_seq()
    done = client.call("device.assign", {"logical": "gps.primary", "device_id": CP2102_ID, "confirm_displace": True},
                       session=token)
    assert done["result"] == {"logical": "gps.primary", "device_id": CP2102_ID, "alias": None,
                              "displaced": [{"logical": "gps.primary", "device_id": UBLOX_ID}]}
    events = [e for e in client.call("events.recent", session=token)["result"]["events"] if e["seq"] > seq]
    topics = [e["topic"] for e in events]
    assert topics.index("device.displaced") < topics.index("device.assigned")
    displaced = events[topics.index("device.displaced")]
    assert displaced["data"] == {"logical": "gps.primary", "id": UBLOX_ID,
                                 "by": {"logical": "gps.primary", "id": CP2102_ID}}
    # (b) confirmed: the CP2102 moves to mesh.primary and loses gps.primary
    seq = core.bus.last_seq()
    moved = client.call("device.assign", {"logical": "mesh.primary", "device_id": CP2102_ID,
                                          "confirm_displace": True}, session=token)
    assert moved["result"]["displaced"] == [{"logical": "gps.primary", "device_id": CP2102_ID}]
    listing = client.call("device.list", session=token)["result"]
    assert set(listing["assignments"]) == {"mesh.primary"}
    assert client.call("device.assign", {"logical": "gps.primary", "device_id": UBLOX_ID,
                                         "confirm_displace": "yes"}, session=token)["error"]["code"] == "bad-request"
    client.close()


def _golden_snapshot(label_prefix):
    transcript = json.loads(GOLDEN.read_text())["transcript"]
    for entry in transcript:
        if entry.get("devices_json", "").startswith(label_prefix):
            return entry["text"]
    raise AssertionError(label_prefix)


def test_42_v1_displacement_unchanged(p2env):
    core = p2env()
    path = core.config.state_dir / "devices.json"
    v1 = LineClient(core.config.socket)
    token = login(core)
    v2 = V2Client(core.config.socket)
    # the same sequence as the golden 0.1.1 recording
    assert v1.request("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID, "alias": "sdr"})["ok"]
    assert path.read_text() == _golden_snapshot(
        'after assign {"alias": "sdr", "device_id": "dev_ca4a208a9242de2c", "logical": "sdr.primary"}')
    seq = core.bus.last_seq()
    result = v1.request("device.assign", {"logical": "gps.primary", "device_id": CP2102_ID, "alias": "x"})
    assert result["result"] == {"logical": "gps.primary", "device_id": CP2102_ID, "alias": "x"}
    assert "displaced" not in result["result"]
    expected = _golden_snapshot('after assign {"alias": "x", "device_id": "dev_ccbc25d5a4210a5a", "logical": "gps.primary"}')
    assert path.read_text() == expected
    result = v1.request("device.assign", {"logical": "mesh.primary", "device_id": CP2102_ID})
    assert result["ok"] is True
    assert path.read_text() == _golden_snapshot('after assign {"device_id": "dev_ccbc25d5a4210a5a", "logical": "mesh.primary"}')
    v1_topics = [e["topic"] for e in v1.request("events.recent")["result"]["events"]]
    assert "device.displaced" not in v1_topics
    v2_events = [e for e in v2.call("events.recent", session=token)["result"]["events"] if e["seq"] > seq]
    assert "device.displaced" not in [e["topic"] for e in v2_events]
    v1.close()
    v2.close()
