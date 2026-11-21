# Source-review request and decisions needed

No Pi access performed. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST** for all proposed device workflows. This Firmware Manager request reuses the Radio r3 installed-source review bundle; it does not redefine Radio APIs, edit the Radio worktree or authorize any live action.

## r2 selected first device / remaining approval boundary

Joshua nominated his working Heltec V3 915 MHz for the first physical rehearsal, conditional on current-configuration backup and verified procedures [U72]. He explicitly still withholds permission for Pi modifications/flashing until individual steps are authorized. See [document 12](12-heltec-v3-first-test.md) for approval-gated passive metadata, exclusive service release, private YAML/key coverage, ROM reads and same-version reflash planning. The reported 2.7.11 pin identifies the Python client; actual radio firmware/build and exact image/SHA256 remain unknown. Do not request a new device nomination or infer blanket execution permission.

## Exact existing interfaces to review

Request these installed files (or the installed-version .deb **plus locally modified installed files and a hash/diff record**). Local working installation wins over an older development tree. Obtain static sources/metadata, not runtime secrets, DBs, auth tokens, exported keys or full home/config directories. Review/redact any private literals before sending. No module imports or device opens are needed for this source collection.

### Core / compatibility

Under `/usr/lib/python3/dist-packages/task_core/`:

- `api.py`, `protocol_v2.py`, `bus.py`, `capabilities.py`, `devices.py`, `enumerator.py`, `modules.py`, `sessions.py`, `auth.py`, `socketpath.py`.
- Relevant imports/static helpers discovered from those sources, only as necessary.
- `/usr/lib/task-core/modules/radio.yaml`, `mesh.yaml`, `gps.yaml`.
- `task-core-compat` installed file list and the compatibility dispatcher/adapters identified by that list; exact filenames unknown until listed, so do not invent them.

### Shared communications

Under `/usr/lib/python3/dist-packages/task_comms/`:

- `ownership.py`, `txpolicy.py`, `bridge.py`, `aprs.py`, `notifications.py`, `core.py`, `events.py`, `status.py` and referenced static interfaces.
- `/usr/share/doc/python3-task-comms/COMMS-STATUS.md`, `NOTIFICATIONS.md`.

Needed answers: canonical physical identities/aliases; current owner queries and conflict reporting; lease lifetime/fencing; maintenance release/ack; reconnect inhibition; failure/crash ownership; notification filters/privacy; protocol version/auth and compatibility constraints. Do not assume advisory ownership is atomic exclusion.

### Mesh, launcher and device coordination (incremental to the Radio bundle)

- `/usr/lib/task-mesh/task_mesh/hub/notifier.py` **as currently installed**, its `.pre-audio-backup` and relevant imports/static notification settings contracts; protect any private values.
- `dpkg -L task-mesh task-launcher task-core-compat python3-task-comms` output to identify exact connection-manager/serial owner, service entrypoint, IPC/reconnect code, launcher module discovery/embedding/window contracts and installed Debian metadata. File names other than the known notifier are unknown, not guessed.
- Static `task-mesh-service.service` unit contents and launcher registration examples from the installed versions; these may reside in user or system locations. Ask for the actual path, do not assume one. No service restart/enable action.
- Mesh sound: hash and original package/source/license provenance for `~/.local/share/task-mesh/sounds/mesh-alert.wav` (reported size 1,176,590 bytes) and a record of the 26 dB/0.95-limiter modification. Firmware Manager needs no copy of the asset and must never overwrite it. Canonical sound integration remains separate work.
- Existing safe installer source under `release/common` (if available) and actual launcher plugin examples, to reuse guardrails only after review; no blind assumption about a new package extension API.

### APRS overlap (shared Radio review, not a flashing dependency)

Reuse the bundle's installed task-aprs files: `task_aprs/agw.py`, `amateur.py`, `kiss.py`, `dwconf.py`, `config.py`, `service.py`, `gmrs/driver.py`, `gmrs/service.py`; `/usr/share/doc/task-aprs/GMRS-HARDWARE-RESEARCH.md`. Review only for ownership boundary/no-interference information here. Actual Direwolf ports/API work belongs to Radio r3; Firmware Manager must not open, change or duplicate APRS transports.

## Safe passive inventory to request later

