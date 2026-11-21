# 12. First physical test plan — Joshua's Heltec V3 915 MHz

Milestone A r2 • 2026-11-08 (EST) • **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**

## Authority and scope

Joshua's pt72u selects his working Heltec V3 915 MHz as the FIRST physical flashing test device and accepts a temporary outage/reflash **conditional on backing up the current configuration and verifying safe procedures first**. His same message explicitly withholds permission for Pi modifications and actual flashing until he authorizes those individual steps. This plan is documentation only: **nothing below has been executed on the Pi**. A device nomination is not approval to stop/start a service, open/reset a port, create a backup, erase/write firmware, restore settings, change trust/configuration or transmit.

Reported setup: task-mesh 0.3.1 owns the CP2102 by-id device below, currently resolving to ttyUSB0; task-mesh-service is running and disabled for automatic startup. Python Meshtastic is reported pinned to **2.7.11**. That is a **client/library version, not proof of the radio firmware version**. The exact installed Python path and radio firmware/build remain to be established. No downgrade to Debian's 2.6.0 client is proposed. [U69,U72,S26,S30]

Read [ownership](05-ownership.md) and [recovery](10-recovery.md) first. The working notifier, pre-audio backup, sound, quiet-hours/mute/focus/dedup/privacy behavior, GPS/gpsd and unrelated radios remain protected.

## Approval gates — every Pi step needs explicit approval

| Gate | Proposed Pi action | Approval/status |
|---|---|---|
| A | Passive OS/USB/service metadata and physical marking inspection | **EXPLICIT APPROVAL REQUIRED; NOT RUN** |
| B | Reserve selected device; temporarily release/stop only the user Mesh service | **EXPLICIT APPROVAL REQUIRED; NOT RUN** |
| C | Local serial `--info`, YAML/channel backup and private-file creation/validation | **EXPLICIT APPROVAL REQUIRED; NOT RUN** |
| D | Manual BOOT/RST entry and esptool ROM identification reads | **EXPLICIT APPROVAL REQUIRED; NOT RUN** |
| E | Exact image/source/hash/recipe review; any named online acquisition | **EXPLICIT APPROVAL REQUIRED; image not selected/downloaded** |
| F | Same-version erase/write or app-only reflash, as specifically reviewed | **EXPLICIT APPROVAL REQUIRED; NOT AUTHORIZED/NOT RUN** |
| G | Controlled application boot and settings restore | **EXPLICIT APPROVAL REQUIRED; NOT RUN; RF gate applies** |
| H | Return port to task-mesh-service, receive/notifier checks | **EXPLICIT APPROVAL REQUIRED; NOT RUN** |
| Later | Firmware-family/role change, new release, RF messaging or failure injection | **Separate future request; outside first rehearsal** |

No one approval bundles all gates. Before any serial open, reset, power cycle or boot, have a verified RF-safe procedure and a correctly connected antenna or suitably rated 915 MHz dummy load. **Never power/operate the SX1262 with an open RF connector.** Antenna attachment protects the radio but does not contain RF. A dummy load is not a guarantee of zero radiated leakage. First boot and the existing running application may transmit autonomously; service stop does not silence radio firmware. If no verified no-transmit path or explicitly approved engineered containment exists, stop before the active gates. No RF transmission is approved by this plan. [S01,S06,S13,S20]

## A. Passive identification — EXPLICIT APPROVAL REQUIRED; NOT RUN

Exact read-only metadata batch for a later approved session as `dragon` (no sudo). This batch never opens a serial port and never changes a service. It prints paths/device descriptors; inspect output before sharing. It only hashes the existing notifier/sound, not secret configuration files.

```bash
PORT='/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0'
readlink -e -- "$PORT"
ls -l -- "$PORT" /dev/serial/by-id/
udevadm info --query=property --name="$PORT"
systemctl --user show task-mesh-service.service -p ActiveState -p SubState -p UnitFileState -p MainPID -p FragmentPath
systemctl show gpsd.service task-core.service -p ActiveState -p SubState -p UnitFileState
id dragon
dpkg-query -W task-mesh python3-task-comms task-core task-core-compat esptool python3-yaml
/usr/bin/python3 -c 'import importlib.metadata as m; print("system-Python Meshtastic:", m.version("meshtastic"))'
sha256sum -- /usr/lib/task-mesh/task_mesh/hub/notifier.py /usr/lib/task-mesh/task_mesh/hub/notifier.py.pre-audio-backup "$HOME/.local/share/task-mesh/sounds/mesh-alert.wav"
```

