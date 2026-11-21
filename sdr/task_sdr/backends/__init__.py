# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Pluggable RECEIVE-ONLY SDR backends (SDR Studio, Phase 4G M1).

A backend lists devices (``enumerate``) without claiming them and opens one (``open``) as an object with the
receive API used by the engine: configure(rate, freq, gain, ppm) / set_frequency / set_gain / start / read(n) /
close / info(). There is deliberately NO transmit method in this interface, in any backend, real or stub.

Implemented in M1: ``rtlsdr`` (native librtlsdr via ctypes, RTL-SDR Blog V4 aware), ``soapy`` (optional, only if
python3-soapysdr is installed — never required), ``simulated`` (synthetic IQ). Stubs (clearly marked, not usable):
airspy, sdrplay, hackrf, lime, pluto, uhd, network.
"""

from dataclasses import dataclass, field


from task_sdr.freq import FrequencyError, is_hz, hz as _strict_hz  # noqa: E402

class RangeError(ValueError):
    """Frequency outside the selected receiver's verified tuning range."""


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    min_hz: int
    max_hz: int
    rates: tuple = ()
    note: str = ""

    def check(self, hz):
        try:
            hz = _strict_hz(hz)
        except FrequencyError as exc:
            raise RangeError(str(exc)) from None
        if not self.min_hz <= hz <= self.max_hz:
            raise RangeError(f"{hz / 1e6:.6f} MHz is outside the {self.name} range "
                             f"({self.min_hz / 1e6:g}–{self.max_hz / 1e6:g} MHz)")
        return hz

    def accepts(self, hz):
        return is_hz(hz, self.min_hz, self.max_hz)


RTL_RATES = (250_000, 1_024_000, 1_200_000, 1_920_000, 2_048_000, 2_400_000)
# Source: RTL-SDR Blog V4 datasheet v1.0 (rtl-sdr.com, 2024-12): "Frequency Range 500 kHz to 1.766 GHz",
# HF through a built-in 28.8 MHz upconverter handled by the driver.
RTL_BLOG_V4 = DeviceProfile("RTL-SDR Blog V4", 500_000, 1_766_000_000, RTL_RATES,
                            "R828D; HF 0.5–28.8 MHz via the built-in upconverter (driver-managed).")
# Other R820T/R820T2/R860 sticks (incl. Blog V3): HF needs direct sampling, not offered in M1 -> 24 MHz floor.
RTL_GENERIC = DeviceProfile("RTL-SDR (R820T/R860)", 24_000_000, 1_766_000_000, RTL_RATES,
                            "Below 24 MHz needs direct-sampling mode, which M1 does not enable.")
SIMULATED = DeviceProfile("SIMULATED receiver", 500_000, 1_766_000_000, RTL_RATES, "Synthetic IQ, no hardware.")


@dataclass
class DeviceInfo:
    backend: str
    index: int
    label: str
    serial: str = ""
    manufacturer: str = ""
    product: str = ""
    profile: DeviceProfile = RTL_GENERIC
    extra: dict = field(default_factory=dict)


class Backend:
    key = "base"
    name = "base"
    stub = False

    def available(self):
        """-> (bool, reason). Must not touch hardware."""
        return False, "not implemented"

    def enumerate(self):
        """-> [DeviceInfo]. Must not claim or configure any device."""
        return []

    def open(self, info: DeviceInfo):
        raise NotImplementedError


class StubBackend(Backend):
    stub = True

    def __init__(self, key, name, note):
        self.key, self.name, self.note = key, name, note

    def available(self):
        return False, f"STUB — {self.name} support is not implemented in SDR Studio M1. {self.note}"

    def open(self, info):
        raise NotImplementedError(self.available()[1])


def registry():
    from task_sdr.backends import rtlsdr, simulated, soapy
    return [
        rtlsdr.RtlSdrBackend(),
        soapy.SoapyBackend(),
        simulated.SimulatedBackend(),
        StubBackend("airspy", "Airspy (R2/Mini/HF+)", "Would use libairspy / libairspyhf, receive only."),
        StubBackend("sdrplay", "SDRplay RSP", "Would use the proprietary SDRplay API (licence check needed)."),
        StubBackend("hackrf", "HackRF One", "TX-capable hardware: a future backend must stay receive-only."),
        StubBackend("lime", "LimeSDR", "TX-capable hardware: a future backend must stay receive-only."),
        StubBackend("pluto", "ADALM-Pluto", "TX-capable hardware: a future backend must stay receive-only."),
        StubBackend("uhd", "Ettus USRP (UHD)", "TX-capable hardware: a future backend must stay receive-only."),
        StubBackend("network", "Network source (rtl_tcp / SpyServer)", "Would connect only to a user-entered "
                    "host; no discovery scanning of the network."),
    ]


def discover(backends=None):
    """Safe discovery: [(backend, available, reason, [DeviceInfo])]. Never opens/claims/configures a device;
    any backend exception is reported, not raised."""
    out = []
    for b in backends if backends is not None else registry():
        ok, why = b.available()
        devs = []
        if ok:
            try:
                devs = b.enumerate()
            except Exception as exc:  # noqa: BLE001
                ok, why = False, f"enumeration failed: {exc}"
        out.append((b, ok, why, devs))
    return out
