# task-console

T.A.S.K. Console 0.1.0: the native desktop client of task-core (PySide6 / Qt Widgets, PHASE-2.md r3).

- Talks **only** to task-core over `/run/task/core.sock` (protocol v2). It never opens `/dev`, `/sys`, udev, serial ports, or task-core's state files; task-core stays the sole hardware authority.
- Runs as the desktop user, never as root. It is started manually from the application menu (**T.A.S.K. Console**) or with `task-console`. There is no autostart, kiosk mode, or session change; F11 toggles fullscreen.
- Signed out it is public (counts and states only). Sign in with a task-core account (`task-core-admin user add …`); the session token is kept in memory only. Ctrl+L locks immediately and revokes the session.
- Preferences: `~/.config/task-console/console.toml` (scale 1.0/1.25/1.5, idle lock minutes 1–10, last panel). Log: `~/.local/state/task-console/console.log` when not started from a terminal. No secrets are written.

Install on the Pi (Debian 13 trixie): `sudo bash deploy/install-console.sh` (apt: python3-pyside6.qtcore, qtgui, qtwidgets, qtnetwork, qt6-wayland; then the wheel with `--no-deps`). Remove: `sudo bash deploy/uninstall-console.sh`. Socket access needs membership in the `task-core` group (`sudo usermod -aG task-core <user>`, an explicit, separate step).

Tests: `QT_QPA_PLATFORM=offscreen python3 -m pytest` (needs python3-pytestqt and python3-pyside6.qttest), or `../run_tests_debian.sh`.

## License

T.A.S.K. task-console
Copyright (C) 2026 Joshua Sturtz

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program (`LICENSE`). If not, see <https://www.gnu.org/licenses/>.
