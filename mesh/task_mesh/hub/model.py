# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Normalised message / node / device records. Identities are never merged across protocols: every key
is scoped by (protocol, ...). Text content is never logged."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Optional

PROTOCOLS = ("meshtastic", "meshcore")
LABELS = {"meshtastic": "Meshtastic", "meshcore": "MeshCore"}
LIVE, SYNC = "live", "sync"          # sync = replayed/queued on the device before we were attached: never "new"


def check_protocol(p: str) -> str:
    if p not in PROTOCOLS:
        raise ValueError(f"unknown protocol {p!r}")
    return p


def dedupe_key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8", "replace") + b"\x1f")
    return h.hexdigest()[:32]


@dataclass
class HubMessage:
    protocol: str
    device: str                  # local radio key (by-id basename)
    key: str                     # dedupe key, unique per protocol
    direction: str               # "in" | "out"
    kind: str                    # "dm" | "channel"
    conversation: str            # "dm:<native sender id>" | "ch:<index>"  (scoped by protocol)
    sender: str                  # native id: "!a1b2c3d4" (Meshtastic) / 12-hex pubkey prefix (MeshCore) / "" unknown
    sender_label: str
    text: str
    ts: float                    # local receive (or send) time
    sender_ts: Optional[int] = None
    origin: str = LIVE
    priority: Optional[str] = None
    priority_source: Optional[str] = None   # "protocol:<what>" | "user-rule:<name>"
    snr: Optional[float] = None
    rssi: Optional[int] = None
    hops: Optional[int] = None
    state: str = "received"      # in: received ; out: queued/sent/relayed/delivered/failed/no-ack
    read: bool = False
    id: Optional[int] = None     # store row id

    def __post_init__(self) -> None:
        check_protocol(self.protocol)
        if self.direction not in ("in", "out") or self.kind not in ("dm", "channel") or self.origin not in (LIVE, SYNC):
            raise ValueError("bad message fields")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HubNode:
    protocol: str
    key: str                     # native id (Meshtastic "!xxxxxxxx", MeshCore full public key hex)
    name: str = ""
    role: str = ""               # e.g. "chat", "repeater", "room", "sensor", "CLIENT", "ROUTER"
    last_heard: Optional[float] = None
    snr: Optional[float] = None
    rssi: Optional[int] = None
    hops: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    device: str = ""


@dataclass
class DeviceStatus:
    key: str                     # by-id basename (or tty name)
    path: str                    # /dev/serial/by-id/... (open path)
    protocol: Optional[str] = None
    protocol_source: str = "unknown"   # "user" | "probe" | "usb-hint" | "unknown"
    state: str = "idle"          # idle | probing | connecting | connected | backoff | busy | error | unsupported
    owner: str = ""              # "service" | "gui" | "other process" | ""
    model: str = ""
    firmware: str = ""
    name: str = ""
    battery: Optional[int] = None
    detail: str = ""
    last_change: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
