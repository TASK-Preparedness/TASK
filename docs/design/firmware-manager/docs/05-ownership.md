# 5. Device/service ownership and transaction coordination

Proposed behavior only. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. Integration interfaces have NOT been inspected. Current state below is Joshua's t69u report [U69], not new Pi observations.

## r2 first-device nomination

Joshua conditionally nominated the working Heltec V3 915 MHz [U72]; [document 12](12-heltec-v3-first-test.md) adds gated identification, private backup and same-version rehearsal. This does not authorize a service/port/device action. Original ownership and preservation boundaries below are unchanged.

## Ownership matrix

| Resource | Current legitimate owner/state | Firmware Manager boundary |
|---|---|---|
| Heltec V3 persistent by-id path ending `CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0`, currently ttyUSB0 | `task-mesh-service.service`, user-level; active/running, disabled for automatic startup | Observe descriptors only until approved coordinated release. Exclusive maintenance lease required before any serial open/reset/probe/backup/flash. Restore prior runtime intent without enabling autostart. |
| U-blox GPS, persistent identity resolves to `/dev/ttyACM0` | `gpsd.service`, active | Denylist by persistent identity, physical topology and descriptors; never open/reset/probe/stop it. Do not trust ttyACM numbering. GPS remains owned by gpsd. |
| Other future supported USB board | Owner unknown until inventory/ownership review | Passive detection only. Unknown owner/ambiguous identity = blocked. No “claim first device” behavior. |
| UV-PRO/Bluetooth and APRS radios | Existing Radio/APRS ownership to be reviewed; no active RFCOMM in inventory | Entirely outside initial Firmware Manager flashing scope. No Bluetooth trust/pair/settings changes and no RF testing. |
| Core device registry/bus | task-core 0.3.0 + compat 0.3.0, core service active/enabled | Consume reviewed registry/maintenance semantics. Do not restart/change Core or compatibility behavior. |
| Shared communication policy/ownership/notifications | python3-task-comms 0.3.1 | Reuse reviewed ownership and policy interfaces; do not implement a competing global ownership authority. |
| Mesh notification/audio | task-mesh 0.3.1 + hardware-tested local notifier/sound | Never replace files, alter filtering or change global sound configuration. Coordination outage is explicit and bounded. |
| SDR/audio stack, Direwolf, Xastir, SoapySDR, unrelated serial/USB devices | Existing owners | No stops, reloads, reset, package changes or device opens. |

Resolve exact U-blox by-id spelling from inventory/source bundle, not a manually retyped path (the supplied messages vary in punctuation). Deny physical identity across aliases, not just one string. Firmware Manager must never use “all ports” esptool autodetection [S06,S08].

## Source-review gate

Use the **same sanitized installed-source bundle requested by Radio r3**, not another competing inventory assumption. Detailed file list is in document 11. Review `task_comms/ownership.py`, `txpolicy.py`, `core.py`, `events.py`, `status.py`, notifications/bridge, plus `task_core/devices.py`, `api.py`, protocol/auth/sessions/socket paths, enumerator and module definitions. Review Mesh connection/service lifecycle and launcher interfaces. Source names do not prove methods or an existing maintenance protocol exists.

Needed semantics (requests, NOT invented API signatures):

- Get current owner, canonical physical identity, leases, maintenance and permission state.
- Obtain an atomic maintenance reservation covering all runtime/boot aliases and re-enumerations; fence out reconnection before closing the existing owner.
- Ask owning service to quiesce TX/queues/notifications, close this one selected port and acknowledge release; prevent its automatic reconnect during maintenance.
- Keep ownership reservation durable across frontend crash/USB reset, without granting a new process permission to resume writing.
- Return ownership to the correct family/role adapter only after compatibility and safety checks; retain prior service enablement policy.

If installed APIs do not provide these semantics, stop for an integration proposal and approval. A separate lock file or a one-time `lsof` check alone cannot coordinate competing processes. Do not patch Core, Mesh or task-comms silently to manufacture the contract.

## Controlled lifecycle (future, separate approvals)

`DETECTED → REVIEWED → MAINTENANCE_CONSENT → RESERVED → OWNER_RELEASED → IDENTIFIED → BACKED_UP_OR_ACKNOWLEDGED → PLAN_CONFIRMED → BOOTLOADER → WRITING → BYTE_VERIFIED → BOOT_QUARANTINE → RECONNECTION_REVIEW → OWNER_REACQUIRED / RECOVERY_REQUIRED`

