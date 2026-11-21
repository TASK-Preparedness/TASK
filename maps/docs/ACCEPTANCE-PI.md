<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Offline acceptance scenario (§5.9) — the core Pi test

**Status: UNVERIFIED on the Pi.** Every step below is still to be performed by Joshua on the
Pi 5 (Debian trixie, labwc). Results from the development machine are in TEST-REPORT, not here.

Preconditions: task-launcher 0.2.0 and task-maps 0.1.0 installed; gpsd installed and running with
the u-blox 7 (`systemctl status gpsd`); network available for step 2 only.

| # | Step | Expected | Result |
|---|---|---|---|
| 1 | Start the launcher, tap **Maps & GPS**. | T.A.S.K. Maps & GPS opens (not FoxtrotGPS); tile label "T.A.S.K. Maps". | UNVERIFIED |
| 2 | **Download** → source *USGS Topo* → drag a rectangle around a local area (≈ 5×5 km) → zoom 10–15 → read the estimate → **Download**. | Tile count, size, storage vs free space shown; progress with rate/ETA; tiles appear on the map while downloading; finishes "Completed". | UNVERIFIED |
| 3 | During step 2 pull the network for ~1 min, then restore it. | State "Waiting for network", then resumes by itself; no failed tiles from the outage. | UNVERIFIED |
| 4 | During step 2 close task-maps, start it again. | Prompt "Resume download?"; Yes → continues from the checkpoint. | UNVERIFIED |
| 5 | Disconnect all networking (Wi-Fi off, Ethernet out). Restart task-maps. | The downloaded area renders at all downloaded zooms; outside it hatched "No offline coverage"; above z15 marked overzoom. Nothing waits for the network. | UNVERIFIED |
| 6 | GPS panel (u-blox 7 outdoors / at a window). | gpsd connected; fix mode, satellites used/visible, position, speed, course, eph; marker + accuracy circle on the map; **Follow** keeps it centred; manual pan turns Follow off. | UNVERIFIED |
| 7 | Cover the antenna / unplug the u-blox; then reconnect; `sudo systemctl restart gpsd`. | "fix lost" shown with the last position; after restart the client reconnects by itself. | UNVERIFIED |
| 8 | Add a waypoint at GPS and one by clicking the map; rename one; record a short track by walking. | Waypoints and track visible and listed. | UNVERIFIED |
| 9 | Export GPX to a USB stick; import it again; try exporting over the same file. | Round trip works; overwrite asks first. | UNVERIFIED |
| 10 | Copy an `.mbtiles` file to a USB stick, **Maps → Import MBTiles file…** while offline. | Checked, copied (or linked if large) into `~/.local/share/task-maps/maps/imported/`, shown. | UNVERIFIED |
| 11 | Reboot the Pi; open task-maps offline. | Maps, waypoints, tracks, settings and finished/paused jobs are all still there. | UNVERIFIED |
| 12 | Run at 1024×600 (`wlr-randr --output <out> --mode 1024x600` or the 7" panel) and at 1920×1080. | All panels usable, no horizontal scrolling, map remains large; touch pan and two-finger pinch work. | UNVERIFIED |
| 13 | `sudo apt remove task-maps`, open Maps & GPS from the launcher. | FoxtrotGPS (fallback) opens; `~/.local/share/task-maps` still exists. Reinstall restores everything. | UNVERIFIED |

Also check: `task-maps` refuses to run as root; a second start shows "already running"; disk-full
behaviour can be tried on a small USB stick as data folder (Settings → Data folder, restart):
the job pauses as "Paused — storage" and the map file appears in the **Maps** list without a
PROBLEM line.