**EXPLICIT APPROVAL REQUIRED for this Pi batch; NOT RUN.** For the selected first Heltec, prefer document 12’s narrower exact by-id metadata block.

The following is a proposed read-only metadata batch for Joshua to review/run; it has NOT been executed on the Pi. It does not open serial ports or stop/restart services. It may print local service/path identifiers; review output before sharing. Service-unit contents/environment files are not collected by this batch because they can contain private values.

```bash
dpkg-query -W task-core task-core-compat python3-task-comms task-mesh task-launcher esptool python3-meshtastic python3-pyside6.qtwidgets
ls -l /dev/serial/by-id/ /dev/serial/by-path/
udevadm info --query=property --name=/dev/ttyUSB0
udevadm info --query=property --name=/dev/ttyACM0
systemctl --user show task-mesh-service.service -p ActiveState -p SubState -p UnitFileState -p FragmentPath
systemctl show gpsd.service task-core.service -p ActiveState -p SubState -p UnitFileState
id dragon
```

If device numbering has changed, ask for the by-id list first; `udevadm info` only queries metadata, but future serial commands must never use hard-coded tty numbers. No esptool `chip_id`, `read_mac`, `flash_id`, serial terminal, Meshtastic export or boot button procedure belongs in a passive batch: these open/reset hardware or require exclusive ownership [S19,S20]. A later controlled identity probe needs explicit approval and the release/RF-safe workflow first.

## Top questions for Joshua (before Milestone B)

1. First device is now selected: Joshua’s working Heltec V3 915 MHz, under the backup/safety conditions [U72]. Confirm actual V3 versus V3.2 PCB marking, RF-band evidence, approved interpreter exposing pinned client 2.7.11 and (only after separately approved exclusive release) the radio firmware/build via private local info. Additional roadmap boards still need exact variants; a spare is no longer a prerequisite for this chosen first device.
2. Reuse the source archive supplied for Radio r3.1 reconciliation; this worker has not inspected it or verified its SHA256. Does that shared review establish the extra Mesh ownership/service and launcher embedding contracts above, including atomic maintenance/reconnect inhibition? Request only genuinely missing sources after reconciliation, not a duplicate full bundle. Any integration extension needs separate approval.
3. Approve the proposed name/tile ID `task.firmware`, integrated view + separate-window behavior and `task-firmware` 0.1.0 package scope? This is separate from Radio's pending tile approval.
4. Which Meshtastic versions and MeshCore roles/versions should form the first small offline catalog? First rehearsal is now the selected working Heltec with the **same actual firmware version/build and role**, after verified private backup; exact radio version/file/hash are still unknown. Later MeshCore/role tests require separate review and authorization.
5. Does “MeshCore on T-Deck” mean the open-source companion/repeater images, or the standalone Ultra UI shown elsewhere? The latter is not covered by the MIT claim [S13]. Keep the default strictly FOSS; do you want that proprietary option excluded entirely?
6. What is the approved **RF-safe first-boot policy**? No RF transmission is authorized. Stock repeater firmware can advertise/repeat autonomously [S13]. Without a verified no-RF boot path or engineered containment and explicit approval, physical flashing/boot tests stay blocked.
7. Temporary outage/reflash was accepted conditionally, not authorized for execution. Review the exact bounded maintenance procedure, approve each stop/start or cooperative release/reacquire step separately, and settle failure recovery before starting. On family/role switch, leave detached if original Mesh transport is incompatible rather than claiming automatic reconnection.
8. What backup/privacy/retention policy should apply to settings, keys and raw flash dumps? Default no automatic key extraction; protected local backups only, explicit limited-coverage warning. Source packs and firmware are separate from private backups.
9. Confirm user-local vault proposal and storage budget; can source/compliance packs be split across under-25-MB archives for offline media? Firmware fetches remain opt-in per named release.
10. What maintainer identity/email should future Debian packages use? Still TBD, not fabricated. Optional: share the November 3 screenshot/app name if exact Android-tool parity is important; identity/capability is presently unknown.

## Permissions still required separately

Research approval does not permit coding, Pi installs/upgrades/downgrades, service restarts/stops/enablement, device reset/probing/configuration, settings backup/restore, firmware erase/write, application boot with autonomous RF, online firmware download or transmission. Every later stage must remain explicit and narrowly scoped. Nothing in this package changes the existing system.