1. Passive discovery reads sysfs/udev and reviewed registry events only; never open serial “to see what it is.” It must not transmit or trigger DTR/RTS. Show current service owner and notification outage.
2. User chooses one physical device and approves maintenance release. Snapshot prior service active state, enabled state and selected transport (metadata only; no secret logging).
3. Reserve device through existing reviewed ownership mechanism; inhibit owner reconnect; request cooperative release. If unsupported, propose a separately confirmed user-level stop of **only** `task-mesh-service.service`, never Core/gpsd. No stop batch is authorized/executed here; r2 document 12 names a possible user-service command solely for later explicit approval. Stopping is an explicit fallback, not default integration.
4. Confirm release via broker acknowledgement and applicable open-handle/OS exclusive checks. Permission-limited process inspection cannot prove absence of every owner. Unknown/conflict = abort without opening. Never kill unrelated processes, unbind USB drivers or reset an entire hub.
5. Identity check after release: VID/PID + USB serial + topology + approved PCB/revision/RF-chip/band evidence; then esptool explicit-port chip ID/MAC, silicon and flash capacity. Probing may reset into the ROM bootloader [S19,S20]; requires consent and RF containment even though it does not write flash. MAC identifies the MCU, **not** the exact board. V3/V3.2 or SX1276/SX1262 ambiguities require manual/photo/registry confirmation, not a confidence percentage guess.
6. Capture supported settings through the owning service before release if feasible, otherwise a reviewed local adapter under the exclusive lease; close backup adapter before flash tool. Failure/unsupported coverage produces a warning and a separately acknowledged data-loss choice; never silently claim backup success.
7. Confirm final immutable plan: physical device identity/MAC, family/version/role, every segment/hash/range, erase and bond/key/history losses, backup status, service outage, RF boot conditions and recovery fallback. Typed device-specific confirmation, non-persistent and invalidated by any device/image/plan change. Maintenance consent is not flashing consent.
8. Launch one bounded tool subprocess without shell interpretation, exact explicit port/chip/version, no `--force`, no efuse writes. Hold lease across USB disappearance. Re-enumeration must match reserved topology/serial + MCU MAC; if ambiguous, stop and request inspection. Never switch to newly allocated `/dev/ttyACM0` blindly.
9. Verify bytes and tool exit; do NOT assume application success. Avoid an automatic after-reset into potentially transmitting firmware. Keep target in bootloader/contained state until boot is separately authorized or the exact no-RF recipe is verified. Initial host TX policy cannot police autonomous radio firmware [S13].
10. Approved boot/reconnect: match identity again; read compatible local version/status under lease, no broadcast tests. Failure = RECOVERY_REQUIRED, not “finished.” Remove firmware tool handles before any reacquire.
11. If same compatible family/role and user approved restoration, ask original owner to reacquire; restore prior running/not-running intent only. Never enable a disabled unit or start one that was inactive. A switch to MeshCore repeater/room-server must not make a Meshtastic serial client repeatedly open the new device. Keep it detached in maintenance pending an approved matching Mesh adapter or explicit rollback. Report notifications unavailable on that target, not healthy.

### Failure/crash rules

No automatic resume, retry with erase, flash rollback, boot or service reacquire into unknown firmware. Durable journal stores last verified phase, pre-service state and identity/hash, not secrets or reusable consent. A UI crash cannot release a busy writer's lease. On lost worker/broker, preserve maintenance quarantine, terminate safely where possible and require human review before clearing stale state. If safe locking cannot survive a service reconnect/reboot, production flashing remains blocked; do not create autostart services as a shortcut.

Closing a window during writing offers “keep monitoring” or explicit interruption warning; cancel before erase/write is safe, mid-write cancel may require recovery. Process completion and handle closure must be observed before recovery or reacquire. No concurrent second window or Radio r3 task may gain the same device.

## Preserve the working Mesh audio exactly

Protected installed items [U69]:

- `/usr/lib/task-mesh/task_mesh/hub/notifier.py`
- `/usr/lib/task-mesh/task_mesh/hub/notifier.py.pre-audio-backup`
- `~/.local/share/task-mesh/sounds/mesh-alert.wav` (reported 1,176,590 bytes)
- asynchronous `/usr/bin/paplay` playback and `hints["suppress-sound"] = True`
- quiet hours, sound enablement, muted conversations, focus suppression and deduplication.

`task-firmware` must ship none of those paths, no dependency-driven Mesh upgrade/downgrade and no sound-generation/install hook. Preserve hashes/backups in later approved preflight. Canonical Mesh audio integration belongs to the separate Mesh/Radio review after the actual installed notifier and license provenance are supplied; an old canonical tree never wins over this tested installation. Firmware Manager can reuse reviewed notification APIs but must not trigger duplicate sounds or expose sensitive device data in notifications.
