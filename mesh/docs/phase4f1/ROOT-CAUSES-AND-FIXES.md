<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Joshua Sturtz -->
# Phase 4F.1: root causes and fixes (task-mesh 0.3.1)

## Bug 1: "Disconnected — will retry — Serial port is in use … in use by service (pid N)"
**Root cause (source):** in 0.3.0, `app.py` chose the mode once at start-up and wired the radio panel's
Connect/Retry straight to `RadioWorker.connect_radio` in **every** mode. So a window opened before the service
started (or any Connect click while the service ran) went to the port, found the service's per-port lock
(`radio/locking.py`, which worked as designed) and went into BACKOFF.
**Fix:** `ui/hub_controller.py` HubController:
* re-checks every 2 s whether the service holds its instance lock. If it does, the window switches to service-client
  mode: it disconnects the Meshtastic worker, stops local MeshCore adapters (releasing their locks), disables the
  radio panel and uses the service over IPC. Connect/Retry go through `connect_requested()`, which refuses while the
  service runs.
* receives live events over `HubSubscriber` (one persistent connection per window, bounded reconnect backoff
  0.5/1/2/5 s) and refreshes immediately. The 2 s poll is kept as a fallback.
* sends replies with `send` over IPC. The service checks `explicit_user_action is True` and the Core session role
  (operator/administrator).
* service-client mode creates no local hub, so the service is the only writer.
* returns to direct mode only when the service has been gone for 15 s (a restart takes <10 s with RestartSec=10).
  It never connects automatically on that switch. The service is never stopped by the window.
* Network Status keeps the explicit Start/Stop buttons (with confirmation) as in 0.3.0.

**IPC review:** AF_UNIX socket at $XDG_RUNTIME_DIR/task/mesh.sock. The bind happens under umask 0177 and is then
chmod 0600. SO_PEERCRED uid must equal the service uid. JSON lines, max 256 KiB. New in 0.3.1:
* the server stamps a per-connection id (`_conn`) and strips any client-supplied `_`-key;
* per-connection write locks, because replies and events share one socket;
* close callbacks drop that window's focus lease;
* `stop()` shuts down client sockets.

Content methods (`messages`) need no session over IPC, the same as reading the 0600 DB file as the same user. The UI
shows content only while signed in.

## Bug 2: no desktop pop-up on LXDE
**Root cause:** Debian trixie `notification-daemon 3.20.0-5` (checked: package file list) ships
`/usr/lib/notification-daemon/notification-daemon` and a `NoDisplay` .desktop file only. It has **no**
`/usr/share/dbus-1/services/org.freedesktop.Notifications.service` and no autostart entry. GNOME starts it as a
session component; LXDE never does. So nothing owns org.freedesktop.Notifications, and every Notify fails.

The second factor is the bus and display. task-mesh-service (systemd --user) talks to the user bus
`/run/user/UID/bus`, which exists with `dbus-user-session`. A bus-activated daemon inherits the bus's activation
environment. On LXDE that environment has no DISPLAY unless the session imports it. If the X session instead runs
its own `dbus-launch` bus, the service and the desktop are on different buses. The preflight and
`task-mesh-notify-setup` report this.

**Fix (opt-in, user files only):** `task-mesh-notify-setup --enable` writes:
1. `~/.local/share/dbus-1/services/org.freedesktop.Notifications.service`: `Exec=/usr/lib/notification-daemon/notification-daemon`.
   It is skipped if any system activation file already provides the name. The bus starts at most one owner, so
   there are no duplicate daemons.
2. `~/.config/autostart/task-mesh-session-env.desktop`: `dbus-update-activation-environment --systemd DISPLAY
   XAUTHORITY` at login. This is argv only, it runs as the user, and it takes effect at the next login. To apply it
   now, run the same command in an LXDE terminal.

`--disable` removes only files carrying the marker. Nothing is installed or enabled by the package.

## Notification behaviour
* **Title:** "T.A.S.K. — New Mesh Message" (+ " [PRIORITY]").
* **Body when signed in:** "<Protocol> · <sender> · <Direct message|Channel N>". The sender is shown only if
  "show sender" is on. The preview line appears only if "show preview" is on.
* **Body when signed out/unknown:** "Sign in to T.A.S.K. Mesh to read it."
* **Timing:** expire_timeout 5000 ms.
* **Actions:** "default"/"Open".
* **Position:** chosen by the daemon. We send no x/y hints. notification-daemon has no per-notification position
  API and places pop-ups according to its own setting. "Upper-right" is UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST
  (on the Pi display).
* **Mute and quiet:** per protocol, per conversation, quiet mode and quiet hours. Counts are always kept.
* **Bursts:** the 3rd and later pop-ups within 10 s update one grouped "N new mesh messages" notification.
* **Dedupe:** the store's unique (protocol, key) and the comms store's message_id. A message re-delivered after a
  reconnect never pops up again.
* **Focus rule:** each window holds a focus lease (active and not minimised, 15 s TTL, renewed every 5 s) on its
  own IPC connection. While any lease is live, there is no pop-up and nothing is marked read. The lease clears on
  unfocus or minimise immediately, on close or crash via socket close, and on a hang via TTL. Multiple windows mean
  any focused window suppresses pop-ups.
* **Click:** the service maps the notification server id to the internal hub row id and publishes "open". An
  attached window raises and selects that conversation. With no window, the service runs
  `/usr/bin/task-mesh --open-message <int>`: argv only, an integer from our own map, only if DISPLAY is in its
  environment. Nothing from message content is ever passed.