Review `ID_VENDOR_ID`, `ID_MODEL_ID`, `ID_SERIAL`, `ID_SERIAL_SHORT`, `ID_PATH`, `DEVPATH` and driver. Record actual VID/PID rather than pre-filling a fabricated observation. CP2102 is shared by many boards; its VID/PID and generic serial `0001` cannot prove V3, V3.2, radio band or even unique hardware identity. Bind selected physical USB topology plus MCU MAC later. The u-blox GPS at ttyACM0 is never opened or reset. If PORT is missing/changed, stop; never substitute the GPS or a guessed tty number. [S11,S19,S20]

**Physical inspection (also Gate A approval):** read the actual PCB silkscreen/revision on both sides and supplier/board markings for the 915 MHz hardware; confirm WiFi LoRa32 V3 versus V3.2, not V4, Wireless Stick or another Heltec. A product title/OLED application label is insufficient. A photo can be supplied without keys/positions. Do not power-cycle, disassemble a powered device or unplug the working radio merely to read a hidden marking without separate approval. Unknown/obscured revision => stop for identification. V3.2 ADC changes are documented [S02], but USB descriptors/ESP32-S3 identification do not distinguish that revision.

The metadata command uses **system** `/usr/bin/python3`, never shell-default Python. If Meshtastic is missing or not 2.7.11, that does NOT invalidate task-mesh's reported pin: its private environment may differ. Stop active commands and request the reviewed task-mesh entrypoint/interpreter/import path from the shared Radio source bundle. Do not install, activate an arbitrary venv, change PYTHONPATH, replace the pin or infer a CLI path. Subsequent `/usr/bin/python3 -m meshtastic` examples are conditional on confirming that exact interpreter resolves the approved 2.7.11 client.

## B. Service release — EXPLICIT APPROVAL REQUIRED; NOT RUN

First review installed task-comms ownership and Mesh reconnect behavior. Reserve all aliases for this one physical device and prevent another UI/service from reconnecting. If cooperative release is supported, prefer it. If the approved procedure is service stop, the exact user-level change is `systemctl --user stop task-mesh-service.service` — **NOT a read-only command and NOT authorized now**. Record active/running and disabled-at-startup before it. Do not use sudo, system-wide stop, disable, mask, enable, daemon-reload or kill; do not touch task-core or gpsd.

After separately approved release/stop, query `systemctl --user show task-mesh-service.service -p ActiveState -p SubState -p MainPID` and inspect the reviewed ownership broker plus a non-killing open-handle query (`fuser -- "$PORT"`, if already available). These queries also require approval for that session. No reported PID is not proof of global exclusivity when process visibility is limited. Any competing/unknown owner or unreviewed reconnect behavior blocks serial work. No automatic service restart trap or retry.

## C. Firmware identification and private backup — EXPLICIT APPROVAL REQUIRED; NOT RUN

Prerequisites: Gate B complete, exclusive release proven, RF-safe Gate satisfied, approved 2.7.11 interpreter/path verified. `--info` is a **local device read request**, not passive OS inventory: it writes serial protocol requests, may reset the board on port open and may expose private keys, channels and location in its output. Never paste its full output into chat or include it in a release. Do not add `--dest`, remote admin, send/reply, BLE scan or auto-port options. [S30,S31]

**Offline caveat:** the inspected 2.7.11 CLI `--info` calls an opportunistic PyPI update check; `--no-time` is a deprecated no-op, not a network-off switch. Run this planned command only in an already-offline environment or after a separately approved, reviewed process-only isolation procedure. Do not change the Pi's global network/Qt/audio/Bluetooth settings and do not patch the installed CLI. The read can still obtain local radio information without internet, but an attempted version check may time out. This caveat must be resolved for the later native fully-offline adapter. [S30,S32]

Planned local device-info read (not a standalone permission to execute):

```bash
# EXPLICIT APPROVAL REQUIRED: released exclusive port + RF-safe procedure + approved interpreter + offline condition first.
PORT='/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0'
/usr/bin/timeout --signal=INT 90s /usr/bin/python3 -m meshtastic --port "$PORT" --timeout 30 --info
```

Because stdout can contain secrets, conduct this only in a private terminal or redirect it into a newly created private backup directory under a separately approved backup-file step below. Share only the manually reviewed firmware-version/build and board-model lines if needed. Record the full **device firmware version + build suffix** and current role, not the client's `--version`. If absent/incomplete, stop and review a separately approved local metadata read; do not guess from the host package.

### Private backup-file step (host writes; NOT a read-only batch)

**EXPLICIT APPROVAL REQUIRED; NOT RUN.** Create a new private directory, never an overwrite of a previous backup. Example below is contingent on the same approved interpreter and release conditions. No secret values are put in command arguments, shell history, chat, repository, firmware vault or deliverable ZIP. The “firmware vault” is distinct from these confidential backups.

