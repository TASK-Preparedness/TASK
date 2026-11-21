<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Phase 4F.1 manual Pi validation (Heltec V3 Meshtastic on CP2102 ttyUSB0; GPS ttyACM0 must stay untouched)
Nothing here has been done by the builder. Mark PASS/FAIL/N/A + time. Run commands as `dragon` in an LXDE terminal.
Mock test that covers each item: in brackets.

| # | Step | Expected | Mock test |
|---|---|---|---|
| 1 | `./preflight-phase4f1.sh` before install | versions 0.3.0/0.3.1/0.3.3; notification owner "no"; ACM0 listed, not opened | — |
| 2 | Stop service yourself, install, `systemctl --user start task-mesh-service` | service active; radio opened by service (Devices tab later shows owner service) | — |
| 3 | Open Mesh, click Connect and Retry | banner "Not connecting: task-mesh-service owns the radios"; **no** BACKOFF / "in use" | G1 |
| 4 | Network Status | "background service (task-mesh-service 0.3.1, pid N)"; Heltec state connected | — |
| 5 | Send a message from another node | appears in the window within ~1 s (live stream) | A02, G2 |
| 6 | Reply: signed out → refused; sign in (operator) → Send | refused / delivered via service ("sent") | A04 |
| 7 | Close the window, send another message | badge +1; service log shows receive; nothing lost | A05 |
| 8 | `systemctl --user restart task-mesh-service` with window open | banner "not responding…" then re-attached; window never opens the port | A03, G4 |
| 9 | Unplug/replug the Heltec | service reconnects; no duplicate message/pop-up | A09 |
| 10 | `systemctl --user stop task-mesh-service`, wait 15 s | window switches to direct; does not connect until you click Connect | G4 |
| 11 | With window in direct mode + connected, start the service | window releases the port; service takes it | G3 |
| 12 | `task-mesh-notify-setup` | reports root cause (no activation file); writes nothing | A18 |
| 13 | `task-mesh-notify-setup --enable`, log out/in | two user files; after login a pop-up can show | A18 |
| 14 | Window minimized/unfocused, message arrives | pop-up "T.A.S.K. — New Mesh Message", ~5 s, position noted (upper-right?) | A06, A17 |
| 15 | Signed out vs signed in (+ preview on) | generic body vs protocol/sender(/preview) | A06 |
| 16 | Window focused, message arrives | no pop-up; unread count rises; not marked read | A10 |
| 17 | Kill the window (`kill -9`), message arrives | pop-up appears (lease dropped / expired ≤15 s) | A11, A12 |
| 18 | Click a pop-up (window closed and open) | window opens/raises at that conversation | A14–A16, G5 |
| 19 | 5 messages within 10 s | at most 2 single pop-ups + 1 grouped "N new mesh messages" | A08 |
| 20 | Mute conversation / quiet hours | no pop-ups; counts still rise. Afterwards: `ls -l ~/.config/task-mesh/radio-protocols.json` unchanged; `journalctl --user -u task-mesh-service` shows no message text | A07, A19 |
