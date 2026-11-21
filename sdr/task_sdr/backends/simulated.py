# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SIMULATED receiver: synthetic IQ (task_sdr.device.FakeDevice). Always available; labelled everywhere."""

from task_sdr.backends import SIMULATED, Backend, DeviceInfo
from task_sdr.device import FakeDevice

DEFAULT_SIGNALS = [(25_000, "fm", {"dev": 5000, "af": 700}), (-150_000, "am", {"depth": 0.6, "af": 400, "amp": 0.2}),
                   (300_000, "tone", {"amp": 0.05})]


class SimulatedBackend(Backend):
    key = "simulated"
    name = "SIMULATED (synthetic IQ)"

    def __init__(self, signals=None, pace=True):
        self.signals, self.pace = signals or DEFAULT_SIGNALS, pace

    def available(self):
        return True, ""

    def enumerate(self):
        return [DeviceInfo("simulated", 0, "SIMULATED receiver", profile=SIMULATED)]

    def open(self, info):
        d = FakeDevice(self.signals, pace=self.pace)
        d.profile = info.profile
        orig = d.set_frequency
        d.set_frequency = lambda hz: orig(info.profile.check(hz))
        return d