```bash
# EXPLICIT APPROVAL REQUIRED: creates private files on Pi and reads selected radio over serial.
umask 077
PORT='/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0'
BACKUP_ROOT="$HOME/.local/state/task-firmware/backups"
mkdir -p -- "$BACKUP_ROOT"
BACKUP_DIR=$(mktemp -d "$BACKUP_ROOT/heltec-v3.XXXXXXXX")
chmod 700 -- "$BACKUP_DIR"
/usr/bin/timeout --signal=INT 90s /usr/bin/python3 -m meshtastic --port "$PORT" --timeout 30 --export-config --export-format yaml > "$BACKUP_DIR/config.yaml" 2> "$BACKUP_DIR/export.stderr"
```

Check command exit status immediately; a timeout/error/empty export is failure, not a backup. Do not run the next phase because a file exists. Preserve failure files privately for review, never automatically delete or retry. Under the same explicitly approved backup session, capture `--info` into `"$BACKUP_DIR/info.txt"` (stderr separate) and optionally `--qr-all` into `"$BACKUP_DIR/channels.txt"` (stderr separate) for comparison; these are additional local serial reads, not RF send tests. The export calls `getURL()` with all active channels by default in inspected 2.7.11 [S30,S31]. A primary-only URL is not enough for secondary channels.

### Backup coverage / key caveats

- YAML should include owner/settings, `config`, `module_config`, and `channel_url` or `channelUrl` carrying active channel settings/PSKs and LoRa config. Treat every channel URL/QR as a secret; base64 is not encryption. Cross-check all active primary/secondary channels, indexes/roles/names and PSKs privately against baseline, because URL reconstruction may not preserve disabled-slot/history details. [S30,S31]
- PKI public/private/admin keys are separate from channel PSKs; a channel URL does not back up PKI. Upstream documents loss/regeneration on erase and recommends `--export-config` [S33]. Check the actual export's `config.security` fields privately for a nonempty, correctly decoded private/public key pair where the running firmware supplies one. Inspected 2.7.11 handles base64 key encodings, but field availability/firmware restrictions and restore behavior require verification. No presence/length check proves keypair correctness or restore success. If private key is absent/masked/unverifiable, **STOP: do not erase this working node**; no permission to bypass the backup condition, export keys separately or generate a replacement identity has been granted.
- The export is **not a full flash/data backup**: not a restorable radio node DB, chat/message history, host task-mesh DB, filesystem dump, Bluetooth pairing database, all calibration/security state or firmware image. An `--info` node listing is not a node-DB restore archive. Settings export cannot promise preservation of missing state. Never touch task-mesh's DBs to compensate. [S30,S31]
- Record field coverage/omissions and get Joshua's specific acceptance before any destructive proposal. If preserving omitted messages/node DB is necessary, stop for a separate supported backup plan. No raw-flash readback or key extraction is added implicitly.
- Keep originals mode 0600, directory 0700; optionally create a separately approved encrypted/offline second copy controlled by Joshua. Do not ask him to send private key material or channel URLs. Hashes and redacted coverage are enough for review. Never include backup artifacts in this repository/archive.

### Validate backup parses (local file read only; EXPLICIT APPROVAL REQUIRED; NOT RUN)

With the private `BACKUP_DIR` variable still set, this proposed check imports PyYAML only, not Meshtastic, and opens no device. It prints no YAML/key values and suppresses parser exception content. `python3-yaml` must already be available; no install is authorized.

```bash
/usr/bin/python3 - "$BACKUP_DIR/config.yaml" <<'PYBACKUP'
import pathlib, sys
try:
    import yaml
    path = pathlib.Path(sys.argv[1])
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError()
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('config'), dict):
        raise ValueError()
    if not isinstance(data.get('module_config'), dict):
        raise ValueError()
    url = data.get('channel_url', data.get('channelUrl'))
    if not isinstance(url, str) or not url.startswith('https://meshtastic.org/') or '/#' not in url:
        raise ValueError()
except Exception:
    raise SystemExit('FAIL: backup parse/shape check; review privately, do not erase')
print('PASS: YAML parse/shape only; channel/PKI coverage and restore remain UNVERIFIED')
PYBACKUP
```

Syntax/shape validation is NOT a restore test or complete backup verification. Separately inspect fields/encoding/active-channel coverage and key presence privately, without printing secrets. Record private file hashes with `sha256sum -- "$BACKUP_DIR/config.yaml"` after successful verification; never present a digest as proof that omitted data was backed up.

