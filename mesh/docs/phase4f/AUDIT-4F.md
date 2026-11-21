<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# AUDIT-4F — feature completeness (source + tests, not design docs)

Inspected 2026-10-13 on the x86 build box only. **Nothing here was run on the Pi.** Sources:
`/workspace/task-mesh` (branch phase4f-mesh), `/workspace/task-phase4c-wt` (branch phase4f: task_core, comms,
launcher, resources, maps, aprs, sdr). Pi state as reported by the user (not verified by me): core 0.3.0,
core-compat 0.3.0, launcher 0.3.2, resources 0.2.1, mesh 0.2.0, comms 0.3.0, aprs 0.1.0, sdr 0.1.0, maps 0.1.1.

Classes: **IV** Implemented + verified (automated tests on x86 with mocks/simulators) · **IH** Implemented,
not hardware-verified · **P** Partial · **PL** Planned (placeholder only) · **M** Missing · **B** Blocked.
Nothing is IV *on hardware*: every radio item is "UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST".

| Area | Class | Evidence (file → test) | Gap |
|---|---|---|---|
| Meshtastic (receive, nodes, DM/channel send, ACK) | IH | task_mesh/radio/*, messaging/* (0.2.0) → tests/unit, tests/integration (313) ; 0.3.0 adapter protocols/meshtastic_adapter.py → T24 | real radio; ACK states in service mode only "sent" |
| MeshCore (companion USB serial) | IH | protocols/meshcore/{compat,adapter}.py on meshcore 2.3.15 → T22, T23 (frame-level SimCompanion using the real SerialConnection parser) | real firmware; BLE/TCP not used; repeater/room admin not implemented |
| Background receiver (task-mesh-service) | IH | service.py, packaging/systemd/task-mesh-service.service (user unit, disabled) → T15–T18, T26 | systemd-analyze unavailable here: unit UNVERIFIED |
| Message history | IV (sim) | hub/store.py hub.sqlite3 0600 WAL → T01, T02, T26 | retention/pruning of hub DB not implemented (P) |
| Unread | IV (sim) | store.unread: read=0 ∧ origin=live ∧ direction=in; mark-read only on explicit selection while unlocked → T02, T04, T12 | |
| Notifications | IV (sim) / IH (desktop) | hub/notifier.py, jeepney Notify → T06, T07, T09, T10, T11 (fake server on a real session bus) | Pi has no notification daemon installed by LXDE-core by default (documented; we never install one) |
| Launcher Mesh badge | IV (unit) | launcher/services/meshbadge.py → test_p4f_meshbadge.py (read-only digest check) | GUI direct mode has no IPC server; badge then reads the comms store (ro) |
| Serial ownership | IV (unit) / IH | hub/locks.py flock per tty; radio/locking.py wraps 0.2.0 RadioWorker; DeviceManager opens only assigned by-id ports → T18–T20 | non-T.A.S.K. programs (meshtastic CLI, ModemManager) do not honour our lock; exclusive=True open is the backstop |
| Inventory | M | no code in any repo (grep) | spec: docs/phase4f/SPEC-INVENTORY.md |
| Medical / Resources integration | P | launcher builtin MedicalWindow (native_windows.py:530) lists Kiwix/IIAB/folders, reference only; Core rejects medical.patients.* (api.py:133) ; resources has categories in its index but **no CLI/category filter entry point** (app.py argparse: --viewer, --no-scan, --version only) | spec: SPEC-MEDICAL.md |
| Maps online/offline | IH | task-maps 0.1.1: own MBTiles renderer, sources.py offline_download_permitted policy (OSM bulk refused), gpsd | not re-tested in 4F; spec SPEC-MAPS.md |
| APRS | IH | task-aprs 0.1.0: receive via Direwolf AGW/KISS, amateur TX through Direwolf with comms txpolicy + audit; GMRS driver simulated only | real TNC/radio |
| Devices tile | P | manifest 090 execs /usr/local/bin/task-console; tile "Unavailable" when absent (test_registry_tiles) ; launcher DevicesWindow exists | spec SPEC-DEVICES.md |
| Launcher: 12 original tiles | IV | apps.d/010…120; test_registry_tiles BUILTIN_KEYS + test_p4f_meshbadge (12, task.medical, task.library) | |
| Launcher: pagination | IV | ui/pager.py → test_pager.py | |
| Launcher: persistent placement | IV | registry/tilestore.py tiles.json → test_move_reorder_and_reset, test_corrupt_store_falls_back_to_defaults | |
| Launcher: status/indicators | IV | services/readiness.py, statuscards.py | |
| Auth: medical data | P (no data to protect yet) | Core refuses medical.patients.* at API; launcher Medical is reference only | patient records not designed |
| Auth: messages | IV (unit) | message content shown only when the comms SessionGate is unlocked (Core session); notifications generic when locked/unknown; send needs explicit_user_action **and** Core session role operator/administrator verified server-side (session.whoami) → T06, T08, T12, T13 | Content at rest protected only by Unix permissions (0600), not encrypted |
| Auth: device config | P | Core device.assign/unassign = administrator (api.py); task-mesh radio-protocols.json is per-user, no role check (it only selects which local radios the user's own app opens; never radio settings) | |
| Auth: inventory edit | M | no Inventory | spec defines role checks in the service, not the UI |
| Auth: admin | IV (Core) | Core METHODS minimum roles enforced in _dispatch, not in UI; launcher min_role gate (main_window.py:320) is UI-only but launch targets enforce their own | |
| Hidden UI is not the only authorization? | mostly yes | Core: server-side; mesh send: server-side (hub.send); launcher App Manager "Show administrative entries" checkbox is cosmetic and the actions behind it go through Core | resources index editing has **no** role check (single local user) — noted |
| Mission Planner | PL | apps.d/060-mission.toml status="planned"; launcher/docs/MISSION-PLANNER-INTERFACE.md | |
| Sewing resources | M | only a line in docs/ARCHITECTURE.md:154 (FreeSewing offline libraries "when that module is built") | roadmap item |

## Contradictions with earlier plans
1. **Meshtastic priority.** Earlier plans said "priority from protocol metadata". `MeshPacket.priority` is a local
   queueing hint and is never transmitted (mesh.proto), so the only over-the-air signal is the BEL character
   (alert). We label it `protocol:meshtastic-bell`. MeshCore has no priority field at all → only user rules.
2. **Mesh vs Core.** 0.2.0 said task-mesh "does not use task-core". 0.3.0 keeps receive Core-free, but sending and
   showing content now require a Core session (operator+). With Core down, receive and counts still work; send is refused.
3. **Medical tile.** Plans described Medical as a Resources category view; the shipped tile is the launcher's
   built-in MedicalWindow. Resources has no supported category entry point, so a `--category` launch would be an
   unsupported hack (not done). Spec F defines the supported path while keeping the built-in fallback.
4. **Devices tile** points at task-console, which is not installed on the build box; it shows Unavailable, as tested.
5. **Badge in GUI direct mode** comes from the comms store, not the service, because only the service exposes IPC.
6. **MeshCore channel sender identity.** Plans assumed a sender per message; MeshCore channel messages carry only a
   claimed "Name: " text prefix. We show it as "(claimed)" with an empty sender id and never match rules on it.
7. Phase numbering kept: 4A launcher, 4B maps, 4C comms, 4D/4E resources, **4F mesh hub**, 4G inventory, …
