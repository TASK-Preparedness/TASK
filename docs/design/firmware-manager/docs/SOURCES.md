# Source register and evidence boundaries

Reviewed 2026-11-08 (EST). Sources were opened this research session. Web indexes/fetches may be cached; this is a dated documentary snapshot, not a claim to know every release that exists. No firmware asset bytes were downloaded or validated. GitHub release asset names establish availability at the stated tag only. Do not interpret absence at a tag as proof that source builds or later versions cannot support a role.

All proposed hardware behavior: **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

## Meshtastic and board documentation

- **S01** [Heltec LoRa32 hardware](https://meshtastic.org/docs/hardware/devices/heltec-automation/lora32/): V3/V3.1 ESP32-S3FN8, SX1262, `heltec-v3`; V4 distinct. Current page does not explicitly list V3.2.
- **S02** [Meshtastic PR 5196](https://github.com/meshtastic/firmware/pull/5196): merged change for V3.2 ADC enable polarity auto-detection; merge `336cdc0efef552b0020606bcbf602f8822736874`. [Issue 5127](https://github.com/meshtastic/firmware/issues/5127) closed referring to this fix. PR 5130's proposed separate `heltec-v3_2` is not evidence of a current released target.
- **S03** [Classic T-Beam hardware](https://meshtastic.org/docs/hardware/devices/community-supported/lilygo/tbeam/): ESP32 variants, SX1276 vs SX1262, `tbeam`, exception `tbeam0.7`. Page is internally inconsistent on v0.7 GPS; no reliance on that GPS detail here.
- **S04** [S3-Core/Supreme/1W hardware](https://meshtastic.org/docs/hardware/devices/lilygo/tbeam/): S3-Core and Supreme ESP32-S3/SX1262 use `tbeam-s3-core`; manual BOOT-on-plug instructions. 1W is a different target.
- **S05** [T-Deck hardware and flashing](https://meshtastic.org/docs/hardware/devices/lilygo/tdeck/): original/Plus ESP32-S3/SX1262, `t-deck`; Pro distinct; hold trackball while powering on. Do not flash keyboard co-processor.
- **S06** [Meshtastic CLI flashing](https://meshtastic.org/docs/getting-started/flashing-firmware/esp32/cli-script/): install/update paths, chip identification, explicit warning about wrong-board images and GPIO damage. Examples may lag current filenames.
- **S07** [Meshtastic install script, inspected master revision](https://github.com/meshtastic/firmware/blob/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/bin/device-install.sh); [raw](https://raw.githubusercontent.com/meshtastic/firmware/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/bin/device-install.sh). Inspected current master script requires `.factory.bin`, `.mt.json`, OTA and littlefs companions, erases before install. This is not a selected release recipe.
- **S08** [Meshtastic update script, same revision](https://github.com/meshtastic/firmware/blob/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/bin/device-update.sh): non-factory image at `0x10000`, explicit-port warning. Do not infer every historic release uses this exact recipe.
- **S09** [Meshtastic Python CLI](https://meshtastic.org/docs/software/python/cli/usage/): configuration export; [CLI source](https://raw.githubusercontent.com/meshtastic/python/master/meshtastic/__main__.py): `--export-config`, `--configure`/`--import-config`, current optional output format behavior. Current master is not the Debian 2.6.0 implementation; confirm installed flags and export coverage before use.
- **S10** [Meshtastic firmware GPLv3 text](https://raw.githubusercontent.com/meshtastic/firmware/master/LICENSE): source/object redistribution obligations, corresponding source. [Firmware repository](https://github.com/meshtastic/firmware).
- **S11** [Heltec ESP32 general quick start](https://docs.heltec.org/zh_CN/node/esp32/esp32_general_docs/quick_start.html): hold PRG/USER/BOOT, press RST, release PRG. [Board index](https://docs.heltec.org/en/node/esp32/wifi_lora_32/index.html): V3 CP2102, ESP32-S3, distinguishes V4. [FAQ](https://docs.heltec.org/en/node/esp32/wifi_lora_32/frequently_asked_questions.html): cables, board selection and partition differences.

## MeshCore

- **S12** [MeshCore README](https://raw.githubusercontent.com/meshcore-dev/MeshCore/main/README.md): roles, USB/BLE/Wi-Fi companion variants, offline-capable prebuilt images and MIT statement; [docs index](https://docs.meshcore.io/).
- **S13** [MeshCore FAQ](https://raw.githubusercontent.com/meshcore-dev/MeshCore/main/docs/faq.md), sections 1.2, 4.2, 5.7, 5.13: role distinctions, T-Deck boot procedure, Pi serial flashing, merged vs app bins, nRF ZIP/adafruit-nrfutil. FAQ explicitly excepts T-Deck standalone firmware and native mobile apps from open source. Section 2.4 documents periodic repeater adverts. Upstream global-pip instructions are NOT adopted.
- **S14** [Companion v1.18.0 assets](https://github.com/meshcore-dev/MeshCore/releases/tag/companion-v1.18.0): exact names in compatibility table. Tag resolves to `81dbae592ffad40b4212bc0b37e82b38da08f4bc` in public commit metadata observed this session.
- **S15** [Repeater v1.18.0 assets](https://github.com/meshcore-dev/MeshCore/releases/tag/repeater-v1.18.0).
- **S16** [Room server v1.18.0 assets](https://github.com/meshcore-dev/MeshCore/releases/tag/room-server-v1.18.0).
- **S17** [MeshCore MIT license at companion-v1.18.0](https://raw.githubusercontent.com/meshcore-dev/MeshCore/companion-v1.18.0/license.txt): copyright Scott Powell / rippleradios.com, MIT permission and retention conditions. Does not grant rights in separately distributed proprietary firmware.
- **S18** [Heltec V3 build environments at v1.18.0](https://raw.githubusercontent.com/meshcore-dev/MeshCore/companion-v1.18.0/variants/heltec_v3/platformio.ini): ESP32-S3, SX1262, USB/BLE companion, repeater and room server. No explicit V3.2 environment shown.

## Flash tools and chip behavior

- **S19** [esptool release-v4 basic commands](https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/esptool/basic-commands.html): erase/write/read, MAC/flash ID, image metadata, merged padding erasure, secure boot/encryption safeguards. Chip family checks are not board pin-map validation.
- **S20** [ESP32-S3 boot mode](https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/advanced-topics/boot-mode-selection.html): GPIO0/46, DTR/RTS reset, BOOT/EN. Opening/probing can reset hardware; not passive inventory.
- **S21** [esptool image format](https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/advanced-topics/firmware-image-format.html): chip/revision metadata, simple SHA256 corruption hash separate from signatures.
- **S22** [esptool v4.7.0 GPLv2 license text](https://raw.githubusercontent.com/espressif/esptool/v4.7.0/LICENSE). Distribution must preserve source and license obligations, including Debian changes/stub treatment.
- **S23** [Adafruit nRF52 nrfutil README](https://raw.githubusercontent.com/adafruit/Adafruit_nRF52_nrfutil/master/README.md): distinct `adafruit-nrfutil`, derived from Nordic pc-nrfutil 0.5.3, Python serial DFU ZIPs; [BSD-3-clause-style license](https://raw.githubusercontent.com/adafruit/Adafruit_nRF52_nrfutil/master/license.txt). Master observed `7fdfe15feee5f304fb7d9b031721dcefa1f72b58`. Future nRF adapter only, not ESP32.
- **S24** [ESP-IDF copyrights](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/COPYRIGHT.html): original code Apache-2.0 plus component-specific terms; source headers prevail. [Arduino-ESP32 LGPL-2.1 text](https://raw.githubusercontent.com/espressif/arduino-esp32/master/LICENSE.md). Neither establishes every bundled binary/blob's redistribution rights.

## Debian 13 Trixie packages

- **S25** [esptool](https://packages.debian.org/trixie/esptool): `4.7.0+dfsg-0.1`, architecture all; depends on python3, bitstring, cryptography, ecdsa, intelhex, reedsolo, serial and yaml. Main adapter candidate; DFSG-repacked build/stub behavior still needs testing.
- **S26** [python3-meshtastic](https://packages.debian.org/trixie/python3-meshtastic): `2.6.0-1`, all; Python dependencies listed, including bleak, packaging, protobuf, pubsub, requests, serial, tabulate, yaml.
- **S27** [python3-pyside6.qtwidgets](https://packages.debian.org/trixie/python3-pyside6.qtwidgets): `6.8.2.1-4`, arm64 listed; qtcore/qtgui dependencies.
- **S28** [python3-bitstring arm64 lookup](https://packages.debian.org/trixie/arm64/python3-bitstring): `4.2.3-1`, all, depends on python3-bitarray. Architecture-all Python packages can be installed on arm64 but their compiled dependency closure must be resolved for arm64.
- **S29** [python3-adafruit-nrfutil lookup](https://packages.debian.org/trixie/python3-adafruit-nrfutil): page returned “No such package.” Exact-name lookup is not proof there is no differently named package; packaging status remains unknown. Not needed for initial ESP scope.

## r2 first-test references (opened 2026-11-08, EST)

- **S30** [Python CLI source tagged 2.7.11](https://raw.githubusercontent.com/meshtastic/python/2.7.11/meshtastic/__main__.py), [release](https://github.com/meshtastic/python/releases/tag/2.7.11): local `--info`, YAML `--export-config`/`--export-format`, `--configure`, QR-all; export settings coverage/base64 key handling; info calls update check; `--no-time` deprecated no-op. Tag/source behavior is evidence, not proof of installed Pi bytes.
- **S31** [Python 2.7.11 node source](https://raw.githubusercontent.com/meshtastic/python/2.7.11/meshtastic/node.py): `getURL(includeAll=True)` includes active primary/secondary channels, `showInfo`/showChannels can reveal private settings/URLs; URL not a full node DB/message export.
- **S32** [Python 2.7.11 util source](https://raw.githubusercontent.com/meshtastic/python/2.7.11/meshtastic/util.py): `check_if_newer_version` performs a PyPI HTTP request with timeout. Do not label `--info` network-silent or use global-pip update suggestions.
- **S33** [Meshtastic security configuration: backup/restore](https://meshtastic.org/docs/configuration/radio/security/): private keys confidential; erase/reinstall loses keys, export-config/configure documented for preservation. Actual export coverage/key continuity must be verified privately for installed firmware/client.
- **S34** [esptool v4 basic options](https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/esptool/basic-options.html), [advanced options](https://docs.espressif.com/projects/esptool/en/release-v4/esp32s3/esptool/advanced-options.html): explicit chip/port; no port means enumerate/probe; before/after no_reset and no-stub options; no-stub ROM/SPI wiring limits. These reads are active serial operations, not passive discovery or simulated flashing.

## Inventory evidence

- **U69** Joshua's t69u read-only inventory and Mesh hardware test report, supplied in conversation. Installed package versions, device owners, service state, notifier behavior and sound size are user-reported. Do not label Firmware Manager hardware-tested because Mesh audio was tested.
- **U72** Joshua’s pt72u: conditionally nominates his working Heltec V3 915 MHz for first physical flashing test, accepting outage/reflash only after configuration backup/safe procedures; no Pi modifications or actual flashing until explicit authorization. Delegated update reports task-mesh client pin 2.7.11; interpreter and radio firmware/build are not inspected.
- **U70** Joshua's t70u requirements. Screenshot/tool identity unknown; likely web flasher or third-party Android tool cannot be identified without the screenshot/app name. No assertion of offline parity with that specific app.

### Known evidence mismatches / not inferred

Meshtastic CLI guide's `.bin`/`-update.bin` examples differ from inspected master factory layout. Release-specific scripts/metadata must win after audit. Heltec V3.2 is conditionally mapped to the V3 family, not a fabricated dedicated target. T-Deck open-source companion/repeater release bins must not be confused with separately licensed standalone UI firmware. T-Deck room-server artifact absent in the inspected v1.18.0 list: unknown/unavailable for that snapshot, not a permanent impossibility.
