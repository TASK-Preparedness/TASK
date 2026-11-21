<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# SPEC — Maps online/offline (Phase 4I)
* **Preserve** `~/.local/share/task-maps/maps/usgs-topo.mbtiles` and every user MBTiles across upgrades: packages never
  ship, move or delete files under ~/.local/share/task-maps; migrations only add metadata. Test: upgrade keeps file hash.
* **No automatic bulk downloads.** Downloads only from an explicit user action, per-source policy
  (offline_download_permitted + evidence, OSM standard tiles refused — already in sources.py), estimate shown first.
* Online mode: live tiles only when the user enables a source; auto-cache stays opt-in and size-capped.
* Offline mode: default; works with no network; source/attribution always shown.
* Tests: no network calls at start; policy refusal; size estimate; mbtiles preserved; gpsd absent → still renders.
