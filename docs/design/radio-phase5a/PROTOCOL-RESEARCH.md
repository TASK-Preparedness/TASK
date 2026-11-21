> HISTORICAL / SUPERSEDED for integration and safety decisions by SOURCE-RECONCILIATION-r3.1.md, ARCHITECTURE.md and ADAPTER-API-SPEC.md. Retained for history only; no commands or capabilities here authorize action.

<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Phase 5A Milestone A: BTECH UV-PRO Bluetooth protocol research

Researched on 2026-10-30. No hardware was available, no Pi was touched, and nothing was transmitted.
Evidence classes: **[OFFICIAL]** = BTECH/FCC publications; **[RE]** = third-party reverse-engineering (open-source code);
**[FORUM]** = unverified user report; **[INFERENCE]** = our reasoning, not a source.
Every hardware item is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

Sources pinned:
- benlink (Kyle Husmann): https://github.com/khusmann/benlink at commit `c4b9d22112402ea193d376f412bc028d1778fdb4` (2026-06-13), **Apache-2.0**.
- HTCommander (Ylian Saint-Hilaire): https://github.com/Ylianst/HTCommander at commit `bd1964d3ece041161879c68eedf80b6a050d6551` (2026-10-29), **Apache-2.0**.
- BTECH UV-PRO firmware changelog: https://baofengtech.com/uv-pro-firmware-changelog/ (fetched 2026-10-30)
- BTECH KISS announcement (fw 0.7.11): https://baofengtech.com/btech-uv-pro-firmware-update-0-7-11-kiss-mode-now-built-in/
- BTECH app manual (2025-09-09): https://baofengtech.com/wp-content/uploads/2025/11/BTECH-APP-Updated-Manual-2025-9-9.pdf
- W7HEN groups.io post (UV-PRO + APRSdroid): https://groups.io/g/W7HEN/topic/110383701
- 47 CFR 95.1787: https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-95/subpart-E/subject-group-ECFR4bd5ed6fde6a8f0/section-95.1787

Licence note: Apache-2.0 is compatible with GPL-3.0-or-later (one direction: Apache code may go into a GPLv3 work, keeping its NOTICE/attribution). It is **not** compatible with GPLv2-only. T.A.S.K. is GPL-3.0-or-later, so we can take both projects as references or vendor them with attribution. **Decision for Milestone B:** write our own clean implementation, cite these projects, and do not vendor code unless the user approves. benlink is not packaged in Debian trixie (`apt-cache search benlink` returned nothing in the arm64 apt simulation), so using it as a dependency would need pip, which the rules forbid.

## 1. Two separate interfaces on the radio

| # | Finding | Class | Evidence |
|---|---|---|---|
| 1.1 | The UV-PRO supports **both** BLE and Bluetooth Classic (RFCOMM) for its vendor control protocol. | RE | benlink README.md lines 13–16 ("over BLE and Bluetooth Classic (RFCOMM)"); `src/benlink/link.py` BleCommandLink (l.40–67) and RfcommCommandLink (l.70–124) |
| 1.2 | The UV-PRO is listed as supported ("should work"). GMRS-PRO is listed as **untested**. | RE | benlink README.md, "Software / Hardware Support" |
| 1.3 | **Firmware ≥ 0.7.11 has a built-in KISS TNC "over Bluetooth"**, switched on from the radio menu: Menu → General Settings → KISS TNC. While KISS is on, the BTECH programmer app cannot connect ("data port is dedicated purely to the KISS protocol"). | OFFICIAL | KISS announcement page; changelog V0.7.11 ("KISS Bluetooth Mode … New KISS UI menu") |
| 1.4 | APRSdroid connects to the UV-PRO's KISS TNC with Connection Type **"Bluetooth SPP"** (fw 0.7.11-32). | FORUM | W7HEN groups.io |
| 1.5 | The radio appears as **two Bluetooth devices**: an audio device and a control device. The control device must also be paired (Windows procedure documented). | RE/FORUM | HTCommander docs/Paring.md |
| 1.6 | On Linux, HTCommander finds the **control** RFCOMM channel through SDP lookup of the standard **Serial Port Profile 0x1101**. Audio uses a vendor "BS AOC" 128-bit service `39144315-32fa-40db-85ed-fbfeba2d86e6`, falling back to 0x1203. | RE | HTCommander src/linux/runner/bluetooth_classic_plugin.cc l.28–34, l.168–187, l.511 |
| 1.7 | **Conclusion on "SPP KISS TNC":** The radio has an SPP (RFCOMM) port. In normal mode that port carries the **proprietary GAIA-framed Benshi command protocol** (finding 3). It is **not** KISS. With the KISS TNC menu option on (fw ≥ 0.7.11), BTECH says the data port carries KISS, and a forum user confirms APRSdroid works over SPP. We have not seen whether KISS mode is also offered over BLE, which RFCOMM channel it uses, or whether both modes can run at once. | OFFICIAL + FORUM + INFERENCE | 1.3, 1.4, 1.6 |

