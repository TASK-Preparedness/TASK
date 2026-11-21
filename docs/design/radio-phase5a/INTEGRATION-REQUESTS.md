<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 integration requests — not approvals
1. Joshua's explicit approval to start simulator-only B, plus answers to seven questions in RISKS-AND-OPEN-QUESTIONS.md.
2. Approved shared task-aprs/controller fixes for ID reuse and ack freshness/channel/epoch, explicit authorization linkage and kill-safe write boundary; no duplicate Radio controller.
3. Approved task-comms extension for physical non-Direwolf transport facts/authorization, only after actual UV-PRO hardware validation. Existing evaluate_amateur does not support it.
4. Exact actual Direwolf configuration/port evidence, missing compatibility wrapper, full gpsd units and package/Qt dependency metadata.
5. Approval for future launcher tile/embedding separately; current task.radio remains unchanged. Generic panel plugin API is not installed.
6. Separate Mesh 0.3.2 source integration/package/test authorization from authoritative notifier; asset licensed/credited per MESH-AUDIO-PRESERVATION.md. No automatic restart or downgrade.
7. Later physical connection and RF authorization: firmware/channel/KISS evidence, ownership confirmation, licensed station/dummy load/second receiver and emergency procedure. Every hardware capability remains UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.

Firmware Manager stays independent. A source-review request is not permission for any of these implementation/deployment actions.
