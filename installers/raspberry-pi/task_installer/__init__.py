# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. Raspberry Pi installer (pre-alpha, 0.2.0.dev0).

Status: detection, compatibility gating, module planning, a text (TUI) front
end and a PySide6 wizard exist and are tested in SIMULATION only (fake
/proc, /sys and dpkg roots). Package installation is NOT executed by this
version: it prints the exact, reviewable commands (dry run). Real execution
will be enabled only after validated arm64 .debs exist and an approved
clean-Pi test passes.

UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST
"""
__version__ = "0.2.0.dev0"
