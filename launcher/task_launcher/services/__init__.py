# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A read-only service probes and parsers (Kiwix, Direwolf/APRS, task-mesh, weather, medical,
GPS and SDR readiness).

Rules for everything in this package:

* read-only: files are only read, local services are only queried, nothing is configured;
* loopback only: network access is restricted to 127.0.0.1 / ::1 (``probe.ensure_loopback``);
* bounded: every subprocess, socket and HTTP call has a short timeout and a size cap;
* no shell: subprocesses are argv lists with absolute program paths (``probe.run_readonly``);
* blocking calls run in background threads (workers.PollWorker), never on the GUI thread.
"""
