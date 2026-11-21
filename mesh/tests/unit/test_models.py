# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import dataclasses

import pytest

from task_mesh.domain.geo import Layer, node_to_geo
from task_mesh.domain.models import (
    Classification,
    NodeRecord,
    Observation,
    PortCandidate,
    StateSnapshot,
)


def test_models_are_immutable():
    r = NodeRecord(1, 10, 10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.long_name = "x"  # type: ignore[misc]
    r2 = r.with_changes(long_name="x")
    assert r.long_name is None and r2.long_name == "x"


def test_noderecord_radio_fields_default_unknown():
    r = NodeRecord(1, 10, 10)
    for f in dataclasses.fields(r):
        if f.name not in ("node_num", "first_seen_local", "updated_local", "stale"):
            assert getattr(r, f.name) is None, f.name


@pytest.mark.parametrize("start,limit,expected", [(3, 1, 2), (3, 3, 0), (None, 1, None), (3, None, None),
                                                  (1, 3, None), (9, 1, None)])
def test_observation_calculated_hops(start, limit, expected):
    assert Observation(1, 0, hop_start=start, hop_limit=limit).hops_calculated == expected


def test_port_candidate_label_and_identity():
    c = PortCandidate("/dev/ttyUSB0", by_id="/dev/serial/by-id/x", vid=0x10C4, pid=0xEA60, serial_number="0001",
                      manufacturer="Silicon Labs", product="CP2102", classification=Classification.LIKELY)
    assert c.usb_id == "10c4:ea60"
    assert "Silicon Labs CP2102" in c.label and "/dev/ttyUSB0" in c.label
    assert c.identity() == {"by_id": "/dev/serial/by-id/x", "by_path": None, "vid": 0x10C4, "pid": 0xEA60,
                            "serial": "0001"}
    assert PortCandidate("/dev/ttyACM0").usb_id == "—"


def test_geo_projection_needs_position():
    assert node_to_geo(NodeRecord(1, 0, 0)) is None
    g = node_to_geo(NodeRecord(1, 0, 0, latitude=1.5, longitude=-2.5, short_name="AB"))
    assert g.layer is Layer.MESHTASTIC and g.latitude == 1.5 and g.id == "meshtastic:1"


def test_state_snapshot_defaults():
    s = StateSnapshot(state="IDLE")
    assert s.candidates == () and s.error_code is None
