# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Text and routing packets (meshtastic.receive dicts) -> plain tuples. Content is never logged."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

BROADCAST_NUM = 0xFFFFFFFF
MAX_TEXT_BYTES = 200  # conservative below Meshtastic's 233-byte data payload


@dataclass(frozen=True)
class TextPacket:
    packet_id: Optional[int]
    from_num: int
    to_num: int
    channel: int
    text: str
    rx_time: Optional[int]
    via_mqtt: bool
    priority: Optional[str] = None   # MeshPacket.priority as delivered by the library (e.g. "ALERT"); 0.3.0

    @property
    def is_direct(self) -> bool:
        return self.to_num != BROADCAST_NUM


@dataclass(frozen=True)
class RoutingPacket:
    request_id: int
    from_num: int
    error_reason: str  # "NONE" = ACK


def _u32(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xFFFFFFFF else None


def parse_text(raw: Any) -> Optional[TextPacket]:
    if not isinstance(raw, Mapping):
        return None
    d = raw.get("decoded")
    if not isinstance(d, Mapping) or d.get("portnum") != "TEXT_MESSAGE_APP":
        return None
    text = d.get("text")
    if not isinstance(text, str):
        payload = d.get("payload")
        if isinstance(payload, (bytes, bytearray)):
            text = bytes(payload).decode("utf-8", "replace")
        else:
            return None
    frm, to = _u32(raw.get("from")), _u32(raw.get("to"))
    if frm is None or frm in (0, BROADCAST_NUM):
        return None
    ch = raw.get("channel", 0)
    return TextPacket(_u32(raw.get("id")), frm, BROADCAST_NUM if to is None else to,
                      ch if isinstance(ch, int) and 0 <= ch <= 7 else 0,
                      text.replace("\x00", "")[:1000], _u32(raw.get("rxTime")) or None, bool(raw.get("viaMqtt")),
                      _priority(raw.get("priority")))


def _priority(v: Any) -> Optional[str]:
    if isinstance(v, str) and v.isupper() and len(v) <= 16:
        return v
    if v == 110:
        return "ALERT"
    return None


def parse_routing(raw: Any) -> Optional[RoutingPacket]:
    if not isinstance(raw, Mapping):
        return None
    d = raw.get("decoded")
    if not isinstance(d, Mapping) or d.get("portnum") != "ROUTING_APP":
        return None
    rid, frm = _u32(d.get("requestId")), _u32(raw.get("from"))
    if not rid or frm is None:
        return None
    routing = d.get("routing") if isinstance(d.get("routing"), Mapping) else {}
    reason = routing.get("errorReason", "NONE")
    return RoutingPacket(rid, frm, reason if isinstance(reason, str) and reason else "NONE")
