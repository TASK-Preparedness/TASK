# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Optional SoapySDR backend (RTL-SDR via soapysdr-module-rtlsdr). Never required: absent python3-soapysdr just
marks this backend unavailable. Receive only."""

import importlib

from task_sdr.backends import Backend, DeviceInfo
from task_sdr.backends.rtlsdr import profile_for
from task_sdr.device import SoapyDevice, enumerate_devices


class SoapyBackend(Backend):
    key = "soapy"
    name = "SoapySDR (optional)"

    def available(self):
        try:
            importlib.import_module("SoapySDR")
            return True, ""
        except (ImportError, OSError) as exc:
            return False, f"python3-soapysdr not installed ({type(exc).__name__}); optional"

    def enumerate(self):
        out = []
        for i, d in enumerate(enumerate_devices()):
            man = d["args"].get("manufacturer", "RTLSDRBlog" if d.get("blog_v4") else "")
            prof = profile_for(man, "Blog V4" if d.get("blog_v4") else d["label"])
            out.append(DeviceInfo("soapy", i, d["label"], d["serial"], man, d["label"], prof, {"args": d["args"]}))
        return out

    def open(self, info):
        dev = SoapyDevice(info.extra["args"])
        dev.profile = info.profile
        orig = dev.set_frequency
        dev.set_frequency = lambda hz: orig(info.profile.check(hz))
        return dev
