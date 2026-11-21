<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# GPX extension namespace `urn:rain:task:gpx-ext:1`

task-maps writes standard GPX 1.1 (`http://www.topografix.com/GPX/1/1`) and puts its own fields in
`<extensions>` under the namespace URI **`urn:rain:task:gpx-ext:1`** (prefix `rain`). Other GPX
readers ignore them; task-maps reads GPX 1.0 and 1.1 with or without them.

| Element | Parent | Meaning |
|---|---|---|
| `rain:id` | `wpt`, `trk` | Stable task-maps id (UUID) of the waypoint/track. |
| `rain:source` | `wpt`, `trk` | `gps`, `map`, `manual` or `import:<file>`. |
| `rain:accuracy_m` | `wpt` | Horizontal accuracy (gpsd eph, else max(epx, epy)) in metres when the waypoint was taken from GPS. |

Version 1 is frozen; additions get a new URN (`…:2`). Import safety: files > 16 MiB, any
`DOCTYPE`/`ENTITY` declaration (billion-laughs, XXE), non-GPX roots, > 50 000 waypoints,
> 1000 tracks or > 1 000 000 points are rejected; out-of-range coordinates are skipped with a
warning. Export never overwrites an existing file without confirmation.

Note: `launcher/docs/MISSION-PLANNER-INTERFACE.md` (shipped in task-launcher 0.2.0) still names a
placeholder namespace `https://rain.invalid/gpx/1`. `urn:rain:task:gpx-ext:1` supersedes it; that
launcher document was deliberately not edited in Phase 4B so the released 0.2.0 sources stay
identical — update it with the next launcher release.
