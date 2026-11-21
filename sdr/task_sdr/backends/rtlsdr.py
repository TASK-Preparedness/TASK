# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Native RTL-SDR backend over librtlsdr (ctypes; Debian trixie: librtlsdr0 2.0.2, which contains the RTL-SDR
Blog V4 support merged upstream at Osmocom). RECEIVE ONLY.

Deliberately NOT bound: rtlsdr_set_bias_tee* (never powers an antenna/LNA), rtlsdr_set_direct_sampling,
rtlsdr_set_testmode, EEPROM writes. Only the receive calls below are declared.
"""

import ctypes
import ctypes.util

import numpy as np

from task_sdr.backends import RTL_BLOG_V4, RTL_GENERIC, Backend, DeviceInfo, RangeError
from task_sdr.device import DeviceBusy, DeviceError

LIB_NAMES = ("rtlsdr", )
LIBUSB_ERROR_ACCESS, LIBUSB_ERROR_BUSY = -3, -6
TUNERS = {0: "unknown", 1: "E4000", 2: "FC0012", 3: "FC0013", 4: "FC2580", 5: "R820T", 6: "R828D"}
ALLOWED_SYMBOLS = ("rtlsdr_get_device_count", "rtlsdr_get_device_name", "rtlsdr_get_device_usb_strings",
                   "rtlsdr_open", "rtlsdr_close", "rtlsdr_set_center_freq", "rtlsdr_get_center_freq",
                   "rtlsdr_set_freq_correction", "rtlsdr_get_tuner_type", "rtlsdr_get_tuner_gains",
                   "rtlsdr_set_tuner_gain", "rtlsdr_set_tuner_gain_mode", "rtlsdr_set_sample_rate",
                   "rtlsdr_set_agc_mode", "rtlsdr_reset_buffer", "rtlsdr_read_sync")


def load_library(loader=ctypes.CDLL):
    path = ctypes.util.find_library("rtlsdr") or "librtlsdr.so.0"
    try:
        lib = loader(path)
    except OSError as exc:
        raise DeviceError(f"librtlsdr not found ({exc}); install librtlsdr0 (Debian trixie 2.0.2 supports the "
                          "RTL-SDR Blog V4)") from None
    P, U32, I, CP = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_char_p
    sig = {"rtlsdr_get_device_count": (U32, []), "rtlsdr_get_device_name": (CP, [U32]),
           "rtlsdr_get_device_usb_strings": (I, [U32, CP, CP, CP]),
           "rtlsdr_open": (I, [ctypes.POINTER(P), U32]), "rtlsdr_close": (I, [P]),
           "rtlsdr_set_center_freq": (I, [P, U32]), "rtlsdr_get_center_freq": (U32, [P]),
           "rtlsdr_set_freq_correction": (I, [P, I]), "rtlsdr_get_tuner_type": (I, [P]),
           "rtlsdr_get_tuner_gains": (I, [P, ctypes.POINTER(I)]), "rtlsdr_set_tuner_gain": (I, [P, I]),
           "rtlsdr_set_tuner_gain_mode": (I, [P, I]), "rtlsdr_set_sample_rate": (I, [P, U32]),
           "rtlsdr_set_agc_mode": (I, [P, I]), "rtlsdr_reset_buffer": (I, [P]),
           "rtlsdr_read_sync": (I, [P, P, I, ctypes.POINTER(I)])}
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = res, args
    return lib


def profile_for(manufacturer, product):
    if "rtlsdrblog" in manufacturer.lower().replace("-", "").replace(" ", "") and "v4" in product.lower():
        return RTL_BLOG_V4
    return RTL_GENERIC


class RtlSdrBackend(Backend):
    key = "rtlsdr"
    name = "RTL-SDR (native librtlsdr)"

    def __init__(self, loader=ctypes.CDLL):
        self.loader = loader
        self._lib = None

    def lib(self):
        if self._lib is None:
            self._lib = load_library(self.loader)
        return self._lib

    def available(self):
        try:
            self.lib()
            return True, ""
        except DeviceError as exc:
            return False, str(exc)

    def enumerate(self):
        lib = self.lib()
        out = []
        for i in range(int(lib.rtlsdr_get_device_count())):
            m, p, s = (ctypes.create_string_buffer(256) for _ in range(3))
            rc = lib.rtlsdr_get_device_usb_strings(i, m, p, s)
            man, prod, ser = (b.value.decode(errors="replace") for b in (m, p, s)) if rc == 0 else ("", "", "")
            name = (lib.rtlsdr_get_device_name(i) or b"RTL-SDR").decode(errors="replace")
            prof = profile_for(man, prod)
            out.append(DeviceInfo("rtlsdr", i, f"{prod or name}" + (f" (SN {ser})" if ser else ""), ser, man, prod,
                                  prof, {"usb_strings_ok": rc == 0}))
        return out

    def open(self, info):
        return RtlSdrDevice(self.lib(), info)


class RtlSdrDevice:
    def __init__(self, lib, info):
        self.lib, self.info_ = lib, info
        self.profile = info.profile
        self.h = ctypes.c_void_p()
        rc = lib.rtlsdr_open(ctypes.byref(self.h), int(info.index))
        if rc == LIBUSB_ERROR_BUSY:
            raise DeviceBusy("the SDR is in use by another program")
        if rc == LIBUSB_ERROR_ACCESS:
            raise DeviceError("no permission for the RTL-SDR USB device (udev rules / plugdev group)")
        if rc < 0:
            raise DeviceError(f"rtlsdr_open failed ({rc}); another program (SDR++, rtl_tcp, dump1090) may hold "
                              "it, or the kernel DVB driver is bound")
        self.rate = None
        self.tuner = TUNERS.get(int(lib.rtlsdr_get_tuner_type(self.h)), "unknown")
        n = lib.rtlsdr_get_tuner_gains(self.h, None)
        arr = (ctypes.c_int * max(n, 0))()
        if n > 0:
            lib.rtlsdr_get_tuner_gains(self.h, arr)
        self.gains_db = [g / 10 for g in arr]

    def info(self):
        g = f"{self.gains_db[0]}–{self.gains_db[-1]} dB ({len(self.gains_db)} steps)" if self.gains_db else "?"
        return {"hardware": f"{self.info_.label} [{self.tuner}]", "info": {"profile": self.profile.name},
                "gain_range": g}

    def _ok(self, rc, what):
        if rc < 0:
            raise DeviceError(f"{what} failed ({rc})")

    def configure(self, rate, freq_hz, gain_db=None, ppm=0):
        self._ok(self.lib.rtlsdr_set_sample_rate(self.h, int(rate)), "set sample rate")
        self.rate = int(rate)
        if ppm:
            rc = self.lib.rtlsdr_set_freq_correction(self.h, int(ppm))
            if rc < 0 and rc != -2:                      # -2: unchanged
                raise DeviceError(f"set ppm failed ({rc})")
        self.set_frequency(freq_hz)
        self.set_gain(gain_db)
        self.lib.rtlsdr_set_agc_mode(self.h, 0)

    def set_frequency(self, hz):
        hz = self.profile.check(hz)                      # never outside the verified range
        if not 0 < hz < 2**32:                           # librtlsdr takes uint32 Hz; never let ctypes wrap it
            raise RangeError(f"{hz} Hz cannot be passed to librtlsdr (uint32)")
        self._ok(self.lib.rtlsdr_set_center_freq(self.h, hz), "tune")

    def set_gain(self, gain_db):
        if gain_db is None:
            self._ok(self.lib.rtlsdr_set_tuner_gain_mode(self.h, 0), "auto gain")
            return
        self._ok(self.lib.rtlsdr_set_tuner_gain_mode(self.h, 1), "manual gain")
        g = min(self.gains_db, key=lambda x: abs(x - float(gain_db))) if self.gains_db else float(gain_db)
        self._ok(self.lib.rtlsdr_set_tuner_gain(self.h, int(round(g * 10))), "set gain")

    def start(self):
        self._ok(self.lib.rtlsdr_reset_buffer(self.h), "reset buffer")

    def read(self, n):
        nbytes = 2 * int(n)
        nbytes -= nbytes % 512                            # librtlsdr wants multiples of 512
        buf = (ctypes.c_uint8 * nbytes)()
        got = ctypes.c_int(0)
        rc = self.lib.rtlsdr_read_sync(self.h, buf, nbytes, ctypes.byref(got))
        if rc < 0:
            raise DeviceError(f"read failed ({rc}) — unplugged?")
        u = np.frombuffer(buf, np.uint8, got.value).astype(np.float32)
        u = (u - 127.4) / 128.0
        return (u[0::2] + 1j * u[1::2]).astype(np.complex64)

    def close(self):
        if self.h:
            self.lib.rtlsdr_close(self.h)
            self.h = ctypes.c_void_p()
