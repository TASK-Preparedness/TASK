# 8. Phases, approval gates and acceptance plan

**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. No implementation, simulator, arm64, GUI, installer or hardware acceptance test has been run. Checking Markdown/ZIP integrity is not a software/hardware pass.

## Milestone A — research and design (this deliverable)

Feasibility, dated source evidence, board/role matrix, native/offline architecture, device ownership, licensing and recovery proposals. Reviewer decisions and installed source review remain open. Keep entirely separate from Radio r3. No access to `/workspace/task-phase5a-wt` and no Pi operations.

## Milestone B — implementation/simulation, only after authorization

Prerequisites: source interfaces inspected; maintenance semantics agreed; registry/image format choices approved; initial device and role selected (Joshua has conditionally nominated the working Heltec V3; precise revision/firmware remains unverified); first-boot RF containment policy designed. Implement offline importer, catalog/schema validation, plan/authorization state machine, PySide6 integrated/standalone view, mocked ownership adapters and simulated esptool I/O. No real device access and no RF in this milestone.

Simulation acceptance plan (NOT executed):

- Board/chip/revision/RF-band mismatch, V3 vs V4, T-Beam classic vs S3, SX1262 vs SX1276, T-Deck vs Pro; ambiguous VID/PID/MAC-only identity all blocked.
- Valid/corrupt/truncated/modified bytes, absent companions, invalid offsets/overlap/out-of-flash, factory vs app confusion, mixed releases, unsupported schema/license/source provenance fail closed.
- USB archive traversal, symlink/bomb, injected command/filename/metadata, forged executable recipe, huge logs; no shell execution and no target changes.
- Maintenance refused, owner still holds handle, unknown PID, release timeout, reconnect race, unplug/replug alias changes, two matching boards, second UI writer and Radio concurrent access fail closed.
- GPS identity/aliases and unrelated devices never reach any serial adapter; deny `/dev/ttyACM0` substitution after renumbering using identity not numbering.
- Backup unsupported/failed/partial, secret redaction, config import RF-enabled fields, source/target version mismatch: honest coverage and renewed consent.
- Erase/write subprocess startup failure, partial write, verification mismatch, disk full, stalled output, UI/worker crash, broker loss, power-loss journal; no automatic erase escalation or auto-resume.
- RF-first-boot unknown, autonomous repeating/adverts possible, service incompatible after family switch: remain quarantined, no false success/reacquire.
- No hidden network calls with network disabled; no auto-fetch/downloads, telemetry, autostart, service changes, global pip, force/eFuse paths or root GUI.
- Integrated/separate window share transaction, truthful indeterminate progress, interruption warnings and private notifications. Quiet hours/mute/focus/dedup continue through reviewed notification API.

## Milestone C — installable release candidate, separately approved

Build task-firmware 0.1.0 deb and offline dependencies in clean arm64 Debian 13; qualify esptool 4.7 DFSG and actual CLI flags without device access first. Lint, dependency simulation, package filelist, maintainer-script audit, install/remove and schema rollback in disposable test environment. No tests on Joshua's Pi until explicit install approval. Publish source/compliance packs and checksums, under 25 MB per archive. No fabricated maintainer email.

## Milestone D — physical acceptance, individually authorized

r2 update [U72]: Joshua conditionally selected his **working Heltec V3 915 MHz** as the FIRST physical-test device and accepts a temporary outage/reflash only after verified configuration backup and safe procedures. This supersedes the r1 spare-device recommendation; it is not permission to perform any Pi operation yet. Follow [the gated first-test plan](12-heltec-v3-first-test.md): establish exact radio firmware/build, back up and verify private configuration/channel/PKI coverage, non-flashing ROM reads, then propose a separately approved same-version/build reflash with the existing role unchanged. A later family/role change needs fresh approval. Hardware possession or device nomination is not execution consent. Explicit separate permissions for service interruption, reset/probe/boot mode, backup reads, erase/write, restoring settings, starting application firmware and any RF behavior. Safe power and approved RF-contained or verified no-transmit environment required. Firmware may transmit without host requests [S13]; never assume a dummy load alone provides sufficient isolation or disconnect the antenna.

Record each exact PCB/revision, RF chip/band, USB IDs/serial/topology, MCU MAC/chip/flash size, image/source/tool/recipe hashes, initial firmware, original owner/service state, consent scope, actual results and limits. Do not claim all boards passed based on one Heltec.

### Hardware test grid (all NOT RUN)

| Board class | Planned checks | Result |
|---|---|---|
| Joshua’s working Heltec V3 915 MHz (conditionally selected) | First: identity + private verified backup + ROM reads; separately approved same-version/build Meshtastic reflash and verified restore/reacquire/notifier. No role/family change in first rehearsal. Later roles require new approval. | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST |
| Heltec V3.2 | Same plus verified revision mapping and battery/charge indication before/after | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST |
| Classic T-Beam SX1276 | Exact PCB/PMU/radio, proper ESP32 image, backup and recovery; no assumed S3 boot/offset behavior | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST |
| Classic T-Beam SX1262 | Separate target/radio proof; same controlled lifecycle | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST |
| Supreme S3 SX1262, if owned/in-scope | Separate board assembly/boot path and firmware roles; bare S3 Core not inferred | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST |
| T-Deck original/Plus | Trackball boot sequence, correct application/USB return, native host UI, companion/repeater only as approved; no proprietary Ultra assumption | UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST |

Failure injection on physical hardware requires its own explicit approval and expendable board; do not deliberately pull power mid-flash on the working installation. Validate host crash recovery using simulation first. Test unexpected disconnects only in a controlled approved session. Do not test RF messaging as a hidden flash-completion check.

### Exit criteria

Documentary target → simulated-only → physically accepted **exact tuple**, with no unsupported broad claims. Success requires separate recorded byte verification, controlled boot and exact version identification/reconnection, plus correct ownership and prior service-state restoration where appropriate. GPS and unrelated radios remain untouched; hardware-tested Mesh audio remains intact. Remaining failures and no-RF uncertainty stay visible.

## Current readiness

Milestone A r2 research package and first-device plan are complete for review; all Pi steps remain unexecuted. The selected device resolves only the nomination question, not the firmware version, private-backup, source/API, RF safety or execution approval gates. **Milestone B is not ready to begin now:** authorization, installed source/API review, precise board inventory, maintenance contract, image recipe/license selection and RF startup policy are blocked. Approval for research is not approval for coding, Pi installation, probing, service operations, firmware flashing or RF transmission.
