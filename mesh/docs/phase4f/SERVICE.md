<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# task-mesh-service (optional background receiver)

* Installed as a **systemd user unit** `/usr/lib/systemd/user/task-mesh-service.service`, **disabled**. The package
  never enables or starts it (no preset, no postinst systemctl). Enable it yourself:
  `systemctl --user enable --now task-mesh-service`, or use Network Status → "Run in background" in the app (asks first).
* Runs as you, never root (refuses euid 0). Single instance (`$XDG_RUNTIME_DIR/task/mesh-service.lock`).
* Owns only radios you assigned in Devices (stored in `~/.config/task-mesh/radio-protocols.json`, 0600). Per-port
  lock `$XDG_RUNTIME_DIR/task/mesh-devices/<tty>.lock`; a port locked by the window (or anything else) is shown "busy" and
  retried, never opened. Backoff 2/5/10/30/60 s.
* IPC: `$XDG_RUNTIME_DIR/task/mesh.sock`, mode 0600, peer uid checked (SO_PEERCRED), JSON lines.
* Data: `~/.local/share/task-mesh/hub.sqlite3` (0600). Notifications are recorded in the comms store
  (`~/.local/share/task-comms/notifications.sqlite`).
* When the service is running the window attaches to it and does not open radios; when it is stopped, the window owns them.
  Switching requires restarting the window (it releases its ports first).
* `task-mesh-service --status` prints whether it is running; `--version`.

## Notifications on LXDE
Pop-ups use org.freedesktop.Notifications on the session bus. **lxde-core does not depend on a notification daemon**
(lxpanel only Recommends one), so a Pi may have none: then no pop-ups appear, counts and the launcher badge still work,
and Network Status shows "no notification daemon". task-mesh never installs one. If you want pop-ups, install one yourself,
for example `notification-daemon` (Debian) — check first with the preflight script.

## 0.3.1 changes
* The window **attaches** to a running service automatically (also if the service starts later) and never opens a
  serial port meanwhile; it returns to direct mode 15 s after the service stops. Start/Stop is always your action.
* Pop-ups on LXDE need a notification daemon to be startable. Debian's notification-daemon has no D-Bus activation
  file. Diagnose with `task-mesh-notify-setup` (read-only); opt in with `task-mesh-notify-setup --enable` (two user
  files, see docs/phase4f1/ROOT-CAUSES-AND-FIXES.md), undo with `--disable`.
