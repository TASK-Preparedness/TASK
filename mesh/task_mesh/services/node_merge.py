# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Pure merge rules turning radio node-DB entries and packet observations into NodeRecords.

Rules (design report §5.3):
* names/hardware/id: radio node DB or NODEINFO packets (library placeholders already suppressed)
* last heard: max(radio lastHeard, packet rxTime) on the RADIO clock; local receive time kept separately
* RSSI: last packet rxRssi only (the node DB has no RSSI)
* SNR: last packet rxSnr, else node DB snr
* hops: node DB hopsAway, else packet hopStart - hopLimit (labelled calculated)
* battery/voltage, position: newest known value; unknown never overwrites known
"""

from __future__ import annotations

from typing import Optional

from task_mesh.domain.models import (
    MetricsData,
    NodeInfoData,
    NodeRecord,
    Observation,
    PositionData,
    Source,
    UserData,
)


def _max_opt(a: Optional[int], b: Optional[int]) -> Optional[int]:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _base(node_num: int, existing: Optional[NodeRecord], now: int) -> NodeRecord:
    if existing is None:
        return NodeRecord(node_num=node_num, first_seen_local=now, updated_local=now)
    return existing


def _apply_user(rec: NodeRecord, user: Optional[UserData]) -> NodeRecord:
    if user is None:
        return rec
    return rec.with_changes(
        node_id=user.node_id or rec.node_id,
        long_name=user.long_name if user.long_name is not None else rec.long_name,
        short_name=user.short_name if user.short_name is not None else rec.short_name,
        hw_model=user.hw_model if user.hw_model is not None else rec.hw_model,
        role=user.role if user.role is not None else rec.role,
        is_licensed=user.is_licensed if user.is_licensed is not None else rec.is_licensed,
    )


def _apply_position(rec: NodeRecord, pos: Optional[PositionData]) -> NodeRecord:
    if pos is None:
        return rec
    changes = {}
    if pos.latitude is not None and pos.longitude is not None:
        changes.update(latitude=pos.latitude, longitude=pos.longitude,
                       position_precision_bits=pos.precision_bits)
        changes["altitude_m"] = pos.altitude_m
        changes["position_time_radio"] = pos.time_radio
    return rec.with_changes(**changes) if changes else rec


def _apply_metrics(rec: NodeRecord, m: Optional[MetricsData]) -> NodeRecord:
    if m is None:
        return rec
    return rec.with_changes(
        battery_level=m.battery_level if m.battery_level is not None else rec.battery_level,
        voltage=m.voltage if m.voltage is not None else rec.voltage,
    )


def merge_nodeinfo(existing: Optional[NodeRecord], info: NodeInfoData, now: int,
                   radio_num: Optional[int]) -> NodeRecord:
    rec = _base(info.node_num, existing, now)
    rec = _apply_user(rec, info.user)
    rec = _apply_position(rec, info.position)
    rec = _apply_metrics(rec, info.metrics)
    changes: dict = {
        "last_heard_radio": _max_opt(rec.last_heard_radio, info.last_heard_radio),
        "updated_local": now,
        "stale": False,
        "heard_via_radio": radio_num if radio_num is not None else rec.heard_via_radio,
    }
    if rec.node_id is None:
        changes["node_id"] = f"!{info.node_num:08x}"
    if info.snr is not None and rec.snr_source is not Source.PACKET:
        changes.update(snr=info.snr, snr_source=Source.RADIO_NODEDB)
    if info.hops_away is not None:
        changes.update(hops_away=info.hops_away, hops_source=Source.RADIO_NODEDB)
    if info.via_mqtt is not None:
        changes["via_mqtt"] = info.via_mqtt
    return rec.with_changes(**changes)


def merge_observation(existing: Optional[NodeRecord], obs: Observation, radio_num: Optional[int]) -> NodeRecord:
    now = obs.observed_local
    rec = _base(obs.node_num, existing, now)
    rec = _apply_user(rec, obs.user)
    rec = _apply_position(rec, obs.position)
    rec = _apply_metrics(rec, obs.metrics)
    changes: dict = {
        "last_heard_radio": _max_opt(rec.last_heard_radio, obs.rx_time_radio),
        "last_rx_local": now,
        "updated_local": now,
        "stale": False,
        "heard_via_radio": radio_num if radio_num is not None else rec.heard_via_radio,
    }
    if rec.node_id is None:
        changes["node_id"] = f"!{obs.node_num:08x}"
    if obs.rx_rssi is not None:
        changes.update(rssi_last=obs.rx_rssi, rssi_at_local=now)
    if obs.rx_snr is not None:
        changes.update(snr=obs.rx_snr, snr_source=Source.PACKET)
    calc = obs.hops_calculated
    if calc is not None and rec.hops_source is not Source.RADIO_NODEDB:
        changes.update(hops_away=calc, hops_source=Source.CALCULATED)
    if obs.via_mqtt is not None:
        changes["via_mqtt"] = obs.via_mqtt
    return rec.with_changes(**changes)
