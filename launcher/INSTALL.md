<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Installing / upgrading task-launcher 0.2.0 on the Pi

Target: Raspberry Pi 5, Debian 13 trixie arm64, labwc, rain-core 0.2.1 installed and running.
rain-console 0.1.0 is optional. task-launcher 0.1.0 may already be installed (upgrade: §1a).

> Everything below is **UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST**. The package was built
> and tested on an amd64 build box only (see TEST-REPORT.md).

## 1a. Upgrade from 0.1.0 (offline, as `dragon`)

0.2.0 has exactly the same Depends and Recommends as 0.1.0, so the upgrade needs no network and
no other package:

```sh
sha256sum -c SHA256SUMS --ignore-missing
sudo dpkg -i task-launcher_0.2.0_all.deb          # replaces the 0.1.0 files under /usr only
dpkg -s task-launcher | grep -E 'Status|Version'  # Version: 0.2.0
```

- No maintainer scripts run; nothing in `/etc` is shipped (no conffiles), so there is no prompt.
- **User configuration is kept as is.** `~/.config/task-launcher/settings.json` and `tiles.json`
  (schema 1) are read unchanged by 0.2.0 and are *not rewritten* on start; custom desktop tiles,
  order, hidden tiles and enable/disable overrides carry over. The tile ids and order of the 12
  built-ins are unchanged. 0.2.0 adds one optional file it never creates:
  `~/.config/task-launcher/reference.toml` (see docs/WEATHER-SOURCES.md).
- Restart the launcher (close it, start it from the menu) to load the new version.

## 1b. Rollback to 0.1.0 (offline)

```sh
sudo dpkg -i task-launcher_0.1.0_all.deb          # sha256 bc70b0f754288e7ed36da837dfea8eee2f2885dc8594d553c5ed7fc1f0fb1b78
```

dpkg accepts the downgrade with a warning. 0.1.0 reads the same settings/tiles files (0.2.0 adds
no keys to them). A per-user `reference.toml` is ignored by 0.1.0.

## 1. Fresh install (as `dragon`, the admin account)

```sh
sha256sum -c SHA256SUMS --ignore-missing         # in the folder with the .deb
sudo apt install ./task-launcher_0.2.0_all.deb    # apt pulls the python3-pyside6.* modules from trixie
dpkg -s task-launcher | grep -E 'Status|Version'
```

- The package has **no maintainer scripts**. It only adds files under `/usr` (list them with
  `dpkg -L task-launcher`). It does not touch rain-core, rain-console, labwc, the session or
  autostart.
- **Dependencies:** python3 (>= 3.13), python3-pyside6.qtcore / qtgui / qtwidgets / qtnetwork /
  qtsvg / qtdbus (>= 6.8).
- **Recommends:** fonts-inter, qt6-wayland, qt6-svg-plugins, xdg-utils. Apt installs recommends
  by default. Without fonts-inter the launcher uses Noto Sans or DejaVu Sans.
- **Offline Pi:** download the dependency .debs on a connected trixie arm64 machine with
  `apt-get download` and install them together:
  `sudo apt install ./task-launcher_0.2.0_all.deb ./python3-pyside6.qtsvg_*.deb …`

## 2. Allow sign-in from the operator's desktop account (only if not already done in Phase 2)

rain-core accepts `session.login` only from uids listed in `/etc/rain/sessions.toml` `[clients]`.
Without that, sign-in shows "rain-core does not allow sign-in from this desktop account". Public
use works without it.

```sh
id -u op                       # e.g. 1001
sudoedit /etc/rain/sessions.toml
# [clients]
# 1001 = "op desktop (rain-console / task-launcher)"
```

rain-core re-reads the file on the next login attempt.

## 3. Start (as `op`, the operator account, in the labwc session)

- From the menu: "R.A.I.N. Launcher", or run `task-launcher` in a terminal.
- `task-launcher --fullscreen` starts fullscreen; F11 toggles and Esc leaves fullscreen.
- Optional autostart: Settings → "Start when I log in". This writes
  `~/.config/autostart/task-launcher.desktop` for this user only. Untick it to remove the file.

## 4. Uninstall and roll back

```sh
sudo apt remove task-launcher                 # removes /usr files only
rm -rf ~/.config/task-launcher ~/.local/state/task-launcher           # optional: per-user settings and logs
rm -f ~/.config/autostart/task-launcher.desktop                       # only if you enabled autostart
```

rain-core, rain-console, the accounts and `/etc/rain` are not affected by install or removal.

## 5. Optional programs the tiles use (never installed by the launcher)

| Tile | Program (path checked) | Debian package |
|---|---|---|
| Mesh Network | `/usr/bin/rain-mesh` or `/usr/local/bin/rain-mesh` | rain-mesh (project package) |
| Maps & GPS | `/usr/bin/task-maps` (Phase 4B), else `/usr/bin/foxtrotgps`; actions `/usr/bin/gpsmon`, `/usr/bin/cgps` + a terminal emulator | foxtrotgps, gpsd-clients |
| SDR | `/usr/bin/sdrpp`, `/usr/local/bin/gqrx` | (SDR++ build), gqrx (local build) |
| Library | a running kiwix-serve (IIAB or the `kiwix-tools` package) | kiwix-tools / IIAB |
| Radio / APRS | a running, operator-configured Direwolf with KISS TCP | direwolf |

## 6. Where things are

| Path | What |
|---|---|
| `/usr/bin/task-launcher` | command |
| `/usr/share/task-launcher/task_launcher/` | Python modules |
| `/usr/share/task-launcher/apps.d/` | the 12 shipped manifests |
| `/etc/task-launcher/apps.d/` | (optional) administrator manifests |
| `/etc/task-launcher/branding.toml` | (optional) system default branding; example in `/usr/share/doc/task-launcher/examples/` |
| `~/.config/task-launcher/settings.json`, `tiles.json` | per-user settings and tiles |
| `~/.config/task-launcher/reference.toml` | (optional, 0.2.0) medical / weather folders; read only |
| `/usr/share/doc/task-launcher/` | README, MANIFEST-SPEC, docs (integrations, module API, mission planner interface, weather sources) |
| `~/.local/state/task-launcher/launcher.log`, `logs/` | logs (no passwords or tokens) |