## D. ROM identity reads (“non-flashing probe,” NOT a no-effect dry-run)

**EXPLICIT APPROVAL REQUIRED; NOT RUN.** Only after the configuration backup gate has passed and ROM/boot/RF handling is approved. Before leaving the running application, recheck reservation, selected topology and identity. Heltec manual route: hold **PRG/USER/BOOT**, press **RST**, release PRG; confirm the exact board buttons first. This resets the MCU and interrupts reception even if flash is not written. [S11,S20]

Qualified esptool 4.7 candidate below explicitly fixes chip/port, disables RAM-stub upload and suppresses tool-requested before/after reset. The chip must already be in the ROM bootloader. Commands send serial requests and can affect transient chip/interface state; **they contain no flash write/erase, eFuse write or persistent device-setting operation**. They are not esptool's simulated flash “dry-run,” and OS/bridge DTR/RTS behavior is still hardware-unverified. ROM flash-ID access with `--no-stub` must be qualified for exact wiring; no SPI-pin overrides/retry escalation. [S19,S34]

```bash
# EXPLICIT APPROVAL REQUIRED: backup verified, service released, exclusive reservation, manual ROM entry and RF-safe conditions first.
PORT='/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0'
/usr/bin/python3 -m esptool --chip esp32s3 --port "$PORT" --baud 115200 --before no_reset --after no_reset --no-stub chip_id
/usr/bin/python3 -m esptool --chip esp32s3 --port "$PORT" --baud 115200 --before no_reset --after no_reset --no-stub flash_id
/usr/bin/python3 -m esptool --chip esp32s3 --port "$PORT" --baud 115200 --before no_reset --after no_reset --no-stub read_mac
```

Approve/run each read separately and stop on any error; do not paste as an unattended loop. First verify installed esptool version/flags locally (also approval required); if absent/incompatible, stop, no pip/apt install. Expected class is ESP32-S3, not an invented observed result. `chip_id` on this family can report MAC rather than a unique chip ID [S06]. Record actual flash capacity/ID, silicon and MAC privately, then bind to selected USB topology. Neither MAC nor chip ID establishes V3 versus V3.2 or SX1262/band. Do not reboot to application merely to regain reception until the boot/service return is approved.

## E. Exact firmware selection and hashes — EXPLICIT APPROVAL REQUIRED; BLOCKED

First physical rehearsal should reflash **the exact currently running Meshtastic firmware version/build for verified `heltec-v3`**, retain its current role, and make no family/role/configuration changes. “Same version” is NOT a no-op: it still writes flash, may erase settings and can fail. MeshCore/role change comes only after a successful recorded restore/reacquire rehearsal and separate permission.

