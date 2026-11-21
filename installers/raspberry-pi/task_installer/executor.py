# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Plan execution.

Only the dry-run executor exists in 0.1.0.dev0. A real executor (running
privileged apt steps through sudo in a terminal, never a root GUI) will be
added after validated arm64 packages exist and a clean-Pi test is approved.
"""
from __future__ import annotations

from .plan import Plan, assert_safe


class DryRunExecutor:
    def __init__(self, out=print):
        self.out = out

    def run(self, plan: Plan, progress=None) -> int:
        assert_safe(plan)
        n = len(plan.steps)
        for i, step in enumerate(plan.steps, 1):
            if progress:
                progress(i, n, step.description)
            self.out(f"[dry run {i}/{n}] {step.description}")
        return 0


class RealExecutor:  # pragma: no cover - intentionally disabled
    def __init__(self, *a, **k):
        raise NotImplementedError(
            "Real installation is disabled in this pre-alpha installer: no validated arm64 packages yet. "
            "UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST")
