# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-mesh 0.3.0 hub: protocol-neutral message model, store, notifications, device ownership, IPC.

Qt-free. Used by the headless task-mesh-service (systemd --user, disabled by default) and, when the
service is not running, in-process by the GUI. Exactly one process owns a radio (per-device lock)."""
