# 3. Firmware family × board × role matrix

**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST** applies to every row and every cell.

Legend: **D** = documentary target/asset evidence only; **C** = conditional revision mapping, not approved; **—** = not an equivalent family role; **?** = unknown/not present in the inspected release list (blocked, not proof of permanent impossibility).

## Meshtastic [S01–S06]

Meshtastic device roles are configuration selections. The three MeshCore role names must not be presented as Meshtastic firmware variants. No automatic router/repeater behavior is enabled by this project.

| Board | Meshtastic target | Meshtastic application | MeshCore-style companion BLE/USB role | MeshCore-style repeater image | Room-server image |
|---|---|---|---|---|---|
| Heltec V3 | `heltec-v3` | D | — | — | — |
| Heltec V3.2 | `heltec-v3`, pending release/revision review [S02] | C | — | — | — |
| Classic T-Beam v1.1/M8N SX1276 | `tbeam` | D | — | — | — |
| Classic T-Beam M8N SX1262 | `tbeam` | D | — | — | — |
| Legacy T-Beam v0.7 | `tbeam0.7` | D, separate legacy gate | — | — | — |
| Supreme / S3-Core SX1262 | `tbeam-s3-core` | D, exact assembly gate | — | — | — |
| T-Deck / Plus | `t-deck` | D | — | — | — |

D indicates the documented target; no Meshtastic release version or binary has yet been selected or hash-verified.

## MeshCore pinned documentary snapshot: v1.18.0 [S14–S18]

| Board | Release basename prefix | Companion BLE | Companion USB | Repeater | Room server |
|---|---|---|---|---|---|
| Heltec V3 | `Heltec_v3` | D | D | D | D |
| Heltec V3.2 | prospective `Heltec_v3` | C | C | C | C |
| Classic T-Beam SX1276, exact PCB/PMU unreviewed | `Tbeam_SX1276` | D | ? | D | D |
| Classic T-Beam SX1262, exact PCB/PMU unreviewed | `Tbeam_SX1262` | D | ? | D | D |
| T-Beam v0.7 | unknown | ? | ? | ? | ? |
| T-Beam S3 Supreme SX1262 | `T_Beam_S3_Supreme_SX1262` | D | ? | D | D |
| Bare T-Beam S3-Core | Supreme mapping not established | ? | ? | ? | ? |
| T-Deck original/Plus, exact revision gate | `LilyGo_TDeck` | D | D | D | ? |

Examples observed, preserving case (all suffixes use `v1.18.0-81dbae5`):

- `Heltec_v3_companion_radio_ble-v1.18.0-81dbae5-merged.bin` [S14]
- `Heltec_v3_companion_radio_usb-v1.18.0-81dbae5.bin` [S14]
- `Heltec_v3_repeater-v1.18.0-81dbae5-merged.bin` [S15]
- `Heltec_v3_room_server-v1.18.0-81dbae5.bin` [S16]
- `Tbeam_SX1276_companion_radio_ble-v1.18.0-81dbae5-merged.bin` [S14]
- `Tbeam_SX1262_repeater-v1.18.0-81dbae5.bin` [S15]
- `T_Beam_S3_Supreme_SX1262_room_server-v1.18.0-81dbae5-merged.bin` [S16]
- `LilyGo_TDeck_companion_radio_usb-v1.18.0-81dbae5-merged.bin` [S14]
- `LilyGo_TDeck_repeater-v1.18.0-81dbae5.bin` [S15]

No `LilyGo_TDeck_room_server` asset or classic/Supreme T-Beam USB companion asset was listed in these inspected releases. Availability is snapshot-specific. Until reviewed source + reproducible build + license + physical tests establish another option, show it unavailable, not a selectable placeholder.

### T-Deck licensing/UI distinction

Open-source `LilyGo_TDeck` companion/repeater images above are not a promise of the separately distributed standalone MeshCore Ultra UI. MeshCore FAQ explicitly excludes T-Deck standalone firmware from its open-source statement [S13]. Its distribution terms must be established independently; no inclusion in a free/open-source default catalog based only on “free to download.” No proprietary blob is included in this docs package.

### Registry acceptance rule

Only exact board revision + RF chip/band + family + role + image layout + tool recipe + known provenance may become an eligible combination. A D cell is not automatically eligible. Unknowns stay disabled with reasons; firmware families do not exchange settings. The native UI must distinguish documentary, simulated and physically accepted states rather than calling all rows “supported.”
