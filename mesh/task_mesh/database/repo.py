# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SQL for v0.1. All writes are executed on the DbWriter thread only."""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from task_mesh.core.config import RetentionConfig
from task_mesh.domain.models import (
    ConnectionEventRecord,
    NodeRecord,
    Observation,
    PortCandidate,
    RadioEvent,
    RadioIdentity,
    Source,
)

NODE_COLUMNS = (
    "node_num", "node_id", "long_name", "short_name", "hw_model", "role", "is_licensed",
    "last_heard_radio", "last_rx_local", "snr", "snr_source", "rssi_last", "rssi_at_local",
    "hops_away", "hops_source", "battery_level", "voltage", "latitude", "longitude", "altitude_m",
    "position_time_radio", "position_precision_bits", "via_mqtt", "heard_via_radio",
    "first_seen_local", "updated_local",
)


def _b(v: Optional[bool]) -> Optional[int]:
    return None if v is None else int(bool(v))


def _src(v: Optional[Source]) -> Optional[str]:
    return None if v is None else v.value


def node_params(rec: NodeRecord) -> dict:
    return {
        "node_num": rec.node_num, "node_id": rec.node_id, "long_name": rec.long_name,
        "short_name": rec.short_name, "hw_model": rec.hw_model, "role": rec.role,
        "is_licensed": _b(rec.is_licensed), "last_heard_radio": rec.last_heard_radio,
        "last_rx_local": rec.last_rx_local, "snr": rec.snr, "snr_source": _src(rec.snr_source),
        "rssi_last": rec.rssi_last, "rssi_at_local": rec.rssi_at_local, "hops_away": rec.hops_away,
        "hops_source": _src(rec.hops_source), "battery_level": rec.battery_level, "voltage": rec.voltage,
        "latitude": rec.latitude, "longitude": rec.longitude, "altitude_m": rec.altitude_m,
        "position_time_radio": rec.position_time_radio,
        "position_precision_bits": rec.position_precision_bits, "via_mqtt": _b(rec.via_mqtt),
        "heard_via_radio": rec.heard_via_radio, "first_seen_local": rec.first_seen_local,
        "updated_local": rec.updated_local,
    }


_values = ", ".join(
    "(SELECT node_num FROM radios WHERE node_num = :heard_via_radio)" if c == "heard_via_radio" else f":{c}"
    for c in NODE_COLUMNS
)
_updates = ", ".join(f"{c} = excluded.{c}" for c in NODE_COLUMNS if c not in ("node_num", "first_seen_local"))
UPSERT_NODE_SQL = (
    f"INSERT INTO nodes ({', '.join(NODE_COLUMNS)}) VALUES ({_values}) "
    f"ON CONFLICT(node_num) DO UPDATE SET {_updates}"
)


def upsert_node(conn: sqlite3.Connection, rec: NodeRecord) -> None:
    conn.execute(UPSERT_NODE_SQL, node_params(rec))


def insert_observation(conn: sqlite3.Connection, obs: Observation, radio_num: Optional[int]) -> None:
    conn.execute(
        "INSERT INTO node_observations (node_num, radio_num, observed_local, rx_time_radio, rx_snr, rx_rssi,"
        " hop_start, hop_limit, portnum, via_mqtt, packet_id)"
        " SELECT ?, (SELECT node_num FROM radios WHERE node_num = ?), ?, ?, ?, ?, ?, ?, ?, ?, ?"
        " WHERE EXISTS (SELECT 1 FROM nodes WHERE node_num = ?)",
        (obs.node_num, radio_num, obs.observed_local, obs.rx_time_radio, obs.rx_snr, obs.rx_rssi,
         obs.hop_start, obs.hop_limit, obs.portnum, _b(obs.via_mqtt), obs.packet_id, obs.node_num),
    )


