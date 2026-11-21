# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Safe snapshot of the library's live ``nodesByNum`` dict.

The reader thread mutates nodesByNum while we copy it; deepcopy can then raise
"RuntimeError: dictionary changed size during iteration". Retry a few times; never crash.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from task_mesh.domain.models import NodeInfoData
from task_mesh.radio.meshtastic.packets import PacketError, parse_nodeinfo


def copy_nodes_by_num(iface: Any, attempts: int = 5) -> list[dict]:
    for _ in range(attempts):
        try:
            nodes = getattr(iface, "nodesByNum", None) or {}
            return copy.deepcopy(list(nodes.values()))
        except RuntimeError:
            time.sleep(0.01)
    return []


def snapshot(iface: Any) -> tuple[list[NodeInfoData], int]:
    """Return (parsed nodes, number of malformed entries skipped)."""
    out: list[NodeInfoData] = []
    bad = 0
    for entry in copy_nodes_by_num(iface):
        try:
            out.append(parse_nodeinfo(entry))
        except PacketError:
            bad += 1
    return out, bad
