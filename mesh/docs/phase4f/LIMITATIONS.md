<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Limitations (0.3.0)
* **Nothing tested on hardware or on the Pi.** All radio behaviour: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.
* x86 build box only: Debian trixie userland in a venv, Qt offscreen, dbus-run-session. Pi arm64 results: none.
* systemd unit not validated (no systemd-analyze / user manager on the build box).
* MeshCore: USB companion firmware only; v3 message frames exercised by simulator; no BLE/TCP, no repeater/room admin,
  no contact management, channel sender is only a claimed name.
* Meshtastic in service mode: delivery shows "sent" only (no ACK tracking yet; window mode keeps 0.2.0 ACK states).
* Switching window ↔ service needs a window restart.
* Message content at rest protected by file permissions (0600) only, not encrypted.
* Third-party programs (meshtastic CLI, ModemManager) do not honour T.A.S.K. locks; exclusive open is the backstop.
* No notification daemon is installed; without one there are no pop-ups.
* GUI direct mode exposes no socket; the launcher badge then reads the comms store.
