# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Bridge interface STUB (task-mesh 0.3.0). No relay or forwarding between protocols exists.

A future, separately approved feature could forward messages between Meshtastic and MeshCore. That would
transmit on behalf of others and needs its own licensing/policy review, so 0.3.0 ships only this interface.
Every method raises; the hub never calls it.
"""

from __future__ import annotations


class BridgeDisabled(RuntimeError):
    pass


class Bridge:
    enabled = False

    def forward(self, message, to_protocol: str):  # pragma: no cover - interface only
        raise BridgeDisabled("protocol bridging is not implemented in task-mesh 0.3.0 (no relay, no forwarding)")
