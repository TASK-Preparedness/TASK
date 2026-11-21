<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# task-launcher app manifest — schema v1 (platform 0.2.0)

Implementation: `task_launcher/registry/manifest.py` (parser and validation) and
`task_launcher/registry/discovery.py` (directories and precedence). Tests:
`tests/test_manifests.py`, `tests/test_p4_registry.py`.

Schema v1 is unchanged in 0.2.0: platform 0.2.0 only adds **optional** keys (marked *0.2.0*
below). Every 0.1.0 manifest is still valid. A manifest that uses a 0.2.0 key should say
`min_platform = "0.2.0"` so that an 0.1.0 launcher shows it as Unavailable rather than
rejecting it as malformed.

A manifest is one UTF-8 TOML file per app, `*.toml`, at most 64 KiB.

## Directories and precedence

| Order | Directory | Trust | Purpose |
|---|---|---|---|
| 1 | `/usr/share/task-launcher/apps.d` | package | Shipped by the Debian package (the 12 built-ins) |
| 2 | `/etc/task-launcher/apps.d` | admin | Administrator additions; **replaces** a package manifest with the same `id` (logged as info) |
| 3 | `~/.local/share/task-launcher/apps.d` | user | Per-user apps; **may not** replace a system `id` (rejected) |

Files are read in name order. Within one directory, a second file with the same `id` is rejected.
When the package directory does not exist (running from a source checkout), the bundled
`task_launcher/data/apps.d` is used in its place.

A file is **rejected** (it is listed under "Manifest problems" in App Manager, and discovery
continues) when:

- it is a symlink, not a regular file, larger than 64 KiB, or world-writable;
- it is a user manifest that is not owned by the user;
- the TOML is malformed or any rule below is broken.

## Top-level keys

Unknown keys are errors, so typos are caught.

| Key | Type | Required | Rule |
|---|---|---|---|
| `manifest_version` | integer | yes | must be `1` |
| `id` | string | yes | `^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*){1,3}$`, e.g. `rain.system`, `org.example.app` |
| `name` | string | yes | 1–40 characters (shown on the tile) |
| `version` | string | yes | `MAJOR.MINOR.PATCH` (optional `-suffix`) |
| `description` | string | no | ≤ 300 characters |
| `icon` | string | no | a bundled Lucide name (`[a-z0-9-]`), or a path to an SVG inside the manifest's directory or the icon directories. A bad icon is a **warning**: the `shapes` icon is used instead |
| `order` | integer | no | 0–100000, default 10000 (default position; the user can reorder) |
| `status` | string | no | `available` (default) or `planned` |
| `roadmap` | string | no | ≤ 80 characters; shown on planned tiles |
| `min_platform` | string | no | launcher platform version required (current platform: 0.2.0); otherwise the tile is Unavailable |
| `enabled` | bool | no | default `true`; the per-user override lives in `tiles.json` |
| `single_instance` | bool | no | default `true` |
| `readiness` | string | no | *0.2.0.* Name of a built-in readiness probe: `gps`, `rtl-sdr`, `mesh`, `kiwix`, `direwolf`, `weather`, `medical`. Its result is shown as a second, smaller line on the tile (display only; it never changes the status or blocks a launch). Probes run in a background worker with short timeouts |
| `status_note` | string | no | *0.2.0.* ≤ 60 characters shown after "Available — " (used by built-in windows, e.g. "receive-only monitor") |
| `min_role` | string | no | `public` (default), `operator` or `administrator`. **Advisory:** the launcher asks the user to sign in first, but it cannot pass its session to the app; rain-core enforces roles itself |

A `planned` manifest must not have a `[launch]` table. A planned tile only opens an information
sheet; it is never shown as Available. A planned manifest may not have `[[actions]]` either.

## `[launch]`

| Key | Type | Rule |
|---|---|---|
| `exec` | array of strings | argv. The first element must be an absolute path. No shell is involved: `;`, `$()` and similar are passed literally |
| `exec_alternatives` | array of argv arrays | at most 8. Tried in order after `exec`; the first that passes the checks is used |
| `builtin` | string | `system`, `app-manager`, `files`, `devices`, and *0.2.0* `library`, `radio`, `weather`, `medical` (native windows). **System manifests only** (package or admin). Only `devices` may also carry `exec` (the rain-console candidates) |
| `on_reactivate` | string | `notify` (default: say "already running") or `relaunch` (start the command again for apps that raise their own window, e.g. rain-console) |

