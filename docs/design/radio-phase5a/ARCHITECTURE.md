<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Radio r3.1 corrected architecture — proposal, not implementation
Authority: SOURCE-RECONCILIATION-r3.1.md and API-MATRIX.md supersede r2/r3 assumptions. This is docs-only. The Pi's installed working source wins over repository copies.

## Scope and layers
1. **Qt presentation**: a reusable PySide6 Radio widget hosted in an offline simulator test window. Monitor, messages, TX status, explicit simulation-enable/disable, timeout indication and prominent KILL. Blocking callbacks bridged onto GUI thread. No launcher modification in B.
2. **Thin session/enablement adapter** (proposed): memory-only epoch-bound TX permit, explicit typed-call confirmation, revoke on disable, KILL, idle expiry, session uncertainty, link loss, process/device/profile change. It narrows authority; it is not another licensing/duplicate/routing policy engine.
3. **Shared policy**: existing `task_comms.txpolicy.TxPolicy` and dataclasses. Its exact decision object is authoritative; do not implement a parallel policy hook. Test fixture facts may be synthetic but never become hardware-verification records. Direct UV-PRO is rejected by current transport/PTT gates; approved upstream extension is prerequisite for physical TX (`/usr/lib/python3/dist-packages/task_comms/txpolicy.py:169-204`).
4. **Existing APRS controller and packet processing**: `task_aprs.amateur.AmateurTx`, `task_aprs.rx.Receiver`, shared `task_comms.aprs` codec (full exact contracts in API-MATRIX). Message IDs/acks/retries remain one implementation, with safety changes proposed upstream rather than a Radio clone. Any wrapper adds metadata/checks, not a replacement scheduler or parser.
5. **Transport boundary**: simulator in-memory transport only in B; separate optional future physical package. No real transport factory in the simulator's allow-list; no automatic fallback to TCP/RFCOMM/BLE/serial. Real interfaces are deferred, not dormant imports.
6. **State/notifications/status**: existing comms EventLog/AuditLog/StatusWriter/NotificationStore with isolated radio/simulator paths and sources. No message bodies in audit/status. Store full text only in private user-owned state after session authorization. No production DB retention/pruning work in B. Shared desktop formatter is Mesh-specific; Radio requires a separately reviewed presentation adapter before notifications.

## Packet and service integration
Keep raw AX.25 bytes canonical; shared codec does KISS escaping and APRS decode. Metadata (source=SIMULATED, monotonic clock, connection epoch, local request ID) is separate and never guessed as RF measurements. No Radio `kiss/` codec, duplicate packet engine or copied codec oracle.

Installed `AmateurTx` consumes a duck-typed transport with `name`, `connected`, `send_raw(channel,frame)`, optional `has_queue_feedback/outstanding(channel)` (`/usr/lib/task-aprs/task_aprs/amateur.py:88-98,161-204`). The simulator can emulate the **Direwolf interface** to test existing policy/controller, while visibly SIMULATED, bound to synthetic identity and a simulation-only permit. This test-only emulation must not be used to relabel a physical UV-PRO as Direwolf. Avoid AprsService default construction: it loads saved TX settings and real TCP factories (`/usr/lib/task-aprs/task_aprs/service.py:24-50`). Construct safe dependencies explicitly; testing the service requires injecting both factories, all roots and a fixture DirewolfConfig.

## TX lifecycle and fail-closed design
Proposed states: disabled -> simulation-ready -> enabled -> submitted -> acked/rejected/no-ack/failed/cancelled. Display installed delivery semantics instead of misleading 'on air' claims (`/usr/lib/task-aprs/task_aprs/amateur.py:9-17`). `queued` is local/controller/TNC queue evidence only. UI TX enablement is distinct from status 'tx-capable' and shared config defaults.

An application command carries current session and device/profile/connection epoch. Before the final transport write: confirm live permit, same frame/target/epoch, unexpired monotonic deadline and current shared policy decision. Serialize cancellation and writes to avoid check/use races; KILL revokes epoch and drains pending application work first, without waiting on GUI or queue queries. B measures **zero new writes after kill returns**. No guarantee can be made for bytes already submitted to a physical TNC or a radio's own autonomous behavior; operator power/PTT control is necessary later.

No pending item auto-resumes after disconnect/reconnect, restart, service restart or session failure. Mark incomplete requests interrupted/cancelled; do not silently replay even if TX later re-enabled. Retry and auto-ack defaults are OFF, beaconing and forwarding absent. Q1 timeout proposal is 60 minutes idle, not yet approved. A short configurable simulated expiry is test input; it does not authorize RF defaults. Expiry does not refresh from RX packets or automatic retries.

## Message reliability: reuse and fixes, not promises
Existing controller decimal IDs reset/wrap, and received acks lack freshness/channel/epoch checks (`/usr/lib/task-aprs/task_aprs/amateur.py:72-77,227-250`). Propose a shared controller enhancement: allocate APRS ID1..5 within sender/recipient/channel/session namespace with recent-ID quarantine over maximum lifetime; separate durable local UUID/epoch from wire ID; reject stale and wrong-peer/channel/addressee acks. Persistence never includes TX enablement or automatic resend. Approval and tests are required before integration; B first records these cases as expected failures against the unchanged installed controller.

Existing retry_schedule gives cumulative 30,90,210... (`/usr/lib/python3/dist-packages/task_comms/txpolicy.py:281-289`). Proposed Q2 times 0/30/60/120/240 must not be silently substituted. B default send explicitly uses retries=0; scheduled retry tests use approved/synthetic policy fixtures only. Incoming messages never trigger Radio RF ack automatically. `ack_info` builds classic ack; APRS1.1 reply-ack is not a confirmed installed contract.

## Discovery, GPS, launcher and boundaries
No `start_scan` or Bluetooth inquiry action. Future known-device details can read cached state only, with separate approval before any connection. SPP UUID, user assertion or generic 'verified' flag is not physical KISS proof. UV-PRO firmware, RFCOMM channel, protocol and TX behavior: **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

Heltec belongs to Mesh; U-blox belongs to gpsd. Radio never opens them. GPS fix from gpsd integration in a future approved stage, not a nonexistent Core GPS RPC; B only synthetic fixes. Existing task-maps gpsd client is a useful reference but private-path import is not a stable shared API (`/usr/share/task-maps/task_maps/ui/main_window.py:213-217`).

Core v2 uses own session and read-only RPC; no device assignment or direct daemon Bus.publish. Capabilities are status, not TX authority. task-core-compat and migration sockets preserved.

The installed launcher already owns task.radio and dispatches task-aprs (`/usr/share/task-launcher/apps.d/030-radio.toml:3-20`; `/usr/share/task-launcher/task_launcher/ui/main_window.py:402-445`). Generic external plugin panels are not supported by its parser; medical alone is currently an embedded view (`ui/main_window.py:34-35`). Later launcher embedding/popout is a separate approval. No replacement of old tile, no new tile now.

## Milestones
B after approval: offline simulator/guard/controller reuse tests/Qt panels only. C: approved packaging and compatibility tests on a cloned/staging Debian 13 ARM64 image, still no RF. D: separately approved physical discovery/RX then licensed controlled TX with known firmware, policy answers and dummy load. Firmware Manager remains independent, no shared deliverable or hidden service changes.
