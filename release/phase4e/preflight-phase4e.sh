#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# READ-ONLY preflight for Phase 4E (task-launcher 0.3.2 + task-resources 0.2.1). Writes NOTHING:
# no files, no temp files, no apt changes (apt-get -s is a simulation and needs no root), no sudo.
# Run as the desktop user:  bash preflight-phase4e.sh  [> report.txt  — redirect yourself if you want a copy]
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
hdr() { printf '\n== %s\n' "$*"; }

hdr "System"
printf 'user %s (uid %s)  arch %s  ' "$(/usr/bin/id -un)" "$(/usr/bin/id -u)" "$(/usr/bin/dpkg --print-architecture)"
. /etc/os-release 2>/dev/null && printf '%s\n' "${PRETTY_NAME:-?}"
printf 'session: XDG_SESSION_TYPE=%s XDG_CURRENT_DESKTOP=%s DISPLAY=%s WAYLAND_DISPLAY=%s\n' \
    "${XDG_SESSION_TYPE:-}" "${XDG_CURRENT_DESKTOP:-}" "${DISPLAY:-}" "${WAYLAND_DISPLAY:-}"

hdr "T.A.S.K. package versions"
for p in task-launcher task-resources task-core task-core-compat task-mesh python3-task-comms task-aprs task-sdr task-maps; do
    printf '  %-20s %s\n' "$p" "$(ver "$p" || true)"
done

hdr "Dependencies"
for p in python3 python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork \
         python3-pyside6.qtsvg python3-pyside6.qtdbus python3-libzim ca-certificates \
         python3-pyside6.qtwebenginewidgets python3-pyside6.qtpdfwidgets dpkg-repack; do
    v="$(ver "$p" || true)"; printf '  %-36s %s\n' "$p" "${v:-NOT INSTALLED}"
done

hdr "Package checksums"
( cd "$HERE" && /usr/bin/sha256sum -c SHA256SUMS 2>&1 | /usr/bin/grep -v ': OK$' ) || true
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS >/dev/null 2>&1 ) && echo "  SHA256SUMS: all OK" || echo "  SHA256SUMS: PROBLEM"

hdr "apt-get -s (simulation only; must show 0 to remove)"
/usr/bin/apt-get -s --no-remove install "$HERE/debs/task-launcher_0.3.2_all.deb" "$HERE/debs/task-resources_0.2.1_all.deb" 2>&1 \
    | /usr/bin/grep -E '^(Inst|Remv|Conf)|upgraded|newly installed|^E:|^W:' || true

hdr "Local modifications to task-launcher (replaced by the upgrade)"
/usr/bin/dpkg --verify task-launcher 2>&1 || true
/usr/bin/grep -nF 'not (t.builtin in ("radio", "library") and t.argv)' \
    /usr/share/task-launcher/task_launcher/ui/main_window.py 2>/dev/null && echo "  (manual Library fix present)" || true

hdr "Disk space"
/usr/bin/df -h "$HOME" / /usr 2>/dev/null | /usr/bin/awk '!seen[$0]++'
[ -d /library ] && /usr/bin/df -h /library | /usr/bin/tail -1

hdr "Storage and backup locations (tested with test -w; nothing is created)"
for d in "$HOME/.local/share/task-resources/downloads" "$HOME/.local/share/task-resources" "$HOME/.local/share" \
         "$HOME/task-backups" "$HOME"; do
    if [ -e "$d" ]; then printf '  %-55s exists, %s\n' "$d" "$([ -w "$d" ] && echo writable || echo NOT writable)"
    else printf '  %-55s does not exist yet\n' "$d"; fi
done
printf '  %-55s %s (never written by T.A.S.K.)\n' "/library" "$([ -d /library ] && echo present || echo absent)"

hdr "Serial ports and their owners (read-only: /dev and /proc of processes visible to this user)"
for p in /dev/serial/by-id/*; do
    [ -e "$p" ] || { echo "  none under /dev/serial/by-id"; break; }
    real="$(/usr/bin/readlink -f "$p")"
    printf '  %s -> %s  %s\n' "$(basename "$p")" "$real" "$(/usr/bin/stat -c '%U:%G %a' "$real")"
    for fd in /proc/[0-9]*/fd/*; do
        [ "$(/usr/bin/readlink "$fd" 2>/dev/null)" = "$real" ] || continue
        pid="${fd#/proc/}"; pid="${pid%%/*}"
        printf '      open by pid %s: %s\n' "$pid" "$(/usr/bin/tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | /usr/bin/cut -c1-100)"
    done
done
echo "  (processes of other users/root are not visible without root; this script never uses sudo)"

hdr "Kiwix / Core services (status only)"
for u in kiwix-serve.service task-core.service rain-core.service; do
    s="$(/usr/bin/systemctl is-active "$u" 2>/dev/null || true)"; [ -n "$s" ] && printf '  %-22s %s\n' "$u" "$s"
done
echo
echo "Preflight finished. Nothing was changed."