| `labels` | table | *0.2.0.* `[launch.labels]`: program path = label (1–60 characters). Keys must be the program (`argv[0]`) of `exec` or of an alternative. The label of the variant in use is shown on the tile: "Available — FoxtrotGPS (fallback)". When no candidate is installed, the reason lists the labels: "not installed: T.A.S.K. Maps, FoxtrotGPS (fallback)" |

An `available` manifest needs `exec` or (system manifests only) `builtin`.

**Executable checks** (`registry/execcheck.py`): the path must exist, be a regular file and be
executable by the user. The file must not be world-writable, and no directory on its real path
may be world-writable (so `/tmp` is refused).

- A missing executable makes the tile **Unavailable**.
- An unsafe executable makes it **Error**.

**Start failures** (0.2.0): when a started app exits with a non-zero code within 8 seconds,
the tile goes to **Error** with "exited with code N X.X s after start: <last line of its output>", and the
last lines of its log are shown in the error sheet and in App Manager.

## `[[actions]]` (0.2.0)

Extra commands offered in the tile's context menu (right-click or long-press), e.g. `gpsmon` next
to Maps. At most 8.

| Key | Type | Rule |
|---|---|---|
| `id` | string | `^[a-z][a-z0-9-]{0,31}$`, unique in the manifest |
| `label` | string | 1–40 characters |
| `exec` | array of strings | argv; absolute program path; same executable checks as `[launch]` |
| `terminal` | bool | default `false`. `true` runs the argv inside the first installed terminal emulator (the same list as desktop `Terminal=true` apps); if none is installed the action is disabled with that reason |

An action whose program is missing is shown disabled with the reason. Actions use the same
process manager as tiles (no second launch path, no shell).

## `[requires]`

| Key | Type | Meaning |
|---|---|---|
| `core_min_version` | string | If rain-core reports an older version, the tile is Unavailable ("requires rain-core X"). Not checked while Core is unreachable |
| `core_capabilities` | array of strings | Shown in App Manager with the live status from `capability.list` (informational in 0.1.0) |
| `hardware` | array of strings | Informational (shown in App Manager). The launcher never touches hardware |
| `debian` | array of strings | Informational: the packages the app needs. The launcher never installs anything |

## Example

```toml
manifest_version = 1
id = "org.example.notes"
name = "Field Notes"
version = "1.2.0"
description = "Offline notes."
icon = "book-open"
order = 500
min_role = "operator"

[launch]
exec = ["/usr/bin/field-notes", "--offline"]
on_reactivate = "notify"

[requires]
core_min_version = "0.2.0"
debian = ["field-notes"]
```

## The 12 shipped manifests

The 12 manifests are `data/apps.d/010-mesh.toml` … `120-app-manager.toml`, in the approved order
(ids and order unchanged since 0.1.0):

| Tile | 0.2.0 manifest |
|---|---|
| Mesh Network | exec `/usr/bin/rain-mesh`, alternative `/usr/local/bin/rain-mesh`; readiness `mesh` |
| Maps & GPS | exec `/usr/bin/task-maps` (native, Phase 4B), alternative `/usr/bin/foxtrotgps` labelled "FoxtrotGPS (fallback)"; actions `gpsmon`, `cgps` (terminal); readiness `gps` |
| Radio / APRS | builtin `radio` (receive-only status + monitor window); readiness `direwolf` |
| SDR | exec `/usr/bin/sdrpp`, alternative `/usr/local/bin/gqrx`; action "Open Gqrx instead"; readiness `rtl-sdr` |
| Library | builtin `library` (native Kiwix viewer); readiness `kiwix` |
| Mission Planner | still `status = "planned"` (see docs/MISSION-PLANNER-INTERFACE.md) |
| Medical | builtin `medical` (offline reference finder); readiness `medical` |
| Weather | builtin `weather` (local tools and data status, no forecast); readiness `weather` |

- Mission Planner's `version = "0.0.0"` only satisfies the schema; App Manager shows "—" as the
  version of planned apps.
- Devices is the `devices` builtin with exec `/usr/local/bin/rain-console`, alternative
  `/usr/bin/rain-console`, `on_reactivate = "relaunch"` and `core_min_version = "0.2.0"`.
- Files is the `files` builtin.
- System is the `system` builtin.
- App Manager is the `app-manager` builtin. It cannot be disabled or hidden.

## Desktop applications (not manifests)

Tiles for installed XDG desktop applications are a separate source type, `desktop`. They are
stored by desktop-file ID in `~/.config/task-launcher/tiles.json`; no manifest is written for
them. See ARCHITECTURE.md §6.