## 2. BLE GATT (vendor control protocol)

| UUID | Role | Class | Evidence |
|---|---|---|---|
| `00001100-d102-11e1-9b23-00025b00a5a5` | Radio control service | RE | benlink link.py l.31; HTCommander lib/services/bluetooth_service.dart l.1065 |
| `00001101-d102-11e1-9b23-00025b00a5a5` | Write (host→radio), write-with-response | RE | benlink link.py l.34, l.54 |
| `00001102-d102-11e1-9b23-00025b00a5a5` | Indicate (radio→host) | RE | benlink link.py l.37, l.60–63 |
| `00001103-d102-11e1-9b23-00025b00a5a5` | Alternative write characteristic (HTCommander only; meaning not documented) | RE | HTCommander bluetooth_service.dart l.1069 |

HTCommander also probes Nordic UART (`6e400001-…`) and SPP UUIDs as generic fallbacks (bluetooth_service.dart l.1050–1059). These are **not** evidence that the UV-PRO uses them.
On BLE, benlink writes the raw Message bytes with **no GAIA wrapper** (link.py l.51–54).
HTCommander radio_transport.dart l.54–75 says iOS cannot see the control service UUID before connecting, so it matches the device name instead ("UV-PRO" keyword).

## 3. Classic RFCOMM framing (GAIA)

From benlink `src/benlink/protocol/command/gaia_frame.py` (whole file) and link.py l.90–117 [RE]:
```
start=0xFF  version=0x01  flags(8 bit; bit0=CHECKSUM)  n_bytes_payload(8)
data = n_bytes_payload + 4 bytes (4 = command_group(16) + command(16 incl. reply bit))
checksum (8 bit) present only if flags.CHECKSUM
```
benlink always sends flags=NONE (no checksum). **UNKNOWN:** the checksum algorithm, which is not implemented in what we read, and whether the radio ever sets it. The benlink comments say the GAIA structure matches CSR/Qualcomm GAIA (cited only to a slideplayer.com deck, which is not authoritative).
HTCommander has its own `lib/radio/gaia_protocol.dart` (not reviewed line by line; review it in Milestone B).

## 4. Message layer

benlink `protocol/command/message.py` [RE]:
- `Message` = command_group (16 bit) + is_reply (1 bit) + command (15 bit) + body (l.229–233)
- `CommandGroup.BASIC = 2`, `EXTENDED = 10` (l.35–37)
- Selected BasicCommand values: `HT_SEND_DATA = 31`, `SET_POSITION = 32`, `SET_APRS_PATH = 71`, `GET_APRS_PATH = 72`, `GET_POSITION = 76` (l.89–134), and `REGISTER_NOTIFICATION` (used in command.py l.258)
- Notifications: `EventType.DATA_RXD = 2` ("Received APRS or BSS Message"), `HT_CH_CHANGED = 5` (protocol/command/notification.py l.18–24)
- **Session init / auth:** benlink's connect path just opens the link (command.py l.72–73). It then "hydrates": GET_DEV_INFO, each channel, settings, beacon settings, status, then registers HT_STATUS_CHANGED (controller.py l.309–331). The comment at l.329 says registering HT_STATUS_CHANGED "also enables the DATA_RXD event, and maybe others… need to investigate further". **No application-layer authentication was seen.** Bluetooth pairing/bonding is the only access control that was observed. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**

## 5. APRS packet representation (vendor protocol, non-KISS mode)

