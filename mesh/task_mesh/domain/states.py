# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Connection state machine: states, the legal-transition table and UI badge mapping."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    NO_DEVICE = "NO_DEVICE"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PORT_BUSY = "PORT_BUSY"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEVICE_REBOOTING = "DEVICE_REBOOTING"
    DISCONNECTING = "DISCONNECTING"
    BACKOFF = "BACKOFF"
    ERROR = "ERROR"


S = ConnectionState
_DISCONNECTED_IDLE = {S.IDLE, S.SCANNING}

TRANSITIONS: dict[ConnectionState, frozenset[ConnectionState]] = {
    S.IDLE: frozenset({S.SCANNING}),
    S.SCANNING: frozenset({S.NO_DEVICE, S.AWAITING_SELECTION, S.PERMISSION_DENIED, S.CONNECTING, S.IDLE, S.ERROR}),
    S.NO_DEVICE: frozenset({S.SCANNING, S.IDLE}),
    S.AWAITING_SELECTION: frozenset({S.CONNECTING, S.SCANNING, S.PERMISSION_DENIED, S.NO_DEVICE, S.IDLE}),
    S.PERMISSION_DENIED: frozenset({S.SCANNING, S.CONNECTING, S.IDLE}),
    S.PORT_BUSY: frozenset({S.BACKOFF, S.IDLE}),
    S.CONNECTING: frozenset(
        {S.CONNECTED, S.NO_DEVICE, S.PERMISSION_DENIED, S.PORT_BUSY, S.BACKOFF, S.DISCONNECTING, S.ERROR}
    ),
    S.CONNECTED: frozenset({S.DEVICE_REBOOTING, S.DISCONNECTING}),
    S.DEVICE_REBOOTING: frozenset({S.CONNECTED, S.DISCONNECTING}),
    S.DISCONNECTING: frozenset({S.BACKOFF, S.IDLE}),
    S.BACKOFF: frozenset({S.SCANNING, S.IDLE}),
    S.ERROR: frozenset({S.BACKOFF, S.IDLE}),
}


class Badge(str, Enum):
    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING…"
    DISCONNECTED = "DISCONNECTED"


def badge_for(state: ConnectionState) -> Badge:
    if state is S.CONNECTED:
        return Badge.CONNECTED
    if state in (S.CONNECTING, S.DEVICE_REBOOTING):
        return Badge.CONNECTING
    return Badge.DISCONNECTED


DESCRIPTIONS: dict[ConnectionState, str] = {
    S.IDLE: "Stopped — press Connect",
    S.SCANNING: "Scanning USB serial ports…",
    S.NO_DEVICE: "No radio detected — waiting for USB device",
    S.AWAITING_SELECTION: "Several possible radios — choose one",
    S.PERMISSION_DENIED: "Permission denied on serial port",
    S.PORT_BUSY: "Serial port busy",
    S.CONNECTING: "Opening port and downloading node database (up to ~30 s)…",
    S.CONNECTED: "Connected",
    S.DEVICE_REBOOTING: "Radio rebooting — waiting for it to return…",
    S.DISCONNECTING: "Disconnecting…",
    S.BACKOFF: "Disconnected — will retry",
    S.ERROR: "Unexpected error",
}


def is_legal(src: ConnectionState, dst: ConnectionState) -> bool:
    return dst in TRANSITIONS.get(src, frozenset())


class StateMachine:
    """Validates transitions. Invalid transitions are logged and ignored (never raise)."""

    def __init__(
        self,
        initial: ConnectionState = S.IDLE,
        on_transition: Optional[Callable[[ConnectionState, ConnectionState, Optional[str]], None]] = None,
    ) -> None:
        self.state = initial
        self._on_transition = on_transition
        self.history: list[tuple[ConnectionState, ConnectionState, Optional[str]]] = []

    def transition(self, dst: ConnectionState, reason: Optional[str] = None) -> bool:
        src = self.state
        if src is dst:
            return False
        if not is_legal(src, dst):
            log.warning(
                "illegal state transition ignored",
                extra={"event": "radio.state_illegal", "from_state": src.value, "to_state": dst.value,
                       "reason": reason},
            )
            return False
        self.state = dst
        self.history.append((src, dst, reason))
        log.info(
            "radio state %s -> %s", src.value, dst.value,
            extra={"event": "radio.state", "from_state": src.value, "to_state": dst.value, "reason": reason},
        )
        if self._on_transition is not None:
            try:
                self._on_transition(src, dst, reason)
            except Exception:  # noqa: BLE001
                log.exception("transition callback failed")
        return True
