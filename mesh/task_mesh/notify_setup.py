# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-mesh-notify-setup: diagnose (default, read-only) and OPT-IN enable desktop pop-ups on LXDE/X11.

Root cause on Debian trixie LXDE: notification-daemon 3.20.0-5 ships no D-Bus activation file and no autostart
entry (only a NoDisplay .desktop used by GNOME sessions), so nothing ever owns org.freedesktop.Notifications.

--enable writes two USER files (nothing system-wide, no root, no daemon started now):
  ~/.local/share/dbus-1/services/org.freedesktop.Notifications.service
      on-demand D-Bus activation of /usr/lib/notification-daemon/notification-daemon. The bus starts it only when
      nothing owns the name, so it never runs twice and never fights another daemon.
  ~/.config/autostart/task-mesh-session-env.desktop
      at LXDE login runs `dbus-update-activation-environment --systemd DISPLAY XAUTHORITY` so the bus-activated
      daemon and task-mesh-service (systemd --user) know the X display.
--disable removes exactly those two files (only if they carry our marker).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

MARK = "# created by task-mesh-notify-setup"
DAEMON = "/usr/lib/notification-daemon/notification-daemon"
UPDATE_ENV = "/usr/bin/dbus-update-activation-environment"
NAME = "org.freedesktop.Notifications"
SYSTEM_DIRS = ("/usr/share/dbus-1/services", "/usr/local/share/dbus-1/services")


def _xdg(var: str, default: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v and os.path.isabs(v) else Path.home() / default


def user_service_file() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "dbus-1/services" / f"{NAME}.service"


def autostart_file() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart/task-mesh-session-env.desktop"


def system_providers(dirs=None) -> list:
    out = []
    for d in (SYSTEM_DIRS if dirs is None else dirs):
        try:
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                try:
                    if f"Name={NAME}" in Path(p).read_text(errors="replace"):
                        out.append(p)
                except OSError:
                    pass
        except OSError:
            pass
    return out


def bus_report() -> dict:
    from task_mesh.hub.notifier import session_bus_address
    r = {"shell_bus": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""), "user_bus_socket": "",
         "display": os.environ.get("DISPLAY", ""), "owner": None, "activatable": None, "server": None}
    rd = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if os.path.exists(os.path.join(rd, "bus")):
        r["user_bus_socket"] = os.path.join(rd, "bus")
    addr = session_bus_address()
    if not addr:
        return r
    try:
        from jeepney import DBus, DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        conn = open_dbus_connection(bus=addr)
        try:
            dbus = DBus()
            r["owner"] = bool(conn.send_and_get_reply(dbus.NameHasOwner(NAME), timeout=3).body[0])
            r["activatable"] = NAME in conn.send_and_get_reply(dbus.ListActivatableNames(), timeout=3).body[0]
            if r["owner"]:
                a = DBusAddress("/org/freedesktop/Notifications", bus_name=NAME, interface=NAME)
                r["server"] = tuple(conn.send_and_get_reply(new_method_call(a, "GetServerInformation"), timeout=3).body)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        r["error"] = type(exc).__name__
    return r


def systemd_env_display() -> str:
    try:
        out = subprocess.run(["/usr/bin/systemctl", "--user", "show-environment"], capture_output=True, text=True,
                             timeout=5, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return next((ln.split("=", 1)[1] for ln in out.splitlines() if ln.startswith("DISPLAY=")), "")


def check(out=sys.stdout) -> int:
    r = bus_report()
    p = lambda *a: print(*a, file=out)  # noqa: E731
    p("Session bus in this shell:", r["shell_bus"] or "(unset)")
    p("systemd user bus socket:  ", r["user_bus_socket"] or "(none: dbus-user-session not installed?)")
    if r["shell_bus"] and r["user_bus_socket"] and r["user_bus_socket"] not in r["shell_bus"]:
        p("WARNING: this X session uses a different bus than systemd --user; task-mesh-service pop-ups will go to a bus "
          "with no display. Install dbus-user-session (Debian) so both share one bus.")
    p("DISPLAY here:", r["display"] or "(unset)", "| DISPLAY in systemd --user env:", systemd_env_display() or "(unset)")
    p("Notification owner on the bus:", r["owner"], "| activatable:", r["activatable"], "| server:", r["server"])
    p("notification-daemon binary:", DAEMON if os.path.exists(DAEMON) else "not installed")
    p("system activation files for the name:", system_providers() or "none (root cause on LXDE)")
    p("user activation file:", user_service_file(), "present" if user_service_file().exists() else "absent")
    p("login env import:", autostart_file(), "present" if autostart_file().exists() else "absent")
    return 0


def enable(out=sys.stdout) -> int:
    if os.geteuid() == 0:
        print("run as the desktop user, not root", file=out)
        return 2
    if not os.path.exists(DAEMON):
        print(f"{DAEMON} not found: install notification-daemon yourself first (task-mesh does not install it)", file=out)
        return 1
    prov = system_providers()
    sf = user_service_file()
    if prov:
        print(f"a system activation file already provides {NAME} ({prov[0]}); not adding another", file=out)
    else:
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(f"{MARK}\n[D-BUS Service]\nName={NAME}\nExec={DAEMON}\n")
        print(f"wrote {sf}", file=out)
    if os.path.exists(UPDATE_ENV):
        af = autostart_file()
        af.parent.mkdir(parents=True, exist_ok=True)
        af.write_text(f"{MARK}\n[Desktop Entry]\nType=Application\nName=T.A.S.K. session environment for "
                      f"notifications\nExec={UPDATE_ENV} --systemd DISPLAY XAUTHORITY\nNoDisplay=true\n"
                      "X-GNOME-Autostart-enabled=true\n")
        print(f"wrote {af} (takes effect at next login; to apply now run: {UPDATE_ENV} --systemd DISPLAY XAUTHORITY)",
              file=out)
    else:
        print(f"{UPDATE_ENV} not found (package dbus-bin); login env import skipped", file=out)
    return 0


def disable(out=sys.stdout) -> int:
    for f in (user_service_file(), autostart_file()):
        try:
            if f.read_text().startswith(MARK):
                f.unlink()
                print(f"removed {f}", file=out)
            else:
                print(f"left {f} (not created by this tool)", file=out)
        except FileNotFoundError:
            pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="task-mesh-notify-setup", description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--enable", action="store_true", help="opt in: write the two user files (see --help)")
    g.add_argument("--disable", action="store_true", help="remove the two user files")
    a = ap.parse_args(argv)
    if a.enable:
        return enable()
    if a.disable:
        return disable()
    return check()


if __name__ == "__main__":
    sys.exit(main())
