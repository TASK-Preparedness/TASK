<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# task-launcher 0.2.0 — architecture

The package is `task_launcher` in `launcher/` on branch `phase3`, off `phase2-fix-h1` (`ee5e4c6`,
rain-core 0.2.1). Product name: R.A.I.N. (technical name). The branding can be switched to
T.A.S.K. in Settings or `/etc/task-launcher/branding.toml` without code changes.

## 1. Boundaries (non-negotiable)

- **rain-core is the only hardware authority.** The launcher talks to `/run/rain/core.sock`
  (protocol v2) and never opens device nodes. A source test (`tests/test_app_entry.py`) fails if
  hardware or package-manager paths appear.
- **An ordinary desktop window.** There is no kiosk mode, no frameless window, and nothing
  replaces labwc, the session or the login manager.
  - Maximized or fullscreen are start-mode choices; F11 toggles fullscreen and Esc leaves it.
  - Autostart is optional, off by default, per user, and only written to
    `~/.config/autostart/task-launcher.desktop` with a marker key. A foreign file with that name
    is never overwritten or deleted (`autostart.py:51`).
- **Never root.** `app.main` refuses uid 0 before importing Qt (`app.py:130`). The launcher never
  elevates privileges, never installs or uninstalls packages, and never edits `.desktop` files.
- **No external network contact.** The only sockets are the rain-core UNIX socket and the
  per-user single-instance `QLocalServer`.
  - Network status is read from NetworkManager over the system D-Bus (read-only
    `Properties.Get`), with `/sys/class/net` as the fallback.
  - The test suite fails on any AF_INET/AF_INET6 connect or name lookup (`tests/conftest.py`).
- **Secrets.** Passwords are read once, cleared from the field before the request is sent, and
  never stored or logged. The session token exists only in `CoreClient` memory and is revoked
  once on sign-out, lock and exit.

## 2. Verified rain-core interfaces used (file:line in this tree)

Envelope `{v, id, method, params, session}` (`rain_core/protocol_v2.py:18`). Method → minimum
role table: `rain_core/protocol_v2.py:20-36`. Dispatch: `rain_core/protocol_v2.py:103-134`.

| Method | Role | Server side | Launcher use |
|---|---|---|---|
| `core.protocol` | public | `protocol_v2.py:103-104` → `{versions:[1,2], core, boot_id}` | First call of every connection attempt (`core/link.py:156`). A reply with `v == 1` or "unsupported version" means a 0.1.x core → "too old" (`core/link.py:189-191`). A changed `boot_id` drops the session (`core/link.py:198-204`) |
| `core.health` | public | `protocol_v2.py:108-110` (v2 adds `hotplug`); base result `main.py:196-205` `{ok, version, uid, uptime_seconds}` | Footer version (real value, never hard-coded) and System window; refreshed every 30 s (`core/link.py:234,240`) |
| `device.counts` | public | `protocol_v2.py:113-114` → `devices.py:249-254` `{total, connected, disconnected}` | Devices window (public view) (`core/link.py:235`) |
| `capability.list` | public | `protocol_v2.py:111-112` → `capabilities.py:68-74` `{capabilities:[{name, kind, status}]}` | App Manager requirement status (`core/link.py:236,292`) |
| `device.list` | operator | `protocol_v2.py:111-112` → records `devices.py:91-108` | Read-only device table after sign-in (`core/link.py:278`) |
| `events.subscribe` | public | `protocol_v2.py:123-124`, `_subscribe` `protocol_v2.py:171-180`; heartbeat 10 s and `session-ended` in `stream.py:23,75` | Topics `core.`, `capability.`, `device.counts` (`core/link.py:282`) |
| `session.login` | public | `protocol_v2.py:125-126` → `sessions.py:160-171`: allowed only for uids in `/etc/rain/sessions.toml [clients]` (`sessions.py:107-108`); otherwise forbidden "session.login not allowed for this client" (`sessions.py:165`); rate limited (`sessions.py:170-171`) | Sign-in dialog (`core/link.py:349`) |
| `session.logout` | public | `protocol_v2.py:127-130` → `sessions.py:199` | Sign out, lock and exit, one attempt each (`core/link.py:130,332,363`) |

