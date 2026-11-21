# 10. Rollback, bootloader guidance and failure recovery

Design only. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. No backup, restore, recovery or first boot is guaranteed. No reset, flash, erase, service change or RF operation is authorized by this guide.

## r2 first-device constraint

Joshua has conditionally selected the working Heltec V3 915 MHz [U72]; follow [document 12](12-heltec-v3-first-test.md). **Every Pi step still needs explicit approval.** No stop/start, backup, probe, erase/write, boot or restore has been run. Before any destructive action, verify its private YAML/channel/PKI backup and exact current firmware/build. Pinned Python Meshtastic 2.7.11 is not the radio firmware version. First rehearsal retains the exact radio version/build and role; this is a risky reflash, not a literal no-op. Full erase + matching complete factory bundle + private configuration restore is a separately approved recovery path, never automatic fallback. Missing PKI/required backup state blocks erase.

Heltec ROM reference: BOOT/PRG held → press RST → release BOOT/PRG [S11,S20]. A correctly connected antenna or rated dummy load protects the RF output, but does not guarantee RF containment; first boot may transmit and needs the separate RF-safe/authorization gate. After verified restore, close all maintenance handles before a separately approved user-service start/reacquire, keep automatic startup disabled, and verify protected notifier/sound hashes plus actual notification results (not tested unless observed).

## Three independent rollback layers

1. **Application/package:** revert only task-firmware to an archived version and compatible private-state snapshot after separate approval; don't downgrade other T.A.S.K. packages or remove dependencies automatically. Preserve vault/backup data; remove only the module's own approved tile registration. No apt autoremove.
2. **Host ownership/runtime state:** remember prior active/inactive and enabled/disabled states. Release only the selected maintenance device. After known-good compatible firmware and separately approved boot, ask its rightful Mesh adapter to reconnect; never enable autostart or restart Core/gpsd. Do not blindly connect the Meshtastic service to MeshCore repeater/room-server firmware.
3. **Device firmware/data:** selecting a retained known-good image is another flash transaction with new confirmation, board identity validation and RF containment. Settings restore is another distinct device write, version-specific and potentially RF-enabling. A successful image rollback does not imply restored keys, bonds, identity, history, external storage or radio calibration.

## Explicit erase/family-switch warning

> This operation can erase device settings, identities, private/channel keys, Bluetooth pairing, histories and filesystem data. Backups may be incomplete, unreadable or incompatible with the target version. Restoration and recovery are not guaranteed. Firmware can transmit or forward automatically on first boot. Confirm the exact board, image, loss scope, maintenance outage and approved RF-safe boot procedure before proceeding.

Display actual erase sectors and segment impact from reviewed plan, not just this generic warning [S07,S13,S19]. No automatic erase on failed connection. Refuse secure-boot/flash-encrypted or otherwise unqualified configurations rather than adding `--force` or writing eFuses [S19]. Do not force version downgrades through incompatible NVS/layout formats.

## Board-specific offline bootloader cards

These are reference instructions for a **later approved maintenance session**. Before any power cycle, hold the maintenance reservation, protect GPS/unrelated hardware, ensure stable power and an approved RF-contained or verified no-RF procedure. Do not remove antenna/load as a no-TX technique. A normal reboot or a failed BOOT sequence may start autonomous firmware. No card is a guarantee of recovery.

| Board | Documented route and boundaries | Source |
|---|---|---|
| Heltec V3 | Heltec general ESP32 guide: hold PRG/USER/BOOT, press RST once, then release PRG. Verify exact physical buttons and selected board; CP2102 bridge is not unique identity. | [S11], ESP32-S3 reset/control behavior [S20] |
| Heltec V3.2 | Provisional use of V3-family route only after confirming exact revision/button mapping. V3.2 ADC change is documented, not a separate verified recovery procedure. | [S02,S11]; conditional, not physically validated |
| Classic T-Beam v1.1/M8N ESP32 | Docs identify Program and Reset switches [S03]. Exact timing/entry sequence for Joshua's revision remains **unknown** until vendor manual/schematic is reviewed. Do not apply S3/native-USB or T-Deck sequence indiscriminately. esptool connection/reset must be qualified on the exact PCB. | [S03,S06] |
| T-Beam v0.7 | Separate legacy target and manual/recovery qualification; not generic `tbeam`. Exact local procedure unknown. | [S03,S06] |
| T-Beam Supreme/S3-Core | Documented Supreme method: unplug, hold BOOT, plug device, release BOOT after 2–3 seconds. Verify exact assembly and image target. Native USB identity may change. | [S04] |
| T-Deck original/Plus | Device power OFF; hold TRACKBALL; power ON; release after 2–3 seconds. Meshtastic describes dark screen/backlight as download-mode indication; MeshCore FAQ adds USB connected before holding/power-on. Confirm serial identity independently; dark screen alone is not proof. | [S05,S13] |
| Future nRF52 boards | Require exact per-board bootloader/DFU ZIP or UF2 procedures and adapter. No generic double-reset/DFU instructions applied to ESP targets. `adafruit-nrfutil` serial ZIP is a different protocol/tool, not Nordic nrfutil equivalence. | [S13,S23] |

Do not choose `dfu-util` or write a keyboard co-processor based on the word DFU in a guide. ESP32-S3 ROM download is an esptool path [S19,S20]. BOOT/RESET/manual intervention is a controlled operation that may interrupt existing firmware and ownership, not passive discovery.

## Failure runbook

- **Owner does not release:** abort; no open/reset/erase. Report current owner and necessary review. Never kill unknown processes or stop gpsd to free a port.
- **Identity ambiguous after re-enumeration:** do not chase tty numbers or broad auto-scan. Re-identify selected USB topology, descriptors and MCU MAC under lease, with user confirmation; unknown = stop.
- **Backup failure:** retain original if not yet erased; warn honestly. User can cancel or separately acknowledge data loss. Never report a backup exists because a zero-length file was created.
- **Connection failure before writing:** check cable/data connection, local permission, stable power and exact approved boot card. Any new reset or service action needs approval; don't raise baud/retry indefinitely or automatically fall back to erase.
- **Power/USB interruption or partial write:** keep journal and maintenance quarantine. Clearly mark device possibly nonbootable. No automatic reboot/reacquire or flash replay. On an approved recovery attempt, re-establish ROM boot mode and exact identity, verify local known-good full bundle, present erase implications, then obtain fresh confirmation.
- **Byte verification failure:** do not label success. Retain redacted output and file/plan hashes. Recovery can require clean install, but only after review and explicit approval.
- **Bytes verified but no application reconnection:** report these as separate states. Remain detached; check approved firmware/board/layout/power/boot procedure. Don't send a broadcast test or probe arbitrary ports. A wrong GPIO image may cause hardware damage [S06], so no trial-and-error image roulette.
- **Application returns with incompatible family/role:** no automatic settings import or original Mesh reconnect. A new matching Mesh transport integration or explicit firmware rollback is required.
- **Service reacquire fails:** keep hardware state and original enablement policy unchanged; report notification/receive outage, no false “restored.” No unrelated service restarts as a recovery shortcut.

A raw flash readback may help on an unsecured compatible chip [S19] but can expose secrets and cannot undo efuses, physical damage, inaccessible boot ROM, or arbitrary version migrations. Keep encrypted-device backups and restore claims outside initial scope. Recovery cards and known-good images must be available locally before maintenance starts; otherwise do not begin a field flash.
