# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
from task_mesh.domain.models import (
    MetricsData,
    NodeInfoData,
    NodeRecord,
    Observation,
    PositionData,
    Source,
    UserData,
)
from task_mesh.services.node_merge import merge_nodeinfo, merge_observation

NOW = 1790000000


def info(**kw):
    return NodeInfoData(0x11, **kw)


def test_new_node_from_nodedb():
    r = merge_nodeinfo(None, info(user=UserData("!00000011", "A", "a", "TBEAM"), snr=3.0, hops_away=1,
                                  last_heard_radio=NOW - 10), NOW, 5)
    assert r.long_name == "A" and r.hw_model == "TBEAM" and r.node_id == "!00000011"
    assert r.snr == 3.0 and r.snr_source is Source.RADIO_NODEDB
    assert r.hops_away == 1 and r.hops_source is Source.RADIO_NODEDB
    assert r.rssi_last is None and r.last_rx_local is None
    assert r.first_seen_local == NOW and r.heard_via_radio == 5 and not r.stale


def test_node_id_fallback_from_number():
    assert merge_nodeinfo(None, info(), NOW, None).node_id == "!00000011"


def test_packet_sets_rssi_and_snr_source_packet():
    base = merge_nodeinfo(None, info(snr=3.0), NOW, None)
    r = merge_observation(base, Observation(0x11, NOW + 5, rx_time_radio=NOW + 4, rx_snr=-2.0, rx_rssi=-99), None)
    assert r.rssi_last == -99 and r.rssi_at_local == NOW + 5
    assert r.snr == -2.0 and r.snr_source is Source.PACKET
    assert r.last_heard_radio == NOW + 4 and r.last_rx_local == NOW + 5


def test_later_nodedb_snr_does_not_override_packet_snr():
    r = merge_observation(None, Observation(0x11, NOW, rx_snr=-2.0), None)
    r = merge_nodeinfo(r, info(snr=7.0), NOW + 1, None)
    assert r.snr == -2.0 and r.snr_source is Source.PACKET


def test_last_heard_is_max_of_radio_times():
    r = merge_nodeinfo(None, info(last_heard_radio=NOW), NOW, None)
    r = merge_observation(r, Observation(0x11, NOW, rx_time_radio=NOW - 100), None)
    assert r.last_heard_radio == NOW


def test_hops_nodedb_beats_calculated():
    r = merge_observation(None, Observation(0x11, NOW, hop_start=3, hop_limit=1), None)
    assert r.hops_away == 2 and r.hops_source is Source.CALCULATED
    r = merge_nodeinfo(r, info(hops_away=1), NOW, None)
    assert r.hops_away == 1 and r.hops_source is Source.RADIO_NODEDB
    r = merge_observation(r, Observation(0x11, NOW, hop_start=3, hop_limit=0), None)
    assert r.hops_away == 1 and r.hops_source is Source.RADIO_NODEDB


def test_unknown_never_overwrites_known():
    r = merge_nodeinfo(None, info(user=UserData("!00000011", "A", "a", "TBEAM"), position=PositionData(1.0, 2.0),
                                  metrics=MetricsData(80, 3.9)), NOW, None)
    r = merge_nodeinfo(r, info(user=UserData("!00000011")), NOW + 1, None)
    r = merge_observation(r, Observation(0x11, NOW + 2, position=PositionData(altitude_m=5),
                                         metrics=MetricsData(voltage=None)), None)
    assert (r.long_name, r.hw_model, r.latitude, r.longitude, r.battery_level, r.voltage) == \
        ("A", "TBEAM", 1.0, 2.0, 80, 3.9)


def test_runtime_packets_update_position_and_battery():
    r = merge_observation(None, Observation(0x11, NOW, position=PositionData(40.1, -105.0)), None)
    r = merge_observation(r, Observation(0x11, NOW + 1, metrics=MetricsData(55)), None)
    assert r.latitude == 40.1 and r.battery_level == 55


def test_stale_cleared_and_first_seen_preserved():
    old = NodeRecord(0x11, first_seen_local=NOW - 9999, updated_local=NOW - 9999, long_name="Old", stale=True)
    r = merge_observation(old, Observation(0x11, NOW), None)
    assert not r.stale and r.first_seen_local == NOW - 9999 and r.long_name == "Old"
