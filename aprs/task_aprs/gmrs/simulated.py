# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SIMULATED GMRS hand-held. Nothing is transmitted and no hardware is opened; it records requests and can
inject received packets. Labelled "SIMULATION" everywhere it appears."""

import time

from task_aprs.gmrs.driver import DriverCapabilities, GmrsDriver, GmrsReceived, register


@register
class SimulatedGmrsDriver(GmrsDriver):
    id = "simulated"

    def __init__(self, channel_mhz=462.5625, burst_s=0.4, clock=time.time, fail=False):
        self.channel_mhz, self.burst_s, self.clock, self.fail = channel_mhz, burst_s, clock, fail
        self.sent = []
        self._open = False
        self._rx_cb = None

    def capabilities(self):
        return DriverCapabilities(model="SIMULATED GMRS hand-held", fcc_id="SIMULATION", handheld=True,
                                  integral_antenna=True, builtin_data=True, can_send_location=True,
                                  can_send_text=True, can_request_location=True, can_receive=True,
                                  max_text_chars=64, max_burst_s=self.burst_s, simulated=True)

    def open(self):
        self._open = True

    def close(self):
        self._open = False

    @property
    def connected(self):
        return self._open

    def current_channel_mhz(self):
        return self.channel_mhz

    def request_transmit(self, kind, *, recipient="", text="", lat=None, lon=None):
        if not self._open:
            raise OSError("simulated radio not open")
        if self.fail:
            raise OSError("simulated radio refused the request")
        self.sent.append({"kind": kind, "recipient": recipient, "text": text, "lat": lat, "lon": lon,
                          "channel_mhz": self.channel_mhz})
        return self.burst_s

    def inject(self, kind, sender, **kw):
        pkt = GmrsReceived(self.clock(), kind, sender, channel_mhz=self.channel_mhz, **kw)
        if self._rx_cb:
            self._rx_cb(pkt)
        return pkt