Not used: `module.list`, `device.get`, `device.assign`/`unassign` (administrator, state-changing),
`events.recent`, `events.since`, `session.whoami`.

Limits honoured by the client: request 65536 B and response 262144 B (`api.py:17-18`), 8 clients
(`api.py:19`), 30 s RPC idle timeout (`api.py:20`) and 4 streams (`stream.py:21`).

Session defaults (server): 2 h idle, 12 h absolute (`sessions.py:23-24`). The launcher adds the
Phase 2 in-window idle lock (1–10 min, default 10) on top.

The client (`core/client.py`) is a copy of `console/rain_console/core_client.py`, with
attribution. rain-console is pip-installed under `/usr/local` and is not a Debian dependency, so
the launcher cannot import it.

## 3. Module map

| Module | Role |
|---|---|
| `app.py` | Root refusal, CLI (`--socket`, `--maximized`/`--windowed`/`--fullscreen`, `--version`), logging to `~/.local/state/task-launcher/launcher.log` (0600), single instance (`QLocalServer`; a second start raises the first window) |
| `core/client.py`, `core/link.py` | Async UNIX-socket client; link state machine `connecting → connected / offline / no-access / too-old / lost`; reconnect backoff 0.5, 1, 2, 4, 8 s then every 10 s, ±20 % jitter (`core/link.py:33`) |
| `registry/manifest.py`, `discovery.py`, `execcheck.py` | Manifest schema v1 (MANIFEST-SPEC.md) |
| `registry/desktop.py` | XDG desktop-entry discovery, visibility rules, Exec parsing, launch plans (§6) |
| `registry/tilestore.py` | `~/.config/task-launcher/tiles.json` (schema 1): order, hidden, custom desktop tiles (name and icon overrides), enable overrides |
| `registry/registry.py` | Builds the tile list with source `builtin` / `manifest` / `desktop` and static status (Available, Planned, Unavailable + reason, Disabled, Error) (`registry/registry.py:99`) |
| `launch.py` | `ProcessManager`: `Popen(argv, shell=False, start_new_session=True, close_fds=True, stdin=DEVNULL)`, per-app log 0600 rotated at 1 MiB, polled by a QTimer (no threads). Apps keep running when the launcher exits |
| `ui/home.py`, `ui/pager.py`, `ui/widgets.py` | Home screen, horizontal paging (§7), tiles and chips |
| `ui/main_window.py` | Wires everything together, activation rules, customisation actions, sign-in and lock, shortcuts, shutdown |
| `ui/system_window.py`, `sysinfo.py` | Native read-only System window (from `/proc`, `/sys`, `os-release`, `statvfs`; calculated values are labelled) |
| `ui/devices_window.py` | Read-only fallback when rain-console is not installed: public sees counts; operator and above see `device.list` |
| `ui/app_manager.py` | App Manager, Add Application, icon dialog. Install / Update / Uninstall are disabled ("Not available in Phase 3") |
| `ui/dialogs.py` | Sign-in, info sheet, Settings |
| `netstatus.py` | NetworkManager `State` / `Connectivity` / `PrimaryConnectionType` / `ConnectivityCheckEnabled` via `Properties.Get` (`netstatus.py:98`); sysfs fallback for physical interfaces (`netstatus.py:64`). "Internet: unknown" when connectivity checking is off or NetworkManager is unreachable |
| `motion.py` | Reduced-motion hint: GTK `settings.ini` `gtk-enable-animations`, then `gsettings` (only if `/usr/bin/gsettings` exists; 2 s timeout, argv) |
| `settings.py`, `atomic.py`, `branding.py`, `autostart.py`, `paths.py` | `settings.json` schema 1, atomic writes (mkstemp → fsync → `os.replace` → fsync dir, 0600) (`atomic.py:11`), presets |
| `layout.py`, `theme.py`, `fonts.py`, `icons.py`, `ui/iconcache.py` | Layout tables from the platform spec, colour tokens with contrast checks, Inter font (falls back to Noto Sans / DejaVu Sans), Lucide SVGs, theme icons |
| `workers.py` | `PollWorker(QThread)` for blocking reads (network status, motion hint, desktop scan, system info), joined on shutdown |