| Selection field | Current value / requirement |
|---|---|
| Board/target | User-selected Heltec V3 915 MHz; inspect revision; `heltec-v3` target conditional on confirmation [S01,S02] |
| Python client | Reported pinned `meshtastic` 2.7.11; verify exact interpreter, do not equate to radio firmware [S30] |
| Radio firmware version + build | **UNKNOWN** until approved local `--info` identifies it |
| Exact file/bundle name and release tag | **UNKNOWN / NOT SELECTED** until firmware version/build established; choose matching ESP32-S3 release bundle and exact `firmware-heltec-v3-...` image variant |
| Source | Official [Meshtastic firmware releases](https://github.com/meshtastic/firmware/releases); exact tagged release URL and source commit must then be recorded |
| Image SHA256 / bundle SHA256 | **UNKNOWN — no firmware binary acquired or hashed**; never substitute the docs ZIP hash |
| Recipe/companions | Audit that exact release's install/update scripts, partition metadata, bootloader/OTA/littlefs files and offsets [S06–S08] |
| Erase policy | Prefer a reviewed same-version application update for first write if compatible; full erase+factory is separately confirmed recovery/clean-install rehearsal, not automatic fallback |

After named acquisition permission, record source release URL, exact asset URL/filename, immutable source commit, upstream checksum/signature if provided and independently computed SHA256 of every actual local file. If publisher supplies no independent digest/signature, label authenticity evidence accordingly. Match all companions/version/build; perform offline `image_info`/plan checks without opening the port. Local checksum command for that later reviewed file is `sha256sum -- /exact/reviewed/image/path` (placeholder, not runnable selection). No image-specific hash or destructive command can honestly be supplied now. If the original build cannot be obtained/reproduced, stop and ask; do not silently pick a nearby version.

## F/G. Future approved write, recovery and settings restore — NOT AUTHORIZED

**EXPLICIT APPROVAL REQUIRED for each operation; NOT RUN.** No erase/write/restore copy-paste batch is issued while the exact version, files/hashes and recipe are unknown. Keep backups and known-good full recovery bundle available offline before the first write. No firmware flashing, bootloader updates, forced security overrides or RF action is performed by this research.

Recovery path for a later approved session:

1. Preserve exclusive maintenance and RF containment; correctly connected antenna/load. Re-enter ROM using BOOT/PRG + RST and reconfirm topology/MAC/chip.
2. Present exact losses and get separate full-erase/factory approval. Use the **matching release's complete verified factory-install recipe**, not just an app `.bin` at a guessed address. Full flash erase can destroy PKI, channels, bonds and files. Some releases require OTA/littlefs companions/metadata; current master differs from older examples [S06–S08]. Do not blindly run a full erase because a read or update failed.
3. Verify writes/bytes with the qualified tool/recipe, remain in ROM or approved containment; never use tool default reboot as an accidental permission to transmit.
4. Separately approve controlled first application boot and local serial access under containment. Confirm exact firmware/build and same board identity before restoration.
5. Review YAML import compatibility/diff; preserve original export unchanged. For the same verified client/version, `meshtastic --configure <private-config.yaml>` is upstream's restore mechanism [S30,S33], but requires exact approved interpreter/port and a separate device-write approval. It may restore TX-enabled/region/role settings, reboot, and print sensitive values. Use a private terminal/log; do not import while the Mesh service owns the port. No guarantee of complete recovery or data restoration.
6. Re-export after approved restore into a new private file; compare semantic settings, all active channel PSKs and PKI public/private coverage privately (expected serialization/default differences require review, not blind byte comparison). Public identity continuity and actual operational state must be checked. Missing/mismatching critical keys/settings => fail, no false restored claim.

## H. Return ownership and notifier verification — EXPLICIT APPROVAL REQUIRED; NOT RUN

Close every CLI/esptool handle and release the maintenance lease only when compatible original Meshtastic firmware/settings and boot safety are established. If original service was running, the proposed user-level change is `systemctl --user start task-mesh-service.service` — **requires explicit approval, not issued/executed now**. Query its status and reviewed owner/selected device to confirm it alone reacquires the Heltec. Preserve disabled automatic startup; no enable, restart of Core/gpsd or global configuration change. If reacquire fails, report receiver/notification outage and stop; never kill unrelated services or repeatedly open the port.

Compare the notifier/pre-audio-backup/sound hashes with Gate A; these files must be unchanged. Verify asynchronous paplay behavior, `suppress-sound=True`, quiet-hours/sound-enable/muted/focus/dedup/privacy controls via the reviewed existing safe local notification test **only after permission**. Exact test command remains source-review-dependent, not invented. An actual incoming message check can wait for naturally occurring allowed reception; do not send a packet from this Heltec, ask a second station to transmit or enable automatic beaconing as an implicit test. If no incoming message is observed, label end-to-end audible notification **not tested**, not passed. A local playback test alone is not incoming-message acceptance.

## Pass / fail / hold criteria (all currently NOT RUN)

- **Preflight pass:** explicit gate approvals; actual revision/band/topology/VID/PID established; exact client path and firmware/build identified; original owner/service states recorded; unrelated devices excluded; RF-safe procedure verified. Unknowns = HOLD.
- **Backup pass:** successful export, nonempty safe YAML parse + structure, complete active-channel/PSK and available PKI review, private permissions and hashes, omissions understood and accepted. Parse-only is insufficient. Missing PKI or required state => HOLD before erase.
- **Probe pass:** three approved non-flashing reads succeed on the selected ESP32-S3/MAC/capacity with no owner race, collateral device open or unapproved application boot. This is not a flashing test pass.
- **Reflash pass:** exact same-version/build target and hashes/recipe recorded, explicit write consent, correct byte verification plus controlled boot and exact firmware identification. No version/role upgrade hidden in rehearsal.
- **Restore/return pass:** critical settings/channel/PKI verified privately, task-mesh-service exclusively reacquires and prior enablement preserved, notifier assets unchanged; local and incoming-message tests separately marked actual pass/fail/not tested. GPS/core/unrelated hardware unchanged.
- **Fail immediately:** mismatched/ambiguous identity, missing backup coverage or recipe, untrusted/mismatched hash, permission/lease conflict, unexpected erase/reset/TX, failed verification/reconnection, key loss, changed protected files or unplanned service/device operation. Stop under maintenance/RF-safe recovery; no automatic erase, retry, reboot, service start or success claim.

This plan narrows the first-device selection but does not authorize implementation, installation or any Pi operation. Radio source-archive receipt/hash reconciliation is a separate worker/task; this document makes no claim to have verified that archive.
