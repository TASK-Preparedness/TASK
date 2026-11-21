# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""User-facing error catalogue: stable codes, short titles and remedy text."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    NO_DEVICE = "NO_DEVICE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PORT_BUSY = "PORT_BUSY"
    HANDSHAKE_TIMEOUT = "HANDSHAKE_TIMEOUT"
    SERIAL_ERROR = "SERIAL_ERROR"
    CONNECTION_LOST = "CONNECTION_LOST"
    WATCHDOG = "WATCHDOG"
    LIBRARY_MISSING = "LIBRARY_MISSING"
    UNEXPECTED = "UNEXPECTED"


REMEDIES: dict[ErrorCode, tuple[str, str]] = {
    ErrorCode.NO_DEVICE: (
        "No radio found",
        "Connect the Meshtastic radio with a data-capable USB cable. It is detected automatically.",
    ),
    ErrorCode.PERMISSION_DENIED: (
        "Permission denied on the serial port",
        'Your user is not allowed to open the port. Run:  sudo usermod -aG dialout "$USER"  '
        "then log out and back in (a running session does not pick up the new group). "
        "Never run this app as root.",
    ),
    ErrorCode.PORT_BUSY: (
        "Serial port is in use",
        "Another program holds the port (another Meshtastic client, the meshtastic CLI, or a "
        "second copy of this app). Close it; reconnection is retried automatically.",
    ),
    ErrorCode.HANDSHAKE_TIMEOUT: (
        "Radio did not answer",
        "The port opened but the radio did not complete the Meshtastic handshake within about "
        "30 s. Check that it runs Meshtastic firmware and is not in bootloader mode; try a "
        "replug or pressing its reset button.",
    ),
    ErrorCode.SERIAL_ERROR: (
        "Serial communication error",
        "The serial link failed. Check the cable and USB port; reconnection is retried automatically.",
    ),
    ErrorCode.CONNECTION_LOST: (
        "Connection to radio lost",
        "The radio was unplugged, rebooted or stopped responding. Reconnection is retried automatically.",
    ),
    ErrorCode.WATCHDOG: (
        "Radio link watchdog tripped",
        "The connection stopped working (reader stopped or device vanished). Reconnecting.",
    ),
    ErrorCode.LIBRARY_MISSING: (
        "Meshtastic library not available",
        "The bundled meshtastic library could not be imported. Reinstall the task-mesh package.",
    ),
    ErrorCode.UNEXPECTED: (
        "Unexpected error",
        "An unexpected error occurred. Details are in the log file; reconnection is retried automatically.",
    ),
}


def title_for(code: ErrorCode) -> str:
    return REMEDIES.get(code, REMEDIES[ErrorCode.UNEXPECTED])[0]


def remedy_for(code: ErrorCode) -> str:
    return REMEDIES.get(code, REMEDIES[ErrorCode.UNEXPECTED])[1]