## 4. Status model

- **Static status** (from the registry):
  - **Available** — the executable or builtin is present and safe. The state line names the
    variant or window when that matters: "Available — FoxtrotGPS (fallback)", "Available —
    SDR++", "Available — receive-only monitor". (0.1.0 called this state "Installed".)
  - **Planned** — no app exists yet; opens an info sheet only.
  - **Unavailable** — always with the reason, e.g. "rain-console not installed", "requires
    rain-core 0.2.0" or "application is no longer installed".
  - **Disabled** — per user.
  - **Error** — unsafe executable or invalid entry.
- **Runtime status** (overlay): **Running** while the launched process lives; **Error — exited
  with code N / killed by SIGx** after a failure. App Manager has "Clear error".
- **Early failure** (0.2.0): a non-zero exit within 8 s of the start is reported as "Error —
  exited with code N X.X s after start: <last output line>"; the error sheet shows the tail.
- **Role gate:** "Sign in to use" for `min_role` above the current role.
- **Readiness line** (0.2.0): a second, smaller line under the state, from a background probe
  (§9). It separates "installed" from "service/hardware ready": e.g. SDR "Available — SDR++" with
  "RTL-SDR 0bda:2838 connected (rain-core)" or "RTL-SDR not reported by rain-core". It is display
  only: it never changes the status and never blocks a launch.

A tile existing never means Available.

## 5. Integrations

- **Devices:**
  - If `/usr/local/bin/rain-console` (or `/usr/bin/rain-console`) passes the executable checks,
    it is launched (verified CLI: only `--socket` and `--version`, `console/rain_console/app.py:117-118`).
  - A second activation re-runs it, and rain-console raises its existing window
    (`console/rain_console/app.py:133-136`).
  - Otherwise the tile is Unavailable ("rain-console not installed") and opens the native
    read-only Devices window.
- **Files:** `/usr/bin/xdg-open ~`. If that fails, or xdg-open is missing, the first of pcmanfm,
  pcmanfm-qt, thunar, nautilus, nemo, caja or dolphin is used.
- **System:** native window, polled every 2 s only while shown.
- **App Manager:** a table of every tile with details, Launch, Enable/Disable, show/remove on the
  dashboard, Clear error, Move earlier/later, Rename, Change icon, Add Application, Rescan and
  Reset layout. It also lists manifest problems.

## 6. Desktop applications (STEERING 1)

- **Discovery** (`registry/desktop.py:385`):
  - Directories are `$XDG_DATA_HOME/applications`, then each `$XDG_DATA_DIRS/applications`
    (default `/usr/local/share:/usr/share`), then `~/.local/share/flatpak/exports/share` and
    `/var/lib/flatpak/exports/share` if present.
  - Desktop-file ID = path below `applications/` with `/` → `-`. The first directory wins, so a
    user file overrides a system one; lower copies are recorded as shadowed.
  - `Hidden=true` deletes the ID, including lower copies.
- **Offered in "Add Application"** (`registry/desktop.py:360`):
  - Only `Type=Application`, with a Name and an Exec (or DBusActivatable).
  - Not `NoDisplay`.
  - `OnlyShowIn`/`NotShowIn` are checked against the colon-separated `XDG_CURRENT_DESKTOP`
    (labwc sets e.g. `labwc:wlroots`).
  - A `TryExec` that is set must be installed.
  - Administrative entries are hidden by default: the Exec program is pkexec / gksu / sudo / su /
    kdesu / doas / run0 …, or the entry has `X-KDE-SubstituteUID` and similar keys. They can be
    shown with a checkbox and are labelled; the launcher still never elevates.
  - The list is searchable (name, generic name, comment, keywords, ID) and shows real icons.
