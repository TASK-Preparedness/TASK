# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Radio provider contract. Small on purpose: Meshtastic, the test fake and future providers
(gpsd/APRS feeds have their own, similar seams) plug in here."""

from __future__ import annotations

from typing import Optional, Protocol

from task_mesh.core.errors import ErrorCode
from task_mesh.domain.models import NodeInfoData, Observation, PortCandidate, RadioEvent, RadioIdentity


class ConnectError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RadioEventSink(Protocol):
    """Called from library threads. Implementations must be thread-safe (e.g. emit Qt signals)."""

    def on_established(self, generation: int) -> None: ...
    def on_lost(self, generation: int) -> None: ...
    def on_nodeinfo(self, generation: int, info: NodeInfoData) -> None: ...
    def on_observation(self, generation: int, obs: Observation) -> None: ...
    def on_radio_event(self, generation: int, event: RadioEvent) -> None: ...


class RadioProvider(Protocol):
    def connect(self, candidate: PortCandidate, generation: int) -> RadioIdentity:
        """Blocking open + handshake. Raises ConnectError. Never call on the GUI thread."""

    def close(self) -> None:
        """Release the port. Safe to call repeatedly or after the device vanished."""

    def is_alive(self) -> bool:
        """True while the underlying reader is running."""

    def port_open(self) -> bool:
        """True while the library still holds an open stream."""

    def snapshot_nodes(self) -> list[NodeInfoData]: ...

    def send_heartbeat(self) -> None:
        """Write-only link probe; raises on serial failure."""

    @property
    def current_generation(self) -> Optional[int]: ...
