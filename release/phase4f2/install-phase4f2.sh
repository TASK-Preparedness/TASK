#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4F.2 installer: task-launcher 0.3.3 -> 0.3.4 (only this package). Requires Phase 4F.1.
#   ./install-phase4f2.sh            check only (default), changes nothing
#   ./install-phase4f2.sh --install  backup, then `sudo apt-get install --no-remove` of the one .deb (asks first)
# Never: autoremove, removals, services, Core/auth, Kiwix, /library, ZIMs, the Resources index, manifests.
set -euo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
DEB="$HERE/debs/task-launcher_0.3.4_all.deb"
MODE="${1:-check}"; ok=1
say() { printf '%s\n' "$*"; }
fail() { printf 'PROBLEM: %s\n' "$*"; ok=0; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
[ "$(/usr/bin/id -u)" = "0" ] && { say "Run as the desktop user, not root."; exit 2; }
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) say "usage: $0 [--install]"; exit 2 ;; esac
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS ) && say "SHA256SUMS: OK" || fail "SHA256SUMS mismatch"
L="$(ver task-launcher || true)"; M="$(ver task-mesh || true)"
say "installed: task-launcher=${L:-none} task-mesh=${M:-none}"
[ -z "$L" ] && fail "task-launcher is not installed"
[ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" gt 0.3.4 && fail "task-launcher $L is newer than 0.3.4: refusing to downgrade"
[ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" lt 0.3.3 && fail "task-launcher $L < 0.3.3: install Phase 4F first"
{ [ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" ge 0.3.1; } || fail "Phase 4F.1 not installed (task-mesh ${M:-none} < 0.3.1): install 4F.1 first"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_launcher' >/dev/null && say "NOTE: the launcher is running; the new version takes effect after you restart it (this script does not)."
say "plan: sudo apt-get install --no-remove $DEB"
[ "$ok" = 1 ] || { say "Checks failed; nothing changed."; exit 1; }
[ "$MODE" = check ] && { say "Check only; nothing changed."; exit 0; }
read -r -p "Back up and install task-launcher 0.3.4 now? Type yes: " a; [ "$a" = yes ] || { say "Not confirmed; nothing changed."; exit 1; }
B="$HOME/task-backups/phase4f2-$(/usr/bin/date +%Y%m%d-%H%M%S)"; /usr/bin/mkdir -p -m 0700 "$B"
for rel in .config/task-launcher .local/state/task-launcher .local/share/task-launcher; do
    [ -e "$HOME/$rel" ] && { /usr/bin/mkdir -p "$B/$(dirname "$rel")"; /usr/bin/cp -a -- "$HOME/$rel" "$B/$rel"; }
done
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' task-launcher task-mesh python3-task-comms task-resources > "$B/versions-before.txt" 2>/dev/null || true
/usr/bin/mkdir -p "$B/rollback-debs"
R="$HERE/rollback/task-launcher_0.3.3_all.deb"
if [ -f "$R" ] && [ "$(/usr/bin/sha256sum "$R" | /usr/bin/cut -d' ' -f1)" = d0d5a5ff3243373a55ae4832ad6204fa2120837b7b8e5ce7e31ea2c57871a2cc ]; then
    /usr/bin/cp -p -- "$R" "$B/rollback-debs/"; say "  saved task-launcher_0.3.3_all.deb (sha256 verified)"
else say "Rollback deb missing or sha256 mismatch; NOT installing. Backup: $B"; exit 1; fi
say "Backup: $B"
/usr/bin/sudo /usr/bin/apt-get install --no-remove "$DEB"
say "installed task-launcher $(ver task-launcher). Restart the launcher to use it."
