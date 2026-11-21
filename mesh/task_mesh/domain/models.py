# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Plain, immutable, Qt-free domain objects shared by radio, services, database and UI.

Rule: every radio-derived value is Optional. None means "unknown" and is rendered as an em dash.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Optional


class Source(str, Enum):
    RADIO_NODEDB = "radio_nodedb"   # value from the radio's node database
    PACKET = "packet"               # value from a received packet
    CALCULATED = "calculated"       # derived by T.A.S.K. (labelled "calc" in the UI)
    LOCAL = "local"                 # this computer's clock / observation


class Classification(str, Enum):
    LIKELY = "likely"
    POSSIBLE = "possible"
    NEVER = "never"


@dataclass(frozen=True)
class PortCandidate:
    device: str                         # /dev/ttyUSB0
    by_id: Optional[str] = None
    by_path: Optional[str] = None
    vid: Optional[int] = None
    pid: Optional[int] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    product: Optional[str] = None
    classification: Classification = Classification.POSSIBLE
    open_path: str = ""                 # path actually passed as devPath
    ambiguous_by_id: bool = False

    @property
    def usb_id(self) -> str:
        if self.vid is None or self.pid is None:
            return "—"
        return f"{self.vid:04x}:{self.pid:04x}"

    @property
    def label(self) -> str:
        name = " ".join(x for x in (self.manufacturer, self.product) if x) or "USB serial device"
        return f"{name} · {self.usb_id} · {self.device}"

    def identity(self) -> dict:
        return {
            "by_id": self.by_id,
            "by_path": self.by_path,
            "vid": self.vid,
            "pid": self.pid,
            "serial": self.serial_number,
        }


@dataclass(frozen=True)
class RadioIdentity:
    node_num: int
    node_id: Optional[str] = None
    long_name: Optional[str] = None
    short_name: Optional[str] = None
    hw_model: Optional[str] = None
    firmware_version: Optional[str] = None


@dataclass(frozen=True)
class PositionData:
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[int] = None
    time_radio: Optional[int] = None
    precision_bits: Optional[int] = None


@dataclass(frozen=True)
class UserData:
    node_id: Optional[str] = None
    long_name: Optional[str] = None
    short_name: Optional[str] = None
    hw_model: Optional[str] = None
    role: Optional[str] = None
    is_licensed: Optional[bool] = None


@dataclass(frozen=True)
class MetricsData:
    battery_level: Optional[int] = None
    voltage: Optional[float] = None


@dataclass(frozen=True)
class NodeInfoData:
    """A node entry from the radio's node database (config download or resync)."""
    node_num: int
    user: Optional[UserData] = None
    position: Optional[PositionData] = None
    metrics: Optional[MetricsData] = None
    snr: Optional[float] = None
    last_heard_radio: Optional[int] = None
    hops_away: Optional[int] = None
    via_mqtt: Optional[bool] = None


@dataclass(frozen=True)
class Observation:
    """One received packet, reduced to link metrics plus any decoded node-state payload."""
    node_num: int
    observed_local: int
    rx_time_radio: Optional[int] = None
    rx_snr: Optional[float] = None
    rx_rssi: Optional[int] = None
    hop_start: Optional[int] = None
    hop_limit: Optional[int] = None
    portnum: Optional[str] = None
    via_mqtt: Optional[bool] = None
    packet_id: Optional[int] = None
    position: Optional[PositionData] = None
    user: Optional[UserData] = None
    metrics: Optional[MetricsData] = None

    @property
    def hops_calculated(self) -> Optional[int]:
        if self.hop_start is None or self.hop_limit is None:
            return None
        if self.hop_start < self.hop_limit or self.hop_start > 7:
            return None
        return self.hop_start - self.hop_limit


@dataclass(frozen=True)
class NodeRecord:
    node_num: int
    first_seen_local: int
    updated_local: int
    node_id: Optional[str] = None
    long_name: Optional[str] = None
    short_name: Optional[str] = None
    hw_model: Optional[str] = None
    role: Optional[str] = None
    is_licensed: Optional[bool] = None
    last_heard_radio: Optional[int] = None
    last_rx_local: Optional[int] = None
    snr: Optional[float] = None
    snr_source: Optional[Source] = None
    rssi_last: Optional[int] = None
    rssi_at_local: Optional[int] = None
    hops_away: Optional[int] = None
    hops_source: Optional[Source] = None
    battery_level: Optional[int] = None
    voltage: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[int] = None
    position_time_radio: Optional[int] = None
    position_precision_bits: Optional[int] = None
    via_mqtt: Optional[bool] = None
    heard_via_radio: Optional[int] = None
    stale: bool = False  # loaded from DB, not yet refreshed by the radio this session

    def with_changes(self, **kw) -> "NodeRecord":
        return replace(self, **kw)


class EventLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RadioEvent:
    at_local: int
    level: EventLevel
    kind: str
    message: str
    detail: Optional[dict] = None


@dataclass(frozen=True)
class ConnectionEventRecord:
    at_local: int
    from_state: Optional[str]
    to_state: str
    reason: Optional[str] = None
    port: Optional[PortCandidate] = None
    radio_num: Optional[int] = None


@dataclass(frozen=True)
class StateSnapshot:
    """What the UI needs to render the radio panel. Immutable; sent via queued signals."""
    state: str
    reason: Optional[str] = None
    port: Optional[PortCandidate] = None
    identity: Optional[RadioIdentity] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_at_local: Optional[int] = None
    retry_at_local: Optional[int] = None
    candidates: tuple[PortCandidate, ...] = field(default_factory=tuple)
    since_local: Optional[int] = None
