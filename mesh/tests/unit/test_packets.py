# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Node/packet conversion including malformed and placeholder data."""

import math

import pytest

from task_mesh.radio.meshtastic.packets import (
    PacketError,
    is_placeholder_user,
    parse_nodeinfo,
    parse_packet,
    parse_position,
    parse_user,
)

FULL = {"num": 287454020,
        "user": {"id": "!11223344", "longName": "Ridge Relay", "shortName": "RDG", "hwModel": "RAK4631",
                 "role": "ROUTER"},
        "position": {"latitudeI": 401234567, "longitudeI": -1051234567, "latitude": 40.1234567,
                     "longitude": -105.1234567},
        "snr": 6.25, "lastHeard": 1759600000, "deviceMetrics": {"batteryLevel": 87}, "hopsAway": 2}


def test_full_nodeinfo():
    n = parse_nodeinfo(FULL)
    assert n.node_num == 0x11223344
    assert n.user.long_name == "Ridge Relay" and n.user.hw_model == "RAK4631" and n.user.role == "ROUTER"
    assert n.position.latitude == pytest.approx(40.1234567) and n.position.longitude == pytest.approx(-105.1234567)
    assert n.snr == 6.25 and n.last_heard_radio == 1759600000 and n.hops_away == 2
    assert n.metrics.battery_level == 87 and n.metrics.voltage is None


def test_library_placeholder_user_suppressed():
    raw = {"num": 0x55667788, "user": {"id": "!55667788", "longName": "Meshtastic 7788", "shortName": "7788",
                                       "hwModel": "UNSET"}}
    assert is_placeholder_user(raw["user"], 0x55667788)
    n = parse_nodeinfo(raw)
    assert n.user.long_name is None and n.user.short_name is None and n.user.hw_model is None
    assert n.user.node_id == "!55667788"


def test_real_user_named_like_placeholder_with_hardware_is_kept():
    u = parse_user({"id": "!55667788", "longName": "Meshtastic 7788", "shortName": "7788", "hwModel": "HELTEC_V3"},
                   0x55667788)
    assert u.long_name == "Meshtastic 7788" and u.hw_model == "HELTEC_V3"


def test_no_position_and_no_user():
    n = parse_nodeinfo({"num": 5})
    assert n.user is None and n.position is None and n.metrics is None and n.snr is None


def test_latitude_i_only_position():
    p = parse_position({"latitudeI": 401234567, "longitudeI": -1051234567})
    assert p.latitude == pytest.approx(40.1234567) and p.longitude == pytest.approx(-105.1234567)


def test_zero_zero_is_kept_as_reported():
    p = parse_position({"latitudeI": 0, "longitudeI": 0, "latitude": 0.0, "longitude": 0.0})
    assert p.latitude == 0.0 and p.longitude == 0.0


@pytest.mark.parametrize("pos", [
    {"latitude": 91.0, "longitude": 10.0},
    {"latitude": float("nan"), "longitude": 10.0},
    {"latitude": "north", "longitude": 10.0},
    {"latitude": 10.0},
    {"latitudeI": 10 ** 12, "longitudeI": 5},
    {"latitude": True, "longitude": False},
])
def test_bad_positions_become_unknown(pos):
    p = parse_position(pos)
    assert p is None or (p.latitude is None and p.longitude is None)


@pytest.mark.parametrize("raw", [None, 5, "x", [], {}, {"num": 0}, {"num": -1}, {"num": "abc"},
                                 {"num": 0xFFFFFFFF}, {"num": 1.5}])
def test_malformed_nodeinfo_raises_packet_error(raw):
    with pytest.raises(PacketError):
        parse_nodeinfo(raw)


def test_malformed_fields_do_not_raise():
    n = parse_nodeinfo({"num": 7, "user": "notadict", "position": [1, 2], "deviceMetrics": {"batteryLevel": "full",
                        "voltage": math.inf}, "snr": "loud", "lastHeard": 0, "hopsAway": 99})
    assert n.user is None and n.position is None and n.metrics is None
    assert n.snr is None and n.last_heard_radio is None and n.hops_away is None


def test_packet_position_with_link_metrics():
    pkt = {"from": 0x11223344, "to": 4294967295, "id": 42, "rxTime": 1759609999, "rxSnr": -3.5, "rxRssi": -97,
           "hopStart": 3, "hopLimit": 1,
           "decoded": {"portnum": "POSITION_APP", "position": {"latitudeI": 401000000, "longitudeI": -1050000000}}}
    o = parse_packet(pkt, 1790000000)
    assert o.node_num == 0x11223344 and o.observed_local == 1790000000 and o.packet_id == 42
    assert o.rx_rssi == -97 and o.rx_snr == -3.5 and o.hops_calculated == 2
    assert o.position.latitude == pytest.approx(40.1)


def test_packet_rssi_absent_is_unknown_not_zero():
    o = parse_packet({"from": 9, "decoded": {"portnum": "TEXT_MESSAGE_APP"}}, 1)
    assert o.rx_rssi is None and o.rx_snr is None and o.rx_time_radio is None


def test_packet_telemetry_and_nodeinfo_payloads():
    t = parse_packet({"from": 9, "decoded": {"portnum": "TELEMETRY_APP",
                                            "telemetry": {"deviceMetrics": {"batteryLevel": 55, "voltage": 3.9}}}}, 1)
    assert t.metrics.battery_level == 55 and t.metrics.voltage == 3.9
    u = parse_packet({"from": 9, "decoded": {"portnum": "NODEINFO_APP",
                                            "user": {"id": "!00000009", "longName": "N", "shortName": "n"}}}, 1)
    assert u.user.long_name == "N"


@pytest.mark.parametrize("raw", [None, {}, {"from": None}, {"from": "x"}, {"from": 0}, [1, 2], "packet"])
def test_packet_without_valid_from_raises(raw):
    with pytest.raises(PacketError):
        parse_packet(raw, 1)


def test_text_non_utf8_packet_still_attributed():
    o = parse_packet({"from": 9, "rxRssi": -50, "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"\xff\xfe"}}, 1)
    assert o.rx_rssi == -50 and o.portnum == "TEXT_MESSAGE_APP"


def test_names_are_sanitised():
    u = parse_user({"id": "!0000000a", "longName": "  A\x00B  ", "shortName": "x" * 50}, 10)
    assert u.long_name == "AB" and len(u.short_name) == 8
