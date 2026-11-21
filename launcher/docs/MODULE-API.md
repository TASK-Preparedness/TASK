<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Module API — design note (0.2.0)

Goal: let T.A.S.K. modules (Maps, Mesh, Radio, Library, …) appear either as **separate apps**
(today: manifest `exec`) or as **embedded panels / pop-out windows** inside the launcher, without
a second launch framework and without each module re-implementing rain-core access.

## 1. Two integration levels

| Level | How | Used in 0.2.0 by |
|---|---|---|
| External app | Manifest `[launch] exec` (+ alternatives, labels, actions). Process managed by the launcher's `ProcessManager` (Running/Error, logs, single instance, early-failure tail) | rain-mesh, task-maps/FoxtrotGPS, SDR++/Gqrx, rain-console |
| Native window | Manifest `[launch] builtin`; Python class in the launcher package (`ui/native_windows.py`) | Library, Radio / APRS, Weather, Medical, System, Devices fallback |

A third level — **plug-in panel** shipped by another package — is proposed below but not
implemented: running third-party Python inside the launcher process widens its trust boundary,
so it needs Joshua's decision first.

## 2. Native window contract (in-tree today)

```python
class _Base(QWidget):            # ui/native_windows.py
    def __init__(self, ctl): ...  # ctl = the MainWindow controller
    def refresh(self): ...        # user pressed Refresh / window shown
    def probes_updated(self): ... # readiness results changed (GUI thread)
    def run_bg(self, fn, done, name): # run blocking fn in a QThread, call done(result) on GUI thread
    def closeEvent(self, e): ...  # stops its threads
```

Rules: blocking I/O only in `run_bg`; loopback-only network; no writes outside the user's own
state directory; no hardware access (go through rain-core or a service the user started).

## 3. Shared services offered by the launcher

| Service | Object | Notes |
|---|---|---|
| rain-core client | `ctl.link` (`core/link.py`) | live, version, `capability_status(name)`, `counts`, `devices` (operator), sign-in state. One connection per launcher; modules must not open their own Core session from inside the launcher |
| Auth | `ctl.link.signed_in`, role; sign-in dialog | The session token stays in memory in the link object; it is never passed to external processes or written to disk |
| Devices | `ctl.link.devices` (read-only) | Never `device.assign` from a module |
| Readiness | `ctl.probes` (`services/readiness.ProbeResults`) | Kiwix, Direwolf, mesh, weather, medical, gpsd, SDR busy |
| Processes | `ctl.procs` (`ProcessManager`) | Same path as tiles (absolute argv, no shell) |
| Waypoints | (future) `docs/MISSION-PLANNER-INTERFACE.md` socket | |

External apps cannot share the launcher's Core session (by design). They connect to rain-core
themselves with their own credentials, as rain-console does.

## 4. Embedded panels and pop-outs (proposal)

- A native window can be shown either as a top-level window (today) or docked into a future
  "workspace" area of the launcher; the same widget class is used, so pop-out = reparent.
- Proposed plug-in manifest key (not accepted by the 0.2.0 parser): `[panel] module =
  "task_maps.panel:MapsPanel"`, loaded only from package-trust manifests in
  `/usr/share/task-launcher/apps.d`, with a `min_platform` check. Requires decision (trust).

## 5. task-maps (Phase 4B) interface notes

- Manifest 020-maps already lists `/usr/bin/task-maps` first, labelled "T.A.S.K. Maps"; installing
  the binary switches the tile from "FoxtrotGPS (fallback)" with no launcher change.
- task-maps should: accept no required arguments; support `--version`; raise its existing
  window when started twice, or rely on `single_instance` (`on_reactivate = "notify"` today);
  read GPS through rain-core `gps.position` when a provider exists, else gpsd, and say which;
  use the waypoint store and IPC in MISSION-PLANNER-INTERFACE.md; work fully offline from
  local tiles (MBTiles / directory tiles); never fetch remote tiles by default.
- If task-maps later offers an embeddable panel, it uses §4.
