# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Generalised geographic entity model (for v0.2 map layers). No rendering in v0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from task_mesh.domain.models import NodeRecord


class Layer(str, Enum):
    MESHTASTIC = "meshtastic"
    TASK_GPS = "rain_gps"  # stored value kept from 0.1.0 for database compatibility
    APRS = "aprs"
    WAYPOINT = "waypoint"
    INCIDENT = "incident"
    RESOURCE = "resource"
    USER_MARKER = "user_marker"


@dataclass(frozen=True)
class GeoEntity:
    id: str
    kind: str
    layer: Layer
    latitude: float
    longitude: float
    altitude_m: Optional[float] = None
    time_local: Optional[int] = None
    accuracy_m: Optional[float] = None
    source: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)


def node_to_geo(node: NodeRecord) -> Optional[GeoEntity]:
    """Project a mesh node into the entity model; None when its position is unknown."""
    if node.latitude is None or node.longitude is None:
        return None
    return GeoEntity(
        id=f"meshtastic:{node.node_num}",
        kind="mesh_node",
        layer=Layer.MESHTASTIC,
        latitude=node.latitude,
        longitude=node.longitude,
        altitude_m=node.altitude_m,
        time_local=node.last_rx_local,
        source="radio",
        attributes={"short_name": node.short_name, "long_name": node.long_name},
    )
