# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Convert meshtastic-library dicts into immutable domain objects.

Defensive by design: any field can be missing, of the wrong type, or nonsensical. Bad values become
None (unknown), never 0. Placeholder users invented by the library are suppressed.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Optional

from task_mesh.domain.models import MetricsData, NodeInfoData, Observation, PositionData, UserData

BROADCAST_NUM = 0xFFFFFFFF
_NODE_ID_RE = re.compile(r"^![0-9a-f]{8}$")


class PacketError(ValueError):
    """Raised for packets that cannot be attributed to a node at all."""


def _int(v: Any, lo: Optional[int] = None, hi: Optional[int] = None) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, float):
        if not math.isfinite(v) or v != int(v):
            return None
        v = int(v)
    if isinstance(v, str):
        try:
            v = int(v, 10)
        except ValueError:
            return None
    if not isinstance(v, int):
        return None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return None
    return v


def _float(v: Any, lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(f):
        return None
    if (lo is not None and f < lo) or (hi is not None and f > hi):
        return None
    return f


def _str(v: Any, maxlen: int = 64) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.replace("\x00", "").strip()
    if not v:
        return None
    return v[:maxlen]


def _bool(v: Any) -> Optional[bool]:
    return v if isinstance(v, bool) else None


def _epoch(v: Any) -> Optional[int]:
    # 0 means "radio clock not set" in Meshtastic, so treat it as unknown.
    return _int(v, lo=1, hi=2**32 - 1)


def node_id_for(num: int) -> str:
    return f"!{num:08x}"


def is_placeholder_user(user: Mapping[str, Any], node_num: Optional[int]) -> bool:
    """The library fabricates {'longName': 'Meshtastic abcd', 'shortName': 'abcd', 'hwModel': 'UNSET'}
    for nodes known only by number. Those are not real names and must not be displayed."""
    uid = user.get("id")
    if not isinstance(uid, str) or len(uid) < 4:
        if node_num is None:
            return False
        uid = node_id_for(node_num)
    tail = uid[-4:]
    return (
        user.get("longName") == f"Meshtastic {tail}"
        and user.get("shortName") == tail
        and user.get("hwModel") in ("UNSET", None)
        and not user.get("macaddr")
        and not user.get("publicKey")
    )


def parse_user(raw: Any, node_num: Optional[int] = None) -> Optional[UserData]:
    if not isinstance(raw, Mapping):
        return None
    node_id = _str(raw.get("id"), 16)
    if node_id is not None and not _NODE_ID_RE.match(node_id.lower()):
        node_id = None
    if node_id is None and node_num is not None:
        node_id = node_id_for(node_num)
    if is_placeholder_user(raw, node_num):
        return UserData(node_id=node_id)
    hw = _str(raw.get("hwModel"), 40)
    if hw == "UNSET":
        hw = None
    return UserData(
        node_id=node_id,
        long_name=_str(raw.get("longName"), 40),
        short_name=_str(raw.get("shortName"), 8),
        hw_model=hw,
        # Proto3 omits the default role; absence means the default (CLIENT) per the protobuf.
        role=_str(raw.get("role"), 32) or ("CLIENT" if (raw.get("longName") or raw.get("shortName")) else None),
        is_licensed=_bool(raw.get("isLicensed")),
    )


def parse_position(raw: Any) -> Optional[PositionData]:
    if not isinstance(raw, Mapping):
        return None
    lat = _float(raw.get("latitude"), -90.0, 90.0)
    lon = _float(raw.get("longitude"), -180.0, 180.0)
    if lat is None:
        li = _int(raw.get("latitudeI"))
        lat = _float(li * 1e-7, -90.0, 90.0) if li is not None else None
    if lon is None:
        li = _int(raw.get("longitudeI"))
        lon = _float(li * 1e-7, -180.0, 180.0) if li is not None else None
    # A position needs both coordinates; half a coordinate is not a position.
    if lat is None or lon is None:
        lat = lon = None
    pos = PositionData(
        latitude=lat,
        longitude=lon,
        altitude_m=_int(raw.get("altitude"), -1000, 100000),
        time_radio=_epoch(raw.get("time")),
        precision_bits=_int(raw.get("precisionBits"), 0, 32),
    )
    if pos == PositionData():
        return None
    return pos


def parse_metrics(raw: Any) -> Optional[MetricsData]:
    if not isinstance(raw, Mapping):
        return None
    m = MetricsData(
        battery_level=_int(raw.get("batteryLevel"), 0, 255),
        voltage=_float(raw.get("voltage"), 0.0, 60.0),
    )
    return None if m == MetricsData() else m


def parse_nodeinfo(raw: Any) -> NodeInfoData:
    if not isinstance(raw, Mapping):
        raise PacketError("node entry is not a mapping")
    num = _int(raw.get("num"), 1, BROADCAST_NUM - 1)
    if num is None:
        raise PacketError("node entry has no valid 'num'")
    return NodeInfoData(
        node_num=num,
        user=parse_user(raw.get("user"), num),
        position=parse_position(raw.get("position")),
        metrics=parse_metrics(raw.get("deviceMetrics")),
        snr=_float(raw.get("snr"), -50.0, 50.0),
        last_heard_radio=_epoch(raw.get("lastHeard")),
        hops_away=_int(raw.get("hopsAway"), 0, 15),
        via_mqtt=_bool(raw.get("viaMqtt")),
    )


def parse_packet(raw: Any, observed_local: int) -> Observation:
    """Parse a received MeshPacket dict (as published on meshtastic.receive.*)."""
    if not isinstance(raw, Mapping):
        raise PacketError("packet is not a mapping")
    num = _int(raw.get("from"), 1, BROADCAST_NUM - 1)
    if num is None:
        raise PacketError("packet has no valid 'from'")
    decoded = raw.get("decoded")
    portnum = position = user = metrics = None
    if isinstance(decoded, Mapping):
        portnum = _str(decoded.get("portnum"), 48) if isinstance(decoded.get("portnum"), str) else None
        if portnum is None and isinstance(decoded.get("portnum"), int):
            portnum = str(decoded.get("portnum"))
        if portnum == "POSITION_APP":
            position = parse_position(decoded.get("position"))
        elif portnum == "NODEINFO_APP":
            user = parse_user(decoded.get("user"), num)
        elif portnum == "TELEMETRY_APP":
            tel = decoded.get("telemetry")
            if isinstance(tel, Mapping):
                metrics = parse_metrics(tel.get("deviceMetrics"))
    return Observation(
        node_num=num,
        observed_local=observed_local,
        rx_time_radio=_epoch(raw.get("rxTime")),
        rx_snr=_float(raw.get("rxSnr"), -50.0, 50.0),
        # rx_rssi has no field presence in the bundled protos: 0 dBm is dropped by MessageToDict,
        # so absence is "unknown", never 0.
        rx_rssi=_int(raw.get("rxRssi"), -200, 50),
        hop_start=_int(raw.get("hopStart"), 0, 7),
        hop_limit=_int(raw.get("hopLimit"), 0, 7),
        portnum=portnum,
        via_mqtt=_bool(raw.get("viaMqtt")),
        packet_id=_int(raw.get("id"), 0, 2**32 - 1),
        position=position,
        user=user,
        metrics=metrics,
    )
