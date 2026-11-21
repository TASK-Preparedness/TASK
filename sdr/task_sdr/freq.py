# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""One strict definition of a frequency: an exact Python integer number of Hz (arbitrary precision, so no
32-bit or float limit). Floats, strings, booleans, None, NaN and infinity are refused rather than coerced.
Each receiver's own min/max range is applied separately (backends.DeviceProfile)."""

import numbers

ABS_MAX_HZ = 99_999_999_999          # 11-digit tuner display (10 GHz digit); far above 2**32


class FrequencyError(ValueError):
    """Not a valid integer-Hz frequency."""


def hz(value, what="frequency", lo=0, hi=ABS_MAX_HZ):
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise FrequencyError(f"{what} must be a whole number of Hz (got {type(value).__name__})")
    v = int(value)                    # numpy int64 etc. -> exact Python int
    if not lo <= v <= hi:
        raise FrequencyError(f"{what} {v} Hz is outside {lo}..{hi} Hz")
    return v


def is_hz(value, lo=0, hi=ABS_MAX_HZ):
    try:
        hz(value, lo=lo, hi=hi)
        return True
    except FrequencyError:
        return False
