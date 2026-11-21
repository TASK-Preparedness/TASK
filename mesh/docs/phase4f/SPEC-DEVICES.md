<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# SPEC — Devices tile (Phase 4K)
* Keep id task.devices. Native view (launcher DevicesWindow) reading Core devices API (read-only for operator;
  assign/unassign administrator, enforced by Core). task-console remains an alternative exec.
* Show /dev/serial/by-id, USB VID:PID, current owner (from T.A.S.K. lock files in $XDG_RUNTIME_DIR/task/mesh-devices),
  Core assignment, protocol assignment from task-mesh radio-protocols.json (read-only here).
* Never opens a serial port; no probing from this tile. Tests: no open() on tty paths; admin action refused for operator.
