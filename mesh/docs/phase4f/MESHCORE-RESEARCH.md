<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# MeshCore companion API: verified facts (2026-10-13)

The source is the PyPI JSON API and the unpacked wheel. Nothing below was run against hardware.

## Library
| Item | Value |
|---|---|
| Package | `meshcore` (PyPI). Upstream https://github.com/fdlamotte/meshcore_py |
| Version bundled | **2.3.15** (latest on PyPI at check time), `meshcore-2.3.15-py3-none-any.whl` sha256 `48344fdb2ebdeea82955bd01a9f865a2f03b4a9bdf709dacbde7ea8cd30ba37e` |
| Licence | **MIT** (LICENSE: "Copyright (c) 2025 Florent de Lamotte"). It is GPL-3.0-compatible, so task-mesh stays GPL-3.0-or-later and the MIT notice is kept. |
| Python | >= 3.10 (trixie has 3.13) |
| Requires | `pycryptodome`, `pyserial-asyncio-fast`, `pycayennelpp`, `bleak` |

## Dependencies on Debian 13 (trixie arm64 Packages index)
| Upstream dep | Debian | Decision |
|---|---|---|
| pyserial-asyncio-fast 0.16 (BSD-3-Clause, needs pyserial) | not packaged | **bundled** wheel sha256 `88939d94…df1687`. Its pyserial dependency comes from Debian `python3-serial` 3.5-2. |
| pycayennelpp 2.4.0 (MIT) | not packaged | **bundled** wheel sha256 `a3e69ea4…901d62`. Pure Python, only used to decode telemetry. |
| pycryptodome | `python3-pycryptodome` 3.20.0+dfsg-3 (arm64) | **Depends**. **INCOMPATIBILITY:** the Debian package installs only the `Cryptodome` namespace (it is pycryptodomex; checked via `dpkg-deb -c`). meshcore does `from Crypto.Cipher import AES`. task-mesh fixes this with a scoped import alias (`task_mesh/protocols/meshcore/compat.py`). It maps `Crypto.*` to `Cryptodome.*` only when `Crypto` is not importable, and it does not install a top-level `Crypto` package. |
| bleak | `python3-bleak` 0.22.3-1 | **not required**: meshcore imports bleak optionally (`ble_cx.py` try/except). task-mesh uses USB serial only. BLE is "Suggests" and is not implemented. |

## What the companion protocol exposes (2.3.15)
**Implemented in task-mesh 0.3.0:**
- Serial connect with the `<` + len16 framing: `MeshCore.create_serial`. It sends `CMD_APP_START`, which is a host↔device session start and not a radio transmission.
- Device info: `send_device_query` gives fw ver, model, ver, fw_build, max contacts/channels and repeat mode. The `ble_pin` field it also returns is dropped immediately and never stored or logged.
- Self info: `SELF_INFO` gives name, public key, radio freq/bw/sf/cr and tx power. These are read only; no setter is called.
- Contacts / nodes / repeaters: `get_contacts` returns `CONTACTS`, and `type` gives 1 = chat, 2 = repeater, 3 = room server, 4 = sensor. Live updates come from `NEW_CONTACT` and `ADVERTISEMENT`.
- Direct messages: `CONTACT_MSG_RECV` with pubkey_prefix (6 bytes), sender_timestamp, txt_type, path_len, and SNR on v3.
- Channel messages: `CHANNEL_MSG_RECV` with channel_idx, sender_timestamp and text. **There is no authenticated sender field.** By convention the text is "Name: message", so task-mesh shows that name as *claimed* and never links it to a contact.
- Queued messages (history): `get_msg` / `MESSAGES_WAITING` drain the device's offline queue. During the initial sync these are stored as `origin='sync'`, are **not** counted as new, and do not notify.
- Signal: SNR from v3 frames, plus RSSI/SNR from `get_stats_radio` where the firmware supports it.
- Status: `get_bat` (level, storage).
- Firmware info: from DEVICE_INFO.
- Reconnect: task-mesh supervises its own backoff and does not use the library's auto_reconnect, so device locks stay under our control.
- Sending, only as an explicit GUI action with an operator session: `send_msg` (DM) and `send_chan_msg`.

**Exposed, but deliberately not used:**
- `set_*` (name, radio, tx power, channel, PIN, coordinates, custom vars), `reboot`, `import/export_private_key`, `send_advert`, `run_cli_command`, `send_raw_packet`, `send_login`, `set_flood_scope`. All of these change settings or transmit, so they are **never called**. A test enforces this with an allow-list.

**Missing or not exposed:**
- No message ids on receive. Dedupe uses (pubkey_prefix | channel, sender_timestamp, sha256(text)).
- No priority field, so MeshCore priority comes only from user rules.
- No read receipts.
- No "history range" query: the device keeps a small offline queue only.

**MeshCore 0.3.1 candidates:** path discovery / trace, telemetry requests, repeater status (`req_status`), room-server login. These transmit and need an explicit-action UX.

## Logging
meshcore logs payloads at DEBUG (`send_msg` logs text and destination; serial_cx logs raw frames). task-mesh pins the `meshcore` logger to WARNING, sets `propagate=False` and only adds a redacting handler, so no content or keys reach the logs. A test covers this.

## Protocol probing (read-only)
- Meshtastic frames start with `0x94 0xC3`.
- MeshCore device→host frames start with `0x3E` ('>') + len16 (host→device uses `0x3C`).
- The probe opens the port, listens passively, and may then send exactly one read-only query (MeshCore `CMD_DEVICE_QUERY 0x16 0x03`, or the Meshtastic `want_config` that 0.2.0 already sends).
- It never writes settings or transmits on RF.
- Results are cached per by-id path, and a user override wins.
- UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST. In particular, opening the port can toggle DTR/RTS and reset some ESP32 boards; this happens with 0.2.0 too.
