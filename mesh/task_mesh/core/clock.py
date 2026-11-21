# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Injectable clock (tests freeze it) and clock plausibility helpers."""

from __future__ import annotations

import time
from typing import Optional

# Anything earlier than 2025-01-01 is treated as an unset/implausible clock.
PLAUSIBLE_EPOCH_MIN = 1735689600


class Clock:
    def now(self) -> int:
        return int(time.time())

    def monotonic(self) -> float:
        return time.monotonic()


class FrozenClock(Clock):
    def __init__(self, now: int = 1790000000) -> None:
        self._now = now
        self._mono = 1000.0

    def now(self) -> int:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += int(seconds)
        self._mono += seconds


def plausible_epoch(value: Optional[int]) -> bool:
    return value is not None and value >= PLAUSIBLE_EPOCH_MIN