- Packets travel as **TNC data fragments**: `TncDataFragment` = is_final_fragment (1 bit), with_channel_id (1 bit), fragment_id (6 bit), data, then an optional channel_id (8 bit) (benlink protocol/command/common.py l.16–25) [RE].
- RX: `DATA_RXD` notifications carry fragments. HTCommander builds a frame from fragment_id 0 up to the final fragment, then treats it as **AX.25, hardware AFSK1200** (HTCommander lib/radio/radio.dart l.3521–3561) [RE]. So the radio forwards **raw AX.25 frames (no KISS framing)** inside vendor fragments. This is reverse-engineered, not confirmed by BTECH.
- TX: `HT_SEND_DATA` sends one fragment. benlink refuses data over 50 bytes ("TODO: implement fragmentation", controller.py l.297–305). HTCommander fragments by MTU (radio.dart l.24, l.2210–2260). **r2 decision:** TX in Milestone B goes through the KISS-SPP path only (standard KISS data frame). The vendor `HT_SEND_DATA` path stays unimplemented (fragment MTU on the UV-PRO is UNKNOWN; benlink has no fragmentation). The adapter declares `APRS_TX` absent, so the TX API refuses it.
- The same DATA_RXD channel also carries **BSS**, BTECH's proprietary short-message format (benlink notification.py comment; HTCommander docs/BSS-Protocol.md). The BTECH manual (§4.2) says BSS is "RF-only … not decodable by APRS receivers" [OFFICIAL].
- From fw V0.8.1 the onboard APRS destination is `APBTUV` [OFFICIAL changelog].

## 6. GPS / location

- `GET_POSITION` reply → `Position`: lat/lon are 24-bit signed values scaled by DegreesMapper, then altitude 16, speed 16, heading 16, time 32, accuracy 16. benlink's own comments mark the units as uncertain ("meters?", "Km/h?", "Degrees?"). Firmware < 49 sends only lat/lon (6 bytes); firmware < 133 sends 16 bytes with no accuracy field (benlink protocol/command/position.py l.54–73) [RE]. These "firmware" numbers are internal build numbers, not the 0.x.y marketing versions. **The mapping between the two is UNKNOWN.**
- HTCommander docs/GPS.md: the radio's GPS state can be read "starting with radio firmware 0.8.5" [RE].
- V0.8.8 "On-radio GPS sharing" and V0.8.15 "GPWPL Upload" (reports received positions as NMEA $GPWPL) [OFFICIAL changelog]. **Which transport GPWPL uses (KISS port? vendor channel?) is UNKNOWN.**

## 7. Reconnection

Neither project documents a resume protocol. benlink's RFCOMM reader marks the link disconnected on EOF (link.py l.248–252). **Our design:** reconnect = full re-handshake (re-hydrate and re-register notifications) with backoff. This is our design, not taken from a source. **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**

## 8. Firmware differences [OFFICIAL changelog unless marked]

| Version | Relevant change |
|---|---|
| 0.7.11 (2024-12-11) | KISS Bluetooth mode + KISS menu; BT buffering/error-correction improvements |
| 0.8.0 (2025-01-22) | KISS stability; APRS ACK fixes; "ACKs now sent via the receiving channel" |
| 0.8.1 | APRS destination APBTUV |
| 0.8.5 | GPS state readable (HTCommander docs/GPS.md) [RE] |
| 0.8.8 | Smart Beaconing, Mic-E frames, on-radio GPS sharing |
| 0.8.12 | BSS/APRS signalling selector; custom fixed location |
| 0.8.15 | KISS TX when squelch open; GPWPL upload |
| 0.9.0 | Mic-E overflow parse fix |
| 0.9.2 (2026-01-29) | KISS profile: separate TX/RX freq and TX power; DTMF in KISS mode |
| latest (V0.9.3 per BTECH reply, 2026-08-07) | "KISS transmission interruption" fix |

Settings that benlink exposes: `kiss_en`, `kiss_upload_tx_msg`, `kiss_tx_delay` (command.py l.1000–1010). In principle these could switch KISS on remotely. **We will never change radio settings in Milestone B/C** (policy).

## 9. VERIFIED vs UNKNOWN

