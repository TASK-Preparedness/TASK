#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4F.1 preflight — READ-ONLY. Opens no serial port (lists /dev/serial/by-id only), writes nothing,
# needs no root. Run it in an LXDE terminal (so DISPLAY and the desktop's bus are visible) as the desktop user.
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '%s\n' "$*"; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
has_owner() {  # $1 = bus address
    DBUS_SESSION_BUS_ADDRESS="$1" /usr/bin/dbus-send --session --print-reply --dest=org.freedesktop.DBus \
        /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.freedesktop.Notifications 2>/dev/null \
        | /usr/bin/grep -q 'boolean true' && echo yes || echo no
}
say "== Versions (4F.1 expects task-mesh 0.3.0 -> 0.3.1; comms 0.3.1 and launcher 0.3.3 unchanged)"
for p in task-mesh python3-task-comms task-launcher task-core python3-jeepney python3-pycryptodome notification-daemon \
         dbus-user-session dbus-bin; do printf '  %-22s %s\n' "$p" "$(ver "$p" || true)"; done
M="$(ver task-mesh || true)"
[ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" gt 0.3.1 && say "  NOTE: task-mesh $M is newer than 0.3.1; the installer will refuse (no downgrade)."
say "== task-mesh-service"
say "  is-enabled: $(/usr/bin/systemctl --user is-enabled task-mesh-service 2>/dev/null || echo disabled/not-found)"
say "  is-active:  $(/usr/bin/systemctl --user is-active task-mesh-service 2>/dev/null || echo inactive)"
say "  MainPID:    $(/usr/bin/systemctl --user show -p MainPID --value task-mesh-service 2>/dev/null || echo ?)"
say "== Notifications (root cause check for Bug 2)"
say "  DISPLAY in this shell: ${DISPLAY:-(unset)}  XAUTHORITY: ${XAUTHORITY:-(unset)}"
say "  bus in this shell:     ${DBUS_SESSION_BUS_ADDRESS:-(unset)}"
UB="/run/user/$(/usr/bin/id -u)/bus"
[ -S "$UB" ] && say "  systemd user bus:      unix:path=$UB (present)" || say "  systemd user bus:      absent (dbus-user-session missing?)"
[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && say "  owner on this shell's bus: $(has_owner "$DBUS_SESSION_BUS_ADDRESS")"
[ -S "$UB" ] && say "  owner on systemd user bus: $(has_owner "unix:path=$UB")"
case "${DBUS_SESSION_BUS_ADDRESS:-}" in
    *"$UB"*|"") ;;
    *) say "  WARNING: the desktop and systemd --user use DIFFERENT buses; service pop-ups cannot reach this desktop." ;;
esac
say "  systemd --user env: $(/usr/bin/systemctl --user show-environment 2>/dev/null | /usr/bin/grep -E '^(DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS)=' | /usr/bin/tr '\n' ' ')"
for d in /usr/share/dbus-1/services /usr/local/share/dbus-1/services "$HOME/.local/share/dbus-1/services"; do
    for f in "$d"/*; do [ -f "$f" ] && /usr/bin/grep -q 'Name=org.freedesktop.Notifications' "$f" && say "  activation file: $f"; done
done
[ -x /usr/lib/notification-daemon/notification-daemon ] && say "  notification-daemon binary present" || say "  notification-daemon binary absent"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -af 'notification-daemon/notification-daemon' | /usr/bin/sed 's/^/  running: /' || say "  notification-daemon not running"
for f in "$HOME/.config/autostart/"*.desktop /etc/xdg/autostart/*.desktop; do
    [ -f "$f" ] && /usr/bin/grep -qE 'notification-daemon|dbus-update-activation-environment' "$f" && say "  autostart: $f"
done
say "== Serial (listing only; nothing is opened). The GPS on /dev/ttyACM0 is only listed."
for l in /dev/serial/by-id/*; do
    [ -e "$l" ] || continue
    t="$(/usr/bin/readlink -f "$l")"; owners=""
    for fd in /proc/[0-9]*/fd/*; do
        [ "$(/usr/bin/readlink "$fd" 2>/dev/null)" = "$t" ] || continue
        pid="${fd#/proc/}"; pid="${pid%%/*}"
        owners+=" $pid($(/usr/bin/tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | /usr/bin/cut -c1-50))"
    done
    say "  $(basename "$l") -> $t owner(s):${owners:- none visible}"
done
L="${XDG_RUNTIME_DIR:-/run/user/$(/usr/bin/id -u)}/task"
for f in "$L"/mesh-service.lock "$L"/mesh-devices/*.lock; do [ -f "$f" ] && say "  T.A.S.K. lock $f: $(/usr/bin/tr '\n' ' ' < "$f")"; done
[ -f "$HOME/.config/task-mesh/radio-protocols.json" ] && say "  radio assignments: $HOME/.config/task-mesh/radio-protocols.json (kept, backed up by the installer)"
say "== apt simulation (-s, no changes)"
[ -d "$HERE/debs" ] && /usr/bin/apt-get -s install --no-remove "$HERE"/debs/*.deb 2>&1 | /usr/bin/grep -E '^(Inst|Remv|Conf|E:)' | /usr/bin/sed 's/^/  /'
say "Preflight done. Nothing was changed."