- **Exec** (`registry/desktop.py:148`):
  - Parsed per the Desktop Entry Specification: string unescape, then quoting with the
    reserved-character rule (unquoted `;|&$*?#()`… are errors), then field codes.
  - `%f %F %u %U` are removed (no files passed); `%i` → `--icon <Icon>`, `%c` → Name,
    `%k` → file path, `%%` → `%`; deprecated codes are removed; unknown codes are errors.
  - The result is an argv list. **Never a shell.**
- **Launch plan** (`registry/desktop.py:438`):
  - The program is resolved on `PATH` (absolute entries only), then the executable checks run.
  - `Path=` must exist and becomes the working directory.
  - `Terminal=true` uses the first available terminal: x-terminal-emulator `-e`, lxterminal `-e`,
    foot, xfce4-terminal `-x`, gnome-terminal `--`, konsole `-e`, alacritty `-e`, kitty,
    xterm `-e`.
  - `DBusActivatable=true` without Exec goes through `gio launch <file>` only if `/usr/bin/gio`
    exists; otherwise the tile is Unavailable.
  - **Deviation from the steering text:** the steering asked for gio/gtk-launch first and the own
    parser as fallback. The own parser is primary because it yields an argv the launcher can
    track (Running / Error, logs, single instance). gio is absent on the build box, so its
    behaviour could not be verified. Reversing the order is a small change in `plan_launch`.
