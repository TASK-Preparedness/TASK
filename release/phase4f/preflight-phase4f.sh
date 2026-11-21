#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# T.A.S.K. Phase 4F preflight — READ-ONLY. Changes nothing, opens no serial port, needs no root.
# Reports: installed versions, new dependencies, notification daemon, serial devices and their current
# owners, dialout membership, ModemManager, the task-mesh-service unit state, and an apt simulation.
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '%s\n' "$*"; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }

say "== Host: $(/usr/bin/hostname 2>/dev/null) user=$(/usr/bin/id -un) arch=$(/usr/bin/dpkg --print-architecture 2>/dev/null)"
say "== Installed T.A.S.K. packages"
for p in task-core task-core-compat task-launcher task-resources task-mesh rain-mesh python3-task-comms task-aprs task-sdr task-maps; do
    printf '  %-20s %s\n' "$p" "$(ver "$p" || true)"
done
say "== Dependencies needed by task-mesh 0.3.0"
for p in python3-pycryptodome python3-jeepney python3-serial python3-pubsub python3-protobuf python3-pyudev \
         python3-pyside6.qtwidgets; do
    v="$(ver "$p" || true)"; printf '  %-28s %s\n' "$p" "${v:-NOT INSTALLED (apt would install it)}"
done
say "== Notification daemon (org.freedesktop.Notifications on the session bus)"
if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -x /usr/bin/dbus-send ]; then
    /usr/bin/dbus-send --session --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.NameHasOwner string:org.freedesktop.Notifications 2>/dev/null | /usr/bin/grep -q 'boolean true' \
        && say "  owner present: pop-ups will show" || say "  NO owner: pop-ups will not show (counts/badge still work)"
else
    say "  cannot query (no session bus in this shell or dbus-send missing)"
fi
for p in notification-daemon xfce4-notifyd dunst mako-notifier lxqt-notificationd; do
    v="$(ver "$p" || true)"; [ -n "$v" ] && say "  package $p $v installed"
done
say "  (task-mesh never installs a notification daemon)"
say "== Serial devices (/dev/serial/by-id; listing only, nothing opened)"
if [ -d /dev/serial/by-id ]; then
    for l in /dev/serial/by-id/*; do
        t="$(/usr/bin/readlink -f "$l")"
        owners=""
        for fd in /proc/[0-9]*/fd/*; do
            [ "$(/usr/bin/readlink "$fd" 2>/dev/null)" = "$t" ] || continue
            pid="${fd#/proc/}"; pid="${pid%%/*}"
            owners+=" $pid($(/usr/bin/tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | /usr/bin/cut -c1-60))"
        done
        say "  $(basename "$l") -> $t  owner(s):${owners:- none visible to this user}"
    done
else
    say "  no /dev/serial/by-id (no USB serial device plugged in)"
fi
/usr/bin/id -nG | /usr/bin/tr ' ' '\n' | /usr/bin/grep -qx dialout && say "  user is in group dialout" \
    || say "  WARNING: user is NOT in group dialout (radios cannot be opened)"
/usr/bin/systemctl is-active ModemManager >/dev/null 2>&1 && say "  WARNING: ModemManager is active (it may probe serial radios)" \
    || say "  ModemManager not active"
say "== task-mesh-service (user unit)"
say "  enabled: $(/usr/bin/systemctl --user is-enabled task-mesh-service 2>/dev/null || echo 'not installed/disabled')"
say "  active:  $(/usr/bin/systemctl --user is-active task-mesh-service 2>/dev/null || echo inactive)"
say "== Existing user data that the installer will back up"
for d in "$HOME/.config/task-mesh" "$HOME/.local/share/task-mesh" "$HOME/.local/state/task-mesh" \
         "$HOME/.config/task-comms" "$HOME/.local/share/task-comms" "$HOME/.config/task-launcher"; do
    [ -e "$d" ] && say "  $d ($(/usr/bin/du -sh "$d" 2>/dev/null | /usr/bin/cut -f1))"
done
say "== apt simulation (no changes; -s)"
if [ -d "$HERE/debs" ]; then
    /usr/bin/apt-get -s install --no-remove "$HERE"/debs/*.deb 2>&1 | /usr/bin/grep -E '^(Inst|Remv|Conf|E:)' | /usr/bin/sed 's/^/  /'
fi
say "Preflight done. Nothing was changed."
