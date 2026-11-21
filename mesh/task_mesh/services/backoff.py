# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Exponential reconnect backoff with jitter: 1, 2, 4, 8, 16, 30, 30 ... seconds (±20 %)."""

from __future__ import annotations

import random
from typing import Callable, Optional


class Backoff:
    def __init__(
        self,
        base: float = 1.0,
        factor: float = 2.0,
        cap: float = 30.0,
        jitter: float = 0.2,
        rand: Optional[Callable[[], float]] = None,
    ) -> None:
        self.base, self.factor, self.cap, self.jitter = base, factor, cap, jitter
        self._rand = rand or random.random
        self.attempt = 0

    def nominal(self, attempt: int) -> float:
        return min(self.cap, self.base * (self.factor ** attempt))

    def next_delay(self) -> float:
        nominal = self.nominal(self.attempt)
        self.attempt += 1
        spread = nominal * self.jitter
        return max(0.1, nominal - spread + 2 * spread * self._rand())

    def reset(self) -> None:
        self.attempt = 0
