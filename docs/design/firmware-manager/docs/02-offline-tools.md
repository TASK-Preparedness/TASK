# 2. Recommended offline tools and image handling

**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. No commands here were run against hardware. This is a design, not an instruction batch to execute on the Pi.

## r2 installed-client preservation

Joshua’s Mesh setup reports pinned Python Meshtastic **2.7.11** [U72]. The Debian 2.6.0 catalog entry below is availability evidence, not permission to replace/downgrade that working client. Verify the exact interpreter/import path from installed sources. Actual radio firmware remains unknown. The tag-specific 2.7.11 CLI/key/export and network-check caveats are documented in [the first-test plan](12-heltec-v3-first-test.md) [S30–S33].

## Recommended tool boundary

| Tool | Use | Local/offline and version qualification |
|---|---|---|
| Debian `esptool` | ESP32 and ESP32-S3 ROM serial adapter for all confirmed initial MCU families; explicit selected port only | Trixie `4.7.0+dfsg-0.1`, architecture all [S25]. Invoke with `/usr/bin/python3 -m esptool` after package/filelist verification. Qualify this DFSG package and its stub behavior; if necessary test documented ROM `--no-stub` mode only on an approved board. Do not assume upstream v5 flags or pip distribution equals Debian v4. |
| Meshtastic release scripts/metadata | Authoritative input to a reviewed, release-specific native flash recipe | Audit exact release scripts, partition metadata and companions offline [S06–S08]. Do not execute scripts supplied by arbitrary imports or scrape their stdout as the sole safety policy. |
| Debian `python3-meshtastic` | Optional local settings backup/restore through existing Mesh ownership | Trixie `2.6.0-1`, all [S26]. Validate installed CLI flags/API against installed firmware; no remote destination, auto-port or BLE scan fallback. Reuse existing installed client if compatible rather than replacing it. |
| `adafruit-nrfutil` | Future nRF52 serial DFU ZIP adapter only | Upstream is an Adafruit fork with distinct command/name [S23]; MeshCore FAQ describes its use [S13]. Not for Heltec V3/V3.2, classic ESP32 T-Beam, Supreme S3 or T-Deck. Exact Debian package availability unknown [S29]. No initial dependency, no global pip, no Nordic executable substitution. |
| Python standard library SHA256 | Verify bytes against trusted manifest and imported package hashes | Proposed implementation; hashing alone does not authenticate the publisher. Treat signature verification and trusted manifest provenance separately [S21]. |

No browser, internet, PlatformIO build, Arduino IDE, WebSerial, dfu-util or cloud service is required in the field flashing path. Browser flashers are research references, not the native implementation. “DFU” in a T-Deck guide means its documented firmware-download workflow, not permission to select a generic USB DFU tool [S05,S13,S20].

## Meshtastic: factory versus update

The official CLI guide has older-style examples: install `firmware-BOARD-VERSION.bin`, update `firmware-BOARD-VERSION-update.bin` [S06]. Inspected current master script instead requires `firmware-*.factory.bin`, a matching `.mt.json`, `mt-MCU-ota.bin` and `littlefs-...bin`; it erases flash first, writes factory at zero and other components at offsets described/used by that script [S07]. Current update script rejects factory files and writes an app image at `0x10000` [S08].

**Consequences:** no filename-only dispatch, no universal “all .bin files go at zero,” no mixing bundles/versions, no importing update files as bootable factory images. A selected release must supply an audited segment recipe, chip/revision, flash-size and layout constraints. Where metadata and script disagree (including filesystem offset handling), block the recipe pending review. Master is not a release; these observations do not authorize any offset for production.

LittleFS is not optional trivia: filesystem images may carry assets or state, and overwrite/erase can destroy data. A factory/erase operation can remove NVS, identities/bonds/settings and filesystem contents. App-only updates may leave state intact, but partition/schema incompatibility or a downgrade can invalidate it. Show exact regions and possible losses; never promise retention [S07–S09,S19]. Web client installation, if later supported, must be a separately selected, locally audited asset; it is not needed by Firmware Manager.

## MeshCore: released binaries and roles

Official v1.18.0 releases provide board/role-specific app `.bin` and ESP `-merged.bin` files [S14–S16]. MeshCore's Pi instructions distinguish non-merged application at `0x10000` from merged at zero for its ESP32-S3 example, explaining differences in bootloader/bond treatment [S13]. Use exact board+role release recipes; validate ESP32 (classic) versus S3 packaging separately. Never transfer the S3 example blindly to every MCU or a differently generated merged file.

The FAQ suggests merged images can retain configuration while replacing pairing/boot content. That is **not a T.A.S.K. preservation guarantee**. Cross-family switching, layout mismatch or a deliberate erase is destructive. Keep segment maps, hashes and wipe ranges in the manifest. Companion BLE, companion USB, repeater and room-server images are different artifacts, not roles guaranteed by a single image. Do not use a build environment as proof that a released binary exists.

## Configuration backup, not guaranteed recovery

Meshtastic documents `--export-config`; the CLI also implements restoration through `--configure` (current source additionally aliases `--import-config`) [S09]. Later approved local-port operation would capture export stdout into a protected file and restore only after reviewing target version/schema and a displayed diff. Verify flags with the installed Debian CLI before generating that operation. Do not blindly use new optional filename arguments from master against 2.6.0.

Prefer export through the existing owning Mesh service if its reviewed API supports it. Otherwise acquire an exclusive maintenance lease first; no parallel CLI opens. Export may omit keys, histories, filesystem or other state depending on version; catalog coverage explicitly. Keep exports separate from public vault, mode 0600 under a private directory, and redact logs. Treat configuration import as a distinct confirmed device write which may enable RF.

MeshCore FAQ describes app export/import and some server setting/key commands [S13], but full native backup coverage across roles/versions is unknown. Do not automatically issue sensitive key-reading commands. A future adapter needs an explicitly reviewed scope and protected handling. Optional esptool full-flash readback [S19] is chip/security dependent, may contain secrets, and is not a portable or guaranteed restorable backup. No eFuse writing, forced secure-boot/encryption overrides or bootloader replacement outside a separately approved exact recipe.
