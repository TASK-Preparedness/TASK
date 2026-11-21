#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4F.1 installer: task-mesh 0.3.0 -> 0.3.1 (only this package).
#   ./install-phase4f1.sh            check only (default), changes nothing
#   ./install-phase4f1.sh --install  backup, then `sudo apt-get install --no-remove` of the one .deb (asks first)
# Never: autoremove, removing packages, enabling/starting/stopping task-mesh-service, notification setup,
# ModemManager/GPS/Direwolf/Kiwix/Core changes, touching radio-protocols.json or the databases (only copied).
set -euo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
DEB="$HERE/debs/task-mesh_0.3.1_all.deb"
MODE="${1:-check}"; ok=1
say() { printf '%s\n' "$*"; }
fail() { printf 'PROBLEM: %s\n' "$*"; ok=0; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
[ "$(/usr/bin/id -u)" = "0" ] && { say "Run as the desktop user, not root."; exit 2; }
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) say "usage: $0 [--install]"; exit 2 ;; esac
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS ) && say "SHA256SUMS: OK" || fail "SHA256SUMS mismatch"
M="$(ver task-mesh || true)"; C="$(ver python3-task-comms || true)"
say "installed: task-mesh=${M:-none} python3-task-comms=${C:-none} task-launcher=$(ver task-launcher || echo none)"
[ -z "$M" ] && fail "task-mesh is not installed; install Phase 4F (0.3.0) first"
[ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" gt 0.3.1 && fail "task-mesh $M is newer than 0.3.1: refusing to downgrade"
[ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" lt 0.3.0 && fail "task-mesh $M < 0.3.0: install Phase 4F first"
[ -z "$C" ] || /usr/bin/dpkg --compare-versions "$C" ge 0.3.1 || fail "python3-task-comms $C < 0.3.1 (Phase 4F)"
ACTIVE="$(/usr/bin/systemctl --user is-active task-mesh-service 2>/dev/null || true)"
[ "$ACTIVE" = active ] && fail "task-mesh-service is running. Stop it yourself first: systemctl --user stop task-mesh-service (this script never stops or starts it)"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_mesh.app' >/dev/null && fail "close T.A.S.K. Mesh first"
say "plan: sudo apt-get install --no-remove $DEB"
[ "$ok" = 1 ] || { say "Checks failed; nothing changed."; exit 1; }
[ "$MODE" = check ] && { say "Check only; nothing changed."; exit 0; }
read -r -p "Back up and install task-mesh 0.3.1 now? Type yes: " a; [ "$a" = yes ] || { say "Not confirmed; nothing changed."; exit 1; }
B="$HOME/task-backups/phase4f1-$(/usr/bin/date +%Y%m%d-%H%M%S)"; /usr/bin/mkdir -p -m 0700 "$B"
for rel in .config/task-mesh .local/share/task-mesh .local/state/task-mesh .config/task-comms .local/share/task-comms; do
    [ -e "$HOME/$rel" ] && { /usr/bin/mkdir -p "$B/$(dirname "$rel")"; /usr/bin/cp -a -- "$HOME/$rel" "$B/$rel"; }
done
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' task-mesh python3-task-comms task-launcher > "$B/versions-before.txt" 2>/dev/null || true
/usr/bin/mkdir -p "$B/rollback-debs"
[ -x /usr/bin/dpkg-repack ] && ( cd "$B/rollback-debs" && /usr/bin/dpkg-repack task-mesh >/dev/null 2>&1 ) && say "  repacked installed task-mesh" || true
while read -r sum name; do
    if [ -f "$HERE/rollback/$name" ] && [ "$(/usr/bin/sha256sum "$HERE/rollback/$name" | /usr/bin/cut -d' ' -f1)" = "$sum" ]; then
        /usr/bin/cp -p -- "$HERE/rollback/$name" "$B/rollback-debs/"; say "  saved $name (sha256 verified)"
    else fail "rollback deb $name missing or sha256 mismatch"; fi
done <<'SUMS'
63aa069c786b669ffb2c93d7af2f346b4c359f1f0bf20585ef696a8e84bc0c4e task-mesh_0.3.0_all.deb
8956231817cbfe2dd0f285fe5b84b5df4abd408c8e00af40f3a5996d6e4b09e4 python3-task-comms_0.3.1_all.deb
d0d5a5ff3243373a55ae4832ad6204fa2120837b7b8e5ce7e31ea2c57871a2cc task-launcher_0.3.3_all.deb
SUMS
[ "$ok" = 1 ] || { say "Rollback debs could not be saved; NOT installing. Backup: $B"; exit 1; }
say "Backup: $B"
/usr/bin/sudo /usr/bin/apt-get install --no-remove "$DEB"
say "installed task-mesh $(ver task-mesh). task-mesh-service left as it was (enabled: $(/usr/bin/systemctl --user is-enabled task-mesh-service 2>/dev/null || echo disabled))."
say "Optional, your choice: task-mesh-notify-setup (read-only check) / task-mesh-notify-setup --enable"
