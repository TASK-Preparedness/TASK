<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# task-launcher 0.2.0 (R.A.I.N. Phase 4A)

A native PySide6 launcher for the R.A.I.N. platform (future product name T.A.S.K., Tactical Access
Support Kit). It is a client of rain-core 0.2.x and never touches hardware itself.

**New in 0.2.0 (Phase 4A):** Mesh, Maps & GPS and SDR launch the real installed apps (rain-mesh;
FoxtrotGPS as a labelled *fallback* until task-maps exists; SDR++ or Gqrx), with a second
"readiness" line on the tile from background probes (rain-core device list, gpsd, Kiwix,
Direwolf). Library, Radio / APRS (receive-only), Medical and Weather open native windows. Mission
Planner stays Planned. See ARCHITECTURE.md §9 and `docs/`.

- **Home screen as approved:**
  - dark theme, "R.A.I.N." / "Remote Access Information Network";
  - top right: auth chip, network pill and settings;
  - 3×4 tiles: Mesh Network, Maps & GPS, Radio / APRS, SDR, Library, Mission Planner, Medical,
    Weather, Devices, Files, System, App Manager;
  - footer: the real rain-core link state and version, internet state and "Offline-first".
- **Honest statuses:**
  - Available (with the variant, e.g. "Available — FoxtrotGPS (fallback)"), Planned,
    Unavailable (with the reason), Disabled, Running, Error (including "exited with code N
    X.X s after start" and the last output lines);
  - a readiness line separates "installed" from "hardware/service ready";
  - unknown values show "—";
  - Mission Planner is Planned and only opens an information sheet.
- **Your own tiles:** App Manager → Add Application lists the installed desktop applications
  (XDG `.desktop`, including flatpak exports) with their real icons. Adding, renaming, re-iconing,
  reordering and removing tiles only changes `~/.config/task-launcher/tiles.json`; nothing is
  installed, uninstalled or edited.
- **Horizontal pages:**
  - page 1 holds the 12 built-ins and added tiles go on page 2+;
  - swipe/drag with snap and spring-back, arrow buttons, dots, keyboard and wheel;
  - 300 ms OutCubic animation, or a short fade with reduced motion.
- **rain-core link:**
  - reconnects with backoff;
  - works fully while Core is down;
  - sign-in as operator or administrator (the password is never stored);
  - in-window idle lock.
- **Integrations:**
  - Devices opens rain-console if installed, otherwise a read-only overview;
  - System is a native read-only window;
  - Files opens the file manager;
  - App Manager.
- **Settings:** branding (R.A.I.N. / T.A.S.K. / custom), layout and scale, start mode, page
  animation, idle lock, optional autostart (off by default).

It is an ordinary window under labwc. There is no kiosk mode and no session replacement, and it
never runs as root.

## Run from the source tree

```sh
python3 -m task_launcher --windowed             # needs python3-pyside6.{qtcore,qtgui,qtwidgets,qtnetwork,qtsvg,qtdbus}
python3 -m task_launcher --socket /run/rain/core.sock --fullscreen
```

Keys:

| Key | Action |
|---|---|
| F11 | Toggle fullscreen |
| Esc | Leave fullscreen |
| Ctrl+L | Lock |
| Ctrl+Shift+S | Sign in |
| Ctrl+, | Settings |
| F5 | Reconnect and rescan |
| Arrows / PageUp / PageDown / Home / End | Navigate |
| Alt+arrows | Move the focused tile |
| Menu key or Shift+F10 | Tile menu |
| Delete | Remove the focused tile |

## Tests

```sh
QT_QPA_PLATFORM=offscreen dbus-run-session -- python3 -m pytest launcher/tests
```

The tests use a real rain-core server from `tests/p2fixtures.py`.

## Documents

- `INSTALL.md` — Debian package install, uninstall and rollback on the Pi.
- `ARCHITECTURE.md` — the design, with file:line references to the rain-core methods used.
- `MANIFEST-SPEC.md` — app manifest schema v1 (platform 0.2.0 additions).
- `docs/PHASE4A-INTEGRATIONS.md` — what each integration verified, assumed, and its conflicts.
- `docs/MISSION-PLANNER-INTERFACE.md` — waypoint store (GPX) and local IPC contract (design).
- `docs/MODULE-API.md` — module API design note (embedded panels, pop-outs, shared services).
- `docs/WEATHER-SOURCES.md` — weather data-source interface.

Licence: GPL-3.0-or-later. Lucide icons: ISC/MIT (see `task_launcher/data/icons/lucide/LICENSE`).