- **Tiles:**
  - Adding stores only the desktop-file ID plus the app's name at that time in `tiles.json`.
    Rename and icon override are launcher-side.
  - Removing forgets the tile; the application stays installed.
  - If the desktop file disappears, the tile shows Unavailable ("application is no longer
    installed") with a Remove button.
- **Icons** (`ui/iconcache.py:35`): `QIcon.fromTheme`, then a manual hicolor/pixmaps search, then
  validated absolute files (png/svg/xpm, ≤ 2 MiB, SVG without script or external references),
  then the Lucide fallback. Name and Comment are localized.
- **Rescan:** the Rescan button, F5, or a `QFileSystemWatcher` on the application directories
  debounced by 1500 ms (`ui/main_window.py:30`). The scan runs in a worker thread.

## 7. Horizontal paging (STEERING 2)

- **Pages** (`ui/home.py:329`):
  - Tiles keep the size of the approved 12-tile page. Page capacity is cols × the rows that fit,
    recomputed on every resize.
  - With the 12 defaults, page 1 is exactly the built-ins; added tiles start on page 2.
  - The page bar (‹ dots ›) appears only when there is more than one page.
- **Strip:** all pages sit side by side in one `Strip` widget inside the clipping `PagedGrid`.
  Only `strip.pos` changes; header, footer and page bar are not part of it.
- **Animation:** `QPropertyAnimation(strip, "pos")` in a `QParallelAnimationGroup`,
  `OutCubic`, 300 ms (`ui/pager.py:30`). A new target retargets from the current position, and
  grabbing mid-animation stops it where it is.
- **Gestures** (`ui/pager.py:161,194`):
  - The strip follows the pointer after a 12 px horizontal threshold. Below that it is a click;
    more vertical than horizontal is not a drag.
  - On release it snaps if the drag is ≥ 25 % of the page width, or the velocity is ≥ 800 px/s
    in the drag direction with at least 24 px moved; otherwise it springs back.
  - One page per gesture (hard stop at the adjacent page). Rubber band (0.35) beyond the
    first/last page.
  - A drag never activates a tile, and neither does a tap that stopped a moving page.
  - Touch uses `QTouchEvent` (a tap activates the tile). The horizontal wheel or Shift+wheel
    pages in 120-unit steps.
- **Keyboard** (`ui/home.py:401`): arrows move within a page; at the grid edge Left/Right go to
  the adjacent page (same row); PageUp/PageDown and Ctrl+Left/Right change page; Home/End go to
  the first/last tile. Focus moves to the new page; focusing a tile on another page (e.g. Tab)
  animates there.
- **Accessibility:**
  - The dots are focusable buttons named "Page i of n (current)".
  - Alt+arrows (or the tile menu: Menu key or Shift+F10) move a tile, also across pages; focus
    follows the tile.
  - The focus ring is shown once the keyboard is used and hidden after a mouse or touch press.
- **Reduced motion:** Settings → Page animation: "Follow the desktop setting" (GTK/gsettings
  hint), "Reduce motion" or "Always animate". Reduced means no slide: the strip jumps and the grid fades
  in over 120 ms.
- **Resize:** any running animation is finished and the strip re-aligned; the current page is
  clamped.
- **Performance:**
  - No relayout and no tile geometry change per frame (tested), and no SVG parsing per frame
    (pixmap cache keyed by spec, size, colour and DPR).
  - Frame times are recorded from `valueChanged`. Offscreen on the build box: 19 frames in
    300 ms, median 16.0 ms, max 25.7 ms.
  - Pi 5 / labwc frame rate: **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**.

## 8. Settings and files

| File | Content |
|---|---|
| `~/.config/task-launcher/settings.json` | schema 1: branding (default / rain / task / custom + title/subtitle), layout (auto=Large / large / standard / compact), scale (1.0 / 1.25 / 1.5), start mode, show planned, idle lock 1–10 min, page animation |
| `~/.config/task-launcher/tiles.json` | schema 1: order, hidden, custom [{desktop_id, name, icon, label}], enabled overrides |
| `~/.config/autostart/task-launcher.desktop` | only if the user ticks "Start when I log in" |
| `~/.local/state/task-launcher/launcher.log`, `logs/<tile>.log` | launcher log (no secrets) and per-app stdout/stderr, 0600 |
| `/etc/task-launcher/branding.toml` | optional system default branding |

Corrupt or unknown-schema files fall back to defaults; the problem is shown and nothing crashes.

## 9. Phase 4A services and native windows (0.2.0)

All new code extends the existing registry, manifest parser and `ProcessManager`; there is no
second launch framework. Native windows are built-ins (`[launch] builtin = …`) and open through
the same `activate()` path as System / Devices.

| Module | Role |
|---|---|
| `services/probe.py` | Shared read-only helpers: loopback-only TCP connect (`tcp_reachable`, connect then close, no bytes sent), loopback-only HTTP GET (no redirects off the endpoint, size cap, short timeout), `run_readonly` (absolute argv, `LC_ALL=C`, timeout, no shell), `systemctl list-units`/`show` (read only), `/proc/*/cmdline` scan, file-age text |
| `services/readiness.py` | The readiness probes (`gps`, `rtl-sdr`, `mesh`, `kiwix`, `direwolf`, `weather`, `medical`). `collect_all()` runs in the `readiness-probes` `PollWorker` thread every 30 s (and on demand); results reach the UI by signal. The GUI thread never blocks on a probe |
| `services/kiwix.py` | Kiwix endpoint discovery, OPDS / library.xml / search parsing, page fetch for the viewer |
| `services/aprs.py` | KISS de-framing, AX.25 UI decoding, APRS parsing; `ReceiveOnlySocket` |
| `services/direwolf.py` | Direwolf install / process / unit / config / port status (read only) |
| `services/mesh.py` | rain-mesh install detection (dpkg status file, candidates), USB serial listing |
| `services/weather.py`, `services/medical.py`, `services/reference.py` | Honest local-data status; optional `~/.config/task-launcher/reference.toml` (read, never created) |
| `ui/native_windows.py` | Library, Radio / APRS, Weather, Medical windows. Background work in `QThread`s that are stopped when the window closes |

### 9.1 Tiles

| Tile | Behaviour |
|---|---|
| Mesh Network | Launches `rain-mesh` if installed. Otherwise Unavailable "not installed: rain-mesh" and the sheet shows a labelled **temporary read-only status** (Core mesh capability, USB serial devices, whether the `meshtastic` CLI exists — which alone does not count). |
| Maps & GPS | `task-maps` (Phase 4B) when present, else FoxtrotGPS: "Available — FoxtrotGPS (fallback)". Context menu: gpsmon / cgps in a terminal. FoxtrotGPS reads gpsd directly; it is not a rain-core client |
| Radio / APRS | Native status + **receive-only** monitor window |
| SDR | SDR++ or Gqrx; readiness from Core `device.list` (RTL-SDR 0bda:2838) |
| Library | Native Kiwix viewer; falls back to the system browser (documented) |
| Mission Planner | Planned. Interface in `docs/MISSION-PLANNER-INTERFACE.md` |
| Medical | Offline reference finder; no records, no clinical claims |
| Weather | Local tools and data with their age; never a forecast |

### 9.2 Hardware ownership and conflicts

rain-core stays the only component that **discovers and assigns** devices (udev enumeration,
`/var/lib/rain/devices.json`); the launcher only reads `device.counts`, `device.list` (operator)
and `capability.list`, and never calls `device.assign`. rain-core does **not** open tty or USB
nodes itself (`rain_core/enumerator.py` uses udev metadata only), so it never holds the RTL-SDR or
the Heltec serial port open.

- **SDR:** SDR++ and Gqrx open the RTL-SDR through librtlsdr directly — the data stream bypasses
  rain-core. Only one program can hold the dongle. The SDR readiness line reports "in use by …"
  when another SDR program (sdrpp, gqrx, rtl_fm, rtl_tcp, rtl_433, dump1090) is visible in
  `/proc`. If a future rain-core opens the device itself (e.g. an `radio.rx` provider), that is a
  conflict and must be flagged by the same check; today Core reports `no-provider` for
  `radio.rx`, so no provider holds it.
- **Mesh:** rain-mesh opens the Heltec serial port through the Meshtastic `SerialInterface`
  (exclusive). It does not use rain-core. The `meshtastic` CLI, a second rain-mesh, or any other
  serial client conflicts with it. The mesh readiness line says "meshtastic CLI running — serial
port conflict" when a `meshtastic` CLI process is visible in `/proc`. rain-mesh is not single-instance itself, so the launcher's
  `single_instance` is the only guard against a second copy launched from the launcher.
- **GPS:** FoxtrotGPS, gpsmon and cgps read gpsd (127.0.0.1:2947) directly, not rain-core.
- **Direwolf:** owns the sound card / PTT. The launcher never starts it and only connects to its
  KISS port to **receive**.

### 9.3 Radio safety

`ReceiveOnlySocket` wraps a connected TCP socket and exposes only `recv`, `settimeout` and
`close` — there is no send method, and the monitor never writes a byte (not even a KISS
command). The write half is deliberately *not* shut down, because Direwolf drops a KISS client
whose connection is half-closed. Tests replace the socket with a recorder and assert that nothing was written. Direwolf
is never launched with guessed settings; the window only shows its config (ADEVICE, PTT, MYCALL,
ports; IGLOGIN passcodes are masked).

### 9.4 Network

Every probe is loopback-only (`ensure_loopback` refuses other hosts) with network timeouts ≤ 1.5 s (local read-only commands such as `systemctl show`: ≤ 3 s), and
the Library viewer refuses to load any resource that is not on the discovered loopback endpoint
(no remote images, scripts or iframes). "Open in browser" passes only loopback URLs or local file
paths to `xdg-open`.
