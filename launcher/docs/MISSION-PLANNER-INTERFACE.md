<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Mission Planner — interface (design only, not implemented)

Status: the Mission Planner tile stays **Planned** in 0.2.0. This document fixes the data and
IPC contracts so that Maps (task-maps, Phase 4B), Mesh (rain-mesh) and the planner can share
waypoints later. Nothing here is implemented; no file or socket below is created by 0.2.0.

## 1. Waypoint store

- **Format:** GPX 1.1 (`http://www.topografix.com/GPX/1/1`) so that FoxtrotGPS, Viking,
  OpenCPN, phones and GPS units can import/export without conversion. Extensions live in the
  namespace `https://rain.invalid/gpx/1` (prefix `rain:`; final URI to be chosen by Joshua).
- **Location:** per user, `~/.local/share/task/waypoints/` (XDG data dir):
  - `waypoints.gpx` — the current set (`<wpt>`), routes (`<rte>`) and recorded tracks (`<trk>`);
  - `missions/<mission-id>.gpx` — one file per mission (waypoints + routes + metadata);
  - `.lock` — advisory `flock` held only while writing.
- **Writes are atomic:** write `*.gpx.tmp` in the same directory, `fsync`, `rename`. Readers
  never see a partial file. Every write bumps `<metadata><time>` and `rain:revision` (integer).
- **Per-waypoint fields:** `lat`, `lon` (WGS-84, required), `ele`, `time` (UTC ISO-8601),
  `name` (≤ 40 chars), `desc`, `sym`, `type`, plus extensions:
  `rain:id` (UUIDv4, stable across edits), `rain:source` (`manual` | `gps` | `mesh:<node-id>` |
  `aprs:<callsign>` | `import:<file>`), `rain:created`, `rain:modified`, `rain:accuracy_m`,
  `rain:mission` (mission id), `rain:status` (`planned` | `reached` | `skipped`).
- **Positions from other stations** (mesh nodes, APRS) are kept apart from the user's own
  waypoints (`rain:source` ≠ `manual`) and are never re-transmitted automatically.
- No secrets, no patient data, no credentials in waypoint files.

## 2. Local IPC contract

- **Transport:** a per-user Unix domain socket `$XDG_RUNTIME_DIR/task/waypoints.sock` (mode
  0600, directory 0700). No TCP listener, no network exposure. One owner process (the planner
  or task-maps, whichever runs first; the other becomes a client).
- **Framing:** newline-delimited JSON-RPC 2.0 (same framing as rain-core's socket, so the
  launcher's Core client code can be reused).
- **Methods:**

| Method | Params | Result |
|---|---|---|
| `waypoints.list` | `{mission?, since_revision?}` | `{revision, waypoints:[…]}` |
| `waypoints.get` | `{id}` | waypoint |
| `waypoints.put` | `{waypoint}` (no `id` = create) | `{id, revision}` |
| `waypoints.delete` | `{id}` | `{revision}` |
| `missions.list` | `{}` | `[{id, name, revision, modified}]` |
| `missions.export` | `{id}` | `{gpx}` (string) |
| `missions.import` | `{gpx, name?}` | `{id}` — validated, size-capped (4 MiB) |
| `events.subscribe` | `{topics:["waypoints","missions"]}` | stream of `{"method":"event", "params":{topic, revision, id, op}}` |

- **Errors:** JSON-RPC codes; `-32602` invalid params, `-32010` not found, `-32011` revision
  conflict (client sent `if_revision` and the store moved on).
- **Auth:** same user only (socket permissions + `SO_PEERCRED` uid check). Role-gated actions
  that leave the box (sending a waypoint over mesh or APRS) are **not** part of this API; they
  stay in rain-mesh / rain-core behind explicit user action.

## 3. What the launcher will do

Show the tile as Available once a planner executable exists (manifest `exec`), with a
readiness line from `waypoints.list` (count + last modified). Until then: Planned.
