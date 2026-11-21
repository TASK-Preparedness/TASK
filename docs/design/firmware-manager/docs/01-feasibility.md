# 1. Board-by-board feasibility

**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. Documentary feasibility is not T.A.S.K. support certification. Sources: [S01–S06, S11–S18] in SOURCES.md.

| Physical board / RF option | Upstream facts and target boundary | Assessment / release gate |
|---|---|---|
| Heltec WiFi LoRa32 V3 / 902–928 MHz option | ESP32-S3FN8, SX1262, CP2102 bridge. Meshtastic `heltec-v3`; MeshCore `Heltec_v3` release family. [S01,S11,S14–S18] | First candidate. r2: Joshua conditionally nominated his working Heltec V3 915 MHz [U72]; verified backup/safety and explicit approval of each live maintenance action remain required. See document 12. |
| Heltec V3.2 | V3 family revision; upstream Meshtastic fix changes ADC polarity handling for V3.2 under existing V3 logic. [S02] Not a V4. | Conditional candidate for `heltec-v3`, not assumed identical in power/battery behavior. No separately verified MeshCore V3.2 target in inspected evidence; mapping to `Heltec_v3` requires schematic/revision and hardware validation. Exact SKU/chip must be confirmed. |
| Classic T-Beam v1.1 / M8N, 915 MHz, SX1276 | ESP32 (not S3); Meshtastic `tbeam`; MeshCore `Tbeam_SX1276`. [S03,S14–S16] | Feasible conditional on board revision and radio identification. GNSS/PMU variation must be registry data. |
| Classic T-Beam M8N, 915 MHz, SX1262 | ESP32; Meshtastic documents `tbeam`; MeshCore uses a separate `Tbeam_SX1262` family. [S03,S14–S16] | Feasible; never substitute the SX1276 MeshCore image. “915” alone does not identify the radio or pin map. |
| T-Beam v0.7 | ESP32/SX1276; Meshtastic `tbeam0.7` explicitly incompatible with `tbeam`. [S03,S06] | Separate legacy registry entry; initial MeshCore eligibility unknown. Exclude from first release until exact upstream pin/PMU support is established. |
| T-Beam S3 Core / Supreme, 915 MHz, SX1262 | ESP32-S3; Meshtastic `tbeam-s3-core`; MeshCore release has `T_Beam_S3_Supreme_SX1262`. [S04,S14–S16] | Separate conditional candidate. Do not assume Supreme image works on a bare S3-Core; validate exact assembly. Not classic `tbeam`. |
| T-Deck original / Plus, 915 MHz | ESP32-S3FN16R8, SX1262, target `t-deck`. Plus adds GPS/battery; distinguish Pro/e-ink. [S05] MeshCore `LilyGo_TDeck` companion/repeater artifacts exist. [S14,S15] | Feasible for listed open-source release roles. Standalone MeshCore Ultra screen/keyboard firmware is a separate licensing/product question [S13]. No promised room-server artifact. |

If a board is sold as “T-Beam 1.2”, record its printed revision, PMU, RF chip, MCU and supplier documentation; the reviewed Meshtastic page does not establish that label's mapping. Unknown variants, 1W boards, T-Deck Pro, V4 and boards without the LoRa module remain blocked until independently registered. ESP chip probing cannot identify SX1262 vs SX1276, an RF band, PCB routing, PMU or board revision reliably.

## Switching firmware families

Meshtastic ↔ MeshCore switching is a fresh-install migration on a verified board, **not** an in-place protocol toggle. Plan for loss of settings, keys, Bluetooth bonds, identities, messages, node tables and filesystem state. Configurations are not mutually importable. Retain family-specific recovery images, settings exports and source/license records before granting a destructive confirmation. Never reuse one family's partition/filesystem offsets merely because the MCU is the same. [S06–S09,S13,S19]

Neither family interoperability nor equivalent roles are implied. Meshtastic client/router choices are configuration roles, not MeshCore companion/repeater/room-server images. Installing repeater firmware may introduce autonomous RF behavior [S13]; a no-TX host UI alone cannot contain that.

## Critical feasibility limit

Offline flashing is technically practical with local artifacts plus esptool [S06,S13,S19,S25]. **Safe first boot without unauthorized RF is not established.** Before any physical test, approve either an independently verified no-RF boot path or a properly engineered RF-contained bench procedure. Do not detach antennas as a purported no-transmit measure: upstream warns of damage [S05,S06]. Until that gate is satisfied, remain in bootloader/quarantine and do not offer automatic reboot into application firmware.
