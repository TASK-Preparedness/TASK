<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Hardware checklist (to be done by you on the Pi; none of this has been done)
Mark each: PASS / FAIL / N/A, with date. Service stays disabled unless a step says otherwise.
1. Preflight: `./preflight-phase4f.sh` (read-only) — record versions, notification daemon, serial owners.
2. Meshtastic radio on USB: window opens, Devices shows by-id path; assign "Meshtastic"; nodes appear; receive a channel msg.
3. Send a channel and a DM **only** after signing in (operator); confirm ACK states in the Meshtastic sub-tab.
4. MeshCore companion on USB: assign "MeshCore"; Identify (click) reports meshcore; contacts appear in MeshCore → Nodes.
5. MeshCore: messages queued on the device before connect appear as history (not counted as unread, no pop-up).
6. MeshCore live DM and channel message: unread +1, pop-up (if a daemon is installed), generic while signed out.
7. MeshCore send DM/channel after sign-in; reply received on another node.
8. Unplug/replug each radio: reconnect within ~60 s; no duplicate messages.
9. Two radios at once (one per protocol): All Messages shows both, separately labelled; no merged identities.
10. Enable service (`systemctl --user enable --now task-mesh-service`), restart window: window shows service banner,
    does not open ports; messages arrive with the window closed; launcher badge counts them; badge never clears them.
11. Reboot with service enabled: service starts after login; disable it again (`systemctl --user disable --now ...`).
12. Launcher: all 12 tiles present, Medical and Library open as before, placement unchanged.
13. Confirm no radio settings changed (compare meshtastic --info / MeshCore app before and after) and nothing transmitted
    except your explicit sends.
