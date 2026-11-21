# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GMRS radio-integration driver interface.

A driver controls a certified GMRS hand-held over its own control link (USB/serial/Bluetooth) and asks the
radio to transmit a data packet that the radio itself generates. Drivers report facts; the policy decides."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DriverCapabilities:
    model: str
    fcc_id: str = ""
    handheld: bool = False
    integral_antenna: bool = False
    builtin_data: bool = False
    can_send_location: bool = False
    can_send_text: bool = False
    can_request_location: bool = False
    can_receive: bool = False
    max_text_chars: int = 0
    max_burst_s: float = None        # radio/driver-reported data burst duration
    verified_on_hardware: bool = False
    simulated: bool = False


@dataclass
class GmrsReceived:
    ts: float
    kind: str                        # location | location-request | text
    sender: str                      # radio unit id / call sign as reported by the radio
    lat: float = None
    lon: float = None
    text: str = ""
    channel_mhz: float = None


class GmrsDriver(ABC):
    id = "abstract"

    @abstractmethod
    def capabilities(self) -> DriverCapabilities: ...

    @abstractmethod
    def open(self): ...

    @abstractmethod
    def close(self): ...

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def current_channel_mhz(self): ...

    @abstractmethod
    def request_transmit(self, kind: str, *, recipient: str = "", text: str = "", lat=None, lon=None) -> float:
        """Ask the radio to send its own data packet; returns the radio-reported burst duration (s).
        Raise OSError on failure. Must never be called except by GmrsTx after a policy 'allowed'."""

    def set_receive_callback(self, cb):
        self._rx_cb = cb


DRIVERS = {}


def register(cls):
    DRIVERS[cls.id] = cls
    return cls
