<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Phase 4F test matrix (comms + security). All x86, mocks/simulators; none on the Pi or hardware.

| # | Requirement | Test |
|---|---|---|
| T01 | hub DB 0600, dedupe | tests/hub::test_T01 |
| T02 | history sync stored, not unread | T02 |
| T03 | identities never merged across protocols | T03 |
| T04 | reads never mark read; only explicit mark_read | T04 |
| T05 | priority only from metadata (BEL) or user rule, labelled | T05 |
| T06 | locked/unknown → generic "New Mesh Message", count kept | T06 |
| T07 | preview off by default; per-protocol + per-conversation mute | T07 |
| T08 | viewer / forged / no session never unlocks | T08 |
| T09 | sync + duplicates never pop up | T09 |
| T10 | sound setting → suppress-sound hint | T10 |
| T11 | typed Notify over a real session bus (fake server, dbus-run-session) | T11 |
| T12 | send needs explicit_user_action=True AND operator session; size limit; own msg not unread | T12 |
| T13 | IPC send without explicit flag refused | T13 |
| T14 | no message text or session token in logs | T14 |
| T15 | IPC socket 0600, round trip, unread read-only | T15 |
| T16 | IPC rejects other uid | T16 |
| T17 | single-instance service lock | T17 |
| T18 | per-device lock: service vs GUI | T18 |
| T19 | GUI (0.2.0 RadioWorker) never opens a port locked by the service | T19 |
| T20 | unassigned/ignored ports never opened; assignments 0600 | T20 |
| T21 | probe writes only ALLOWED_WRITES; want_config frame parses as protobuf ToRadio | T21 |
| T22 | MeshCore sim: queued=sync, push=live, claimed channel names, no TX without send, BLE PIN dropped | T22 |
| T23 | MeshCore reconnect after drop (bounded backoff) | T23 |
| T24 | Meshtastic: BEL priority labelled protocol:, old rxTime = sync | T24 |
| T25 | bridge/relay is a disabled stub | T25 |
| T26 | service restart keeps history + unread | T26 |
| T27 | GUI direct mode: exactly the 5 tabs | tests/integration/test_hub_tabs::T27 |
| T28 | service running → GUI attaches, owns no radio | T28 |
| T29 | quiet mode / quiet hours suppress pop-ups, keep counts | T29 |
| T30 | history retention keeps unread | T30 |
| T31 | per-conversation mute from the GUI, no mark-read while locked | T31 |
| L1–L5 | launcher badge read-only (DB digest unchanged), socket uses only "unread", text, readiness line, 12 tiles incl. task.medical/task.library | launcher/tests/test_p4f_meshbadge.py |
| C1–C3 | comms mesh sources, generic locked notification, badge_group | comms/tests (0.3.1 additions) |
