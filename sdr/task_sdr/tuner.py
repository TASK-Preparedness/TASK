# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Digit tuner logic (pure Python, no Qt): 11 digits shown as GG.MMM.kkk.hhh ("00.000.000.000" = GHz.MHz.kHz.Hz).

Digit k counts from the right (k=0 is 1 Hz, k=10 is 10 GHz). Stepping adds/subtracts 10**k as an integer, so carry
and borrow across digits happen naturally. A step or entry that would leave the receiver's range is REJECTED
(value unchanged, reason returned) — never clamped silently, never wrapped.
"""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from task_sdr.freq import FrequencyError, hz as _strict_hz

DIGITS = 11
MAX_DISPLAY = 10 ** DIGITS - 1


def format_hz(hz):
    s = f"{int(hz):011d}"
    return f"{s[0:2]}.{s[2:5]}.{s[5:8]}.{s[8:11]}"


_UNITS = {"": None, "hz": 1, "k": 10**3, "khz": 10**3, "m": 10**6, "mhz": 10**6, "g": 10**9, "ghz": 10**9}
MAX_TEXT = 40


def parse(text):
    """'146.52M' / '146.52 MHz' / '1.2G' / '162550000' / '00.162.550.000' / '146.52' (plain decimal = MHz).
    -> int Hz, or raises ValueError."""
    if len(str(text)) > MAX_TEXT:
        raise ValueError("frequency text too long")
    t = str(text).strip().lower().replace(",", "").replace("_", "").replace(" ", "")
    m = re.fullmatch(r"([0-9.]+)([a-z]*)", t)
    if not m or m.group(2) not in _UNITS:
        raise ValueError(f"not a frequency: {text!r}")
    num, unit = m.group(1), m.group(2)
    if num.count(".") >= 2:                     # digit-group form 00.000.000.000
        if unit:
            raise ValueError("grouped digits take no unit")
        groups = num.split(".")
        if not all(g.isdigit() for g in groups):
            raise ValueError(f"not a frequency: {text!r}")
        return int("".join(groups))
    mult = _UNITS[unit]
    if mult is None:
        mult = 10**6 if "." in num else 1        # plain decimal is MHz; plain integer is Hz
    try:                                          # exact decimal arithmetic: no float rounding at GHz
        hz = int((Decimal(num) * mult).to_integral_value(rounding=ROUND_HALF_EVEN))
    except (InvalidOperation, ValueError):
        raise ValueError(f"not a frequency: {text!r}") from None
    if hz < 0 or hz > MAX_DISPLAY:
        raise ValueError("out of the 11-digit display range")
    return int(hz)


class DigitTuner:
    def __init__(self, hz, accepts=lambda hz: True, why=lambda hz: "outside the receiver's range"):
        self.accepts, self.why = accepts, why
        hz = _strict_hz(hz)
        if not accepts(hz):
            raise ValueError(why(hz))
        self.hz = hz
        self.cursor = 6                              # kHz digit selected by default
        self.last_rejection = ""

    @property
    def text(self):
        return format_hz(self.hz)

    def digit(self, k):
        return (self.hz // 10 ** k) % 10

    def _try(self, new):
        try:
            new = _strict_hz(new, lo=-10**12, hi=10**12)   # type check; range checks follow
        except FrequencyError as exc:
            self.last_rejection = str(exc)
            return False
        if new < 0 or new > MAX_DISPLAY or not self.accepts(new):
            self.last_rejection = self.why(new) if 0 <= new <= MAX_DISPLAY else "outside the display range"
            return False
        self.hz, self.last_rejection = int(new), ""
        return True

    def step(self, k, direction):
        """direction +1 (top half / wheel up / Up) or -1. Carries/borrows; rejected if out of range."""
        if not 0 <= k < DIGITS:
            raise IndexError(k)
        return self._try(self.hz + (1 if direction > 0 else -1) * 10 ** k)

    def set_digit(self, k, d):
        if not (0 <= k < DIGITS and 0 <= int(d) <= 9):
            raise ValueError("bad digit")
        return self._try(self.hz - self.digit(k) * 10 ** k + int(d) * 10 ** k)

    def type_digit(self, d):
        ok = self.set_digit(self.cursor, d)
        if ok and self.cursor > 0:
            self.cursor -= 1
        return ok

    def move_cursor(self, delta):
        """delta -1 = Left (towards GHz), +1 = Right (towards Hz)."""
        self.cursor = min(DIGITS - 1, max(0, self.cursor - delta))
        return self.cursor

    def set_hz(self, hz):
        return self._try(hz)

    def enter(self, text):
        try:
            hz = parse(text)
        except ValueError as exc:
            self.last_rejection = str(exc)
            return False
        return self._try(hz)