def upsert_radio(conn: sqlite3.Connection, ident: RadioIdentity, port: Optional[PortCandidate], now: int) -> None:
    p = port or PortCandidate(device="")
    conn.execute(
        "INSERT INTO radios (node_num, node_id, long_name, short_name, hw_model, firmware_version, usb_vid,"
        " usb_pid, usb_serial, last_port_by_id, last_port_by_path, last_port_dev, first_connected, last_connected)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(node_num) DO UPDATE SET node_id=excluded.node_id, long_name=excluded.long_name,"
        " short_name=excluded.short_name, hw_model=excluded.hw_model, firmware_version=excluded.firmware_version,"
        " usb_vid=excluded.usb_vid, usb_pid=excluded.usb_pid, usb_serial=excluded.usb_serial,"
        " last_port_by_id=excluded.last_port_by_id, last_port_by_path=excluded.last_port_by_path,"
        " last_port_dev=excluded.last_port_dev, last_connected=excluded.last_connected",
        (ident.node_num, ident.node_id, ident.long_name, ident.short_name, ident.hw_model,
         ident.firmware_version, p.vid, p.pid, p.serial_number, p.by_id, p.by_path, p.device or None, now, now),
    )


def insert_connection_event(conn: sqlite3.Connection, ev: ConnectionEventRecord) -> None:
    p = ev.port or PortCandidate(device="")
    conn.execute(
        "INSERT INTO connection_events (at_local, from_state, to_state, reason, port_dev, port_by_id,"
        " port_by_path, usb_vid, usb_pid, usb_serial, radio_num)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,(SELECT node_num FROM radios WHERE node_num = ?))",
        (ev.at_local, ev.from_state, ev.to_state, ev.reason, p.device or None, p.by_id, p.by_path,
         p.vid, p.pid, p.serial_number, ev.radio_num),
    )


def insert_radio_event(conn: sqlite3.Connection, ev: RadioEvent, radio_num: Optional[int]) -> None:
    conn.execute(
        "INSERT INTO radio_events (at_local, level, kind, message, detail_json, radio_num)"
        " VALUES (?,?,?,?,?,(SELECT node_num FROM radios WHERE node_num = ?))",
        (ev.at_local, ev.level.value, ev.kind, ev.message,
         json.dumps(ev.detail, sort_keys=True) if ev.detail is not None else None, radio_num),
    )


def _opt_bool(v) -> Optional[bool]:
    return None if v is None else bool(v)


def _opt_src(v) -> Optional[Source]:
    try:
        return None if v is None else Source(v)
    except ValueError:
        return None


def load_nodes(conn: sqlite3.Connection) -> list[NodeRecord]:
    rows = conn.execute(f"SELECT {', '.join(NODE_COLUMNS)} FROM nodes ORDER BY node_num").fetchall()
    out = []
    for r in rows:
        d = dict(zip(NODE_COLUMNS, r))
        d["is_licensed"] = _opt_bool(d["is_licensed"])
        d["via_mqtt"] = _opt_bool(d["via_mqtt"])
        d["snr_source"] = _opt_src(d["snr_source"])
        d["hops_source"] = _opt_src(d["hops_source"])
        out.append(NodeRecord(stale=True, **d))
    return out


def _chunked_delete(conn: sqlite3.Connection, table: str, where: str, params: tuple, chunk: int) -> int:
    total = 0
    while True:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} WHERE {where} LIMIT {int(chunk)})", params
        )
        conn.execute("COMMIT")
        total += cur.rowcount
        if cur.rowcount < chunk:
            return total


def prune(conn: sqlite3.Connection, ret: RetentionConfig, now: int, chunk: int = 5000) -> dict:
    day = 86400
    out = {
        "node_observations": _chunked_delete(conn, "node_observations", "observed_local < ?",
                                             (now - ret.node_observations_days * day,), chunk),
        "connection_events": _chunked_delete(conn, "connection_events", "at_local < ?",
                                             (now - ret.connection_events_days * day,), chunk),
        "radio_events": _chunked_delete(conn, "radio_events", "at_local < ?",
                                        (now - ret.radio_events_days * day,), chunk),
    }
    # Row cap on radio_events: keep the newest N.
    over = conn.execute("SELECT count(*) FROM radio_events").fetchone()[0] - ret.radio_events_max_rows
    if over > 0:
        cutoff = conn.execute("SELECT id FROM radio_events ORDER BY id LIMIT 1 OFFSET ?", (over - 1,)).fetchone()[0]
        out["radio_events"] += _chunked_delete(conn, "radio_events", "id <= ?", (cutoff,), chunk)
    if ret.nodes_unheard_days > 0:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("DELETE FROM nodes WHERE updated_local < ?", (now - ret.nodes_unheard_days * day,))
        conn.execute("COMMIT")
        out["nodes"] = cur.rowcount
    conn.execute("PRAGMA incremental_vacuum(500)").fetchall()
    return out
