<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# T.A.S.K. Maps & GPS (`task-maps` 0.1.0)

Native PySide6 map application of **T.A.S.K. — Tactical Access Support Kit**, started by the
launcher's *Maps & GPS* tile (`rain.maps`, which prefers `/usr/bin/task-maps` and falls back to
FoxtrotGPS only when task-maps is not installed). No QtWebEngine, no browser/HTML UI, no QtLocation.

> **Pi status: UNVERIFIED.** Everything here was built and tested on a development machine
> (offscreen Qt, local fixtures, loopback tile server, fake gpsd). Nothing has run on the Pi yet;
> see `docs/ACCEPTANCE-PI.md`.

## What it does

| Area | Summary |
|---|---|
| Viewer | Own QWidget renderer for raster MBTiles: drag/kinetic pan, wheel/pinch/+/− zoom, scale bar, cursor coordinates (decimal or DMS), attribution from metadata, GPS marker + accuracy circle + heading, follow mode, overzoom beyond the file's max zoom (amber dashed edge + status bar note), hatched **No offline coverage**, live states downloaded / downloading / missing / failed, bounded LRU cache, off-thread decoding. |
| Download Maps | Draw/move/resize a rectangle, choose source and zoom range, live tile count, size and storage estimate vs free space, rate-limit time estimate, progress (done/total, rate, ETA), pause/resume/cancel, retry failed tiles. Tiles appear on the map while downloading. Jobs survive restarts and power loss (resume prompt). |
| Sources | TOML definitions; only sources with verified, cited terms are offline-approved (shipped: USGS Topo, USGS Imagery). `tile.openstreetmap.org` is always refused. User-attested sources (e.g. your own LAN tile server) and offline **Import MBTiles** always work. |
| Storage | MBTiles 1.3, XYZ↔TMS flip, WAL, a single writer thread with batched transactions and checkpoints, duplicates skipped, tile bytes validated, integrity check, disk full → pause with no corruption. |
| GPS | gpsd JSON on 127.0.0.1:2947, read-only (`?WATCH` only). Position, fix mode, satellites used/visible, speed, course, altitude, eph/epx/epy, time, fix loss. Reconnects with backoff. rain-core's `gps.position` capability is shown for information. |
| Waypoints & tracks | Add at GPS or by clicking the map; rename, edit coordinates, delete; track recording with a distance/accuracy filter; GPX 1.1 import/export (safe parser, no overwrite without confirmation, extension namespace `urn:rain:task:gpx-ext:1`). |

## Paths

| What | Where |
|---|---|
| Program | `/usr/bin/task-maps`, modules in `/usr/share/task-maps/task_maps/` |
| Packaged sources | `/usr/share/task-maps/sources.d/*.toml` |
| User sources | `~/.config/task-maps/sources.d/*.toml` (example: `/usr/share/doc/task-maps/examples/local-tile-server.toml`) |
| API keys | `~/.config/task-maps/keys.toml` (mode 0600, never logged) |
| Settings | `~/.config/task-maps/settings.json` |
| Data (default) | `$XDG_DATA_HOME/task-maps` = `~/.local/share/task-maps` — configurable in Settings or `--data-dir` |
| Downloaded maps | `<data>/maps/<source-id>.mbtiles` (one file per source; regions are job rows, overlapping regions share tiles) |
| Imported maps | `<data>/maps/imported/*.mbtiles` (copied, or symlinked for large files) |
| Download jobs | `<data>/jobs.sqlite` |
| Waypoints/tracks | `<data>/waypoints.sqlite` |
| Instance lock | `~/.local/state/task-maps/instance.lock` |

The package owns none of the user paths: upgrades and `apt remove task-maps` never touch maps,
jobs, waypoints or settings.

## Run from the source tree

    python3 -m task_maps --windowed            # from maps/
    python3 -m pytest -q tests                 # offscreen; local fixtures only

Dependencies: Python ≥ 3.13 standard library (sqlite3, tomllib, urllib, xml.etree) and PySide6
QtCore/QtGui/QtWidgets ≥ 6.8 (Debian trixie: python3-pyside6.qtcore, .qtgui, .qtwidgets).
gpsd is recommended, not required.

See `ARCHITECTURE.md`, `SOURCES-POLICY.md`, `docs/ACCEPTANCE-PI.md`, `docs/GPX-EXTENSION.md`.