**Verified from sources (not on our hardware):**
- BLE and Classic both carry the vendor protocol [RE]
- BLE UUIDs (section 2) [RE, two independent projects agree]
- GAIA framing on RFCOMM [RE]
- AX.25 in TNC fragments via DATA_RXD [RE]
- A KISS TNC over Bluetooth exists on fw ≥ 0.7.11 [OFFICIAL] and is used as SPP by APRSdroid [FORUM]

**UNKNOWN (UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST):**
- the RFCOMM channel numbers on our unit
- whether KISS mode is reachable over BLE
- whether KISS and the vendor protocol can coexist
- the GAIA checksum algorithm
- the full set of notification enable semantics
- the fragment MTU on the UV-PRO
- the GPS field units
- the build-number ↔ version mapping
- BlueZ pairing behaviour of the dual audio/control identity on Pi 5 (trixie, bluez 5.82)
- GMRS-PRO protocol parity
- behaviour on link loss mid-fragment

## 9a. Standards used for TX (r2) — not UV-PRO specific

- **[STANDARD] KISS** (KA9Q/K3MC "The KISS TNC", 1987): FEND=0xC0, FESC=0xDB, TFEND=0xDC, TFESC=0xDD. In a data frame, 0xC0 becomes DB DC and 0xDB becomes DB DD, in both directions. The command byte is (port<<4)|cmd, with data frame = 0. task-radio sends **only data frames (cmd 0)**. It never sends the parameter commands 1–6 (TXDELAY, P, SlotTime, TXtail, FullDuplex, SetHardware), and it never sends 0xFF (exit KISS). These would change TNC settings, and the policy says no settings writes.
- **[STANDARD] AX.25 v2.2 UI frame:** address fields of 7 bytes (callsign shifted left 1, SSID byte 0b0RR SSID 0 with the H-bit 0x80 on repeaters, the end bit on the last address), control 0x03, PID 0xF0. FCS is added by the TNC, not sent over KISS.
- **[STANDARD] APRS 1.0.1 messages (APRS101.pdf ch.14):** `:ADDRESSEE:text{ID`. The addressee is exactly 9 characters, space-padded. The text is up to 67 characters and must not contain `|`, `~` or `{`. The message ID is up to 5 alphanumeric characters. Ack = `:SENDER___:ackID`; reject = `:SENDER___:rejID`. The 1.1 "reply-ack" `{MM}AA` form exists in the aprs.org addenda; Milestone B **parses** it but does not send it (decision; open question).
- **[STANDARD/INFERENCE] Retry:** APRS101 describes repeating a message until it is acked, but does not fix a schedule. The schedule in ARCHITECTURE §TX is **our design**, chosen to be conservative for a shared 1200-baud channel.
- **UV-PRO-specific TX behaviour is still UNKNOWN:** whether KISS TX needs squelch closed or open (changelog 0.8.15 mentions "KISS TX when squelch open"), which TX power and frequency the KISS profile uses (0.9.2 adds separate TX/RX frequency and TX power), and whether the radio echoes TX frames back (`kiss_upload_tx_msg` setting, benlink command.py l.1000–1010). All of these are **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST** (Milestone D).
- The **existing** `task_comms.aprs.kiss_frame`/`encode_ax25` are listed in INTEGRATION-REQUESTS as present in the source here. Whether they are the installed versions, and whether they handle escaping and digipeater paths exactly as above, is **pending the source-interface review**.

## 10. Recommended adapter strategy

1. **Primary path, UV-PRO "KISS-SPP" mode:** the user turns on KISS TNC on the radio. T.A.S.K. opens RFCOMM to the SPP channel and speaks standard KISS/AX.25, reusing `task_comms.aprs.KissDecoder`/`decode_ax25`. This is officially documented and standards-based. **Support tier: partial** until hardware acceptance.
2. **Secondary path, "Benshi vendor protocol" (BLE or RFCOMM GAIA), receive-only (r2: still RX-only; TX API present, capability absent):** DATA_RXD → AX.25, plus GET_POSITION. It is useful when KISS is off. **Tier: experimental**, read-only commands only, no settings writes, no HT_SEND_DATA.
3. Discovery uses BlueZ's cached properties (Name, UUIDs) only. **No connect and no RF action** during discovery.
