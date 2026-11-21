# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Protocol adapters (one per mesh protocol). Each owns one serial device, normalises everything into
task_mesh.hub.model records and exposes send_text() for explicit user actions only."""
