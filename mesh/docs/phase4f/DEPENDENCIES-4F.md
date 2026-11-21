<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Dependency / architecture review (Phase 4F)

## meshcore_py 2.3.15 (MIT) — details in MESHCORE-RESEARCH.md
* **Licence:** MIT → GPL-3.0-or-later compatible (notice kept in /usr/share/doc/task-mesh/copyright).
* **API used (allow-list adapter.COMMANDS_USED):** send_appstart, send_device_query, get_bat, get_contacts,
  get_msg (drain until NO_MORE_MSGS), send_msg / send_chan_msg (explicit GUI send only). Nothing that changes radio,
  contact or channel settings; no reboot, no firmware, no export_private_key.
* **Serial:** SerialConnection with host→device `<`+len16 and device→host `>`+len16 frames over pyserial-asyncio-fast.
  115200 baud. USB companion firmware only (BLE/TCP companion not used).
* **Firmware:** companion protocol v3 frames (CONTACT_MSG_RECV_V3 / CHANNEL_MSG_RECV_V3) assumed; older v1/v2 frames
  are parsed by meshcore but not exercised by our simulator. UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST on real firmware.
* **Events:** MESSAGES_WAITING push → drain (live); queued messages drained at session start are tagged sync (not
  unread-for-popups, but stored). ADVERTISEMENT/contacts → nodes. DEVICE_INFO.ble_pin dropped.
* **Reconnect:** our own bounded backoff 2/5/10/30/60 s after disconnect callback; meshcore auto_reconnect not used. T23.
* **Logging:** meshcore logs payloads at DEBUG → logger pinned to WARNING, propagate=False.
* **Debian incompatibility:** python3-pycryptodome provides only `Cryptodome`; scoped alias shim (compat.ensure_crypto).

## meshtastic-python 2.7.11 (GPL-3.0) — vendored wheel, unchanged since 0.2.0
* GPL-3.0 → compatible (we are GPL-3.0-or-later; combined work is GPL-3.0).
* Serial via SerialInterface (0.2.0 provider), pypubsub, protobuf (Debian python3-protobuf).
* MeshPacket.priority is not sent over the air; BEL (0x07) is the only alert marker.

## Other runtime deps (Debian trixie)
| Dep | Licence | Source |
|---|---|---|
| python3-pyside6 (Qt 6) | LGPL-3.0 | Debian (unchanged) |
| python3-jeepney 0.9.0 | MIT | Debian, NEW Depends (D-Bus Notify) |
| python3-pycryptodome 3.20 | BSD/PD | Debian, NEW Depends |
| python3-serial 3.5 | BSD-3 | Debian |
| pyserial-asyncio-fast 0.16 | BSD-3 | vendored wheel |
| pycayennelpp 2.4.0 | MIT | vendored wheel |
| python3-task-comms >= 0.3.1 | GPL-3.0+ | ours |
All compatible with GPL-3.0-or-later. No network service, no root, no D-Bus system bus.
