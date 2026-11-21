#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4F.3 installer: task-launcher 0.3.5 + task-resources 0.2.2. Requires task-mesh >= 0.3.1 and
# task-launcher >= 0.3.4. Default: check only. --install: backup, then one `sudo apt-get install --no-remove`.
# Never: autoremove, removals, services, Core/auth, Kiwix, /library, ZIMs, config overwrite, manifests.
set -euo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
DEBS=("$HERE/debs/task-launcher_0.3.5_all.deb" "$HERE/debs/task-resources_0.2.2_all.deb")
MODE="${1:-check}"; ok=1
say() { printf '%s\n' "$*"; }
fail() { printf 'PROBLEM: %s\n' "$*"; ok=0; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
[ "$(/usr/bin/id -u)" = "0" ] && { say "Run as the desktop user, not root."; exit 2; }
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) say "usage: $0 [--install]"; exit 2 ;; esac
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS ) && say "SHA256SUMS: OK" || fail "SHA256SUMS mismatch"
L="$(ver task-launcher || true)"; R="$(ver task-resources || true)"; M="$(ver task-mesh || true)"
say "installed: task-launcher=${L:-none} task-resources=${R:-none} task-mesh=${M:-none}"
{ [ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" ge 0.3.1; } || fail "task-mesh ${M:-none} < 0.3.1: install Phase 4F.1 first"
{ [ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" ge 0.3.4; } || fail "task-launcher ${L:-none} < 0.3.4: install Phase 4F.2 first"
[ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" gt 0.3.5 && fail "task-launcher $L is newer than 0.3.5: refusing to downgrade"
[ -n "$R" ] && /usr/bin/dpkg --compare-versions "$R" gt 0.2.2 && fail "task-resources $R is newer than 0.2.2: refusing to downgrade"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_resources' >/dev/null && fail "close T.A.S.K. Resources first"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_launcher' >/dev/null && say "NOTE: restart the launcher afterwards (this script does not)."
say "plan: sudo apt-get install --no-remove ${DEBS[*]}"
[ "$ok" = 1 ] || { say "Checks failed; nothing changed."; exit 1; }
[ "$MODE" = check ] && { say "Check only; nothing changed."; exit 0; }
read -r -p "Back up and install now? Type yes: " a; [ "$a" = yes ] || { say "Not confirmed; nothing changed."; exit 1; }
B="$HOME/task-backups/phase4f3-$(/usr/bin/date +%Y%m%d-%H%M%S)"; /usr/bin/mkdir -p -m 0700 "$B"
for rel in .config/task-launcher .local/state/task-launcher .local/share/task-launcher .config/task-resources; do
    [ -e "$HOME/$rel" ] && { /usr/bin/mkdir -p "$B/$(dirname "$rel")"; /usr/bin/cp -a -- "$HOME/$rel" "$B/$rel"; }
done
/usr/bin/mkdir -p "$B/.local/share/task-resources"      # index only (never managed ZIM storage)
for f in "$HOME"/.local/share/task-resources/index.sqlite*; do [ -f "$f" ] && /usr/bin/cp -p -- "$f" "$B/.local/share/task-resources/"; done
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' task-launcher task-resources task-mesh > "$B/versions-before.txt" 2>/dev/null || true
/usr/bin/mkdir -p "$B/rollback-debs"
while read -r sum name; do
    if [ -f "$HERE/rollback/$name" ] && [ "$(/usr/bin/sha256sum "$HERE/rollback/$name" | /usr/bin/cut -d' ' -f1)" = "$sum" ]; then
        /usr/bin/cp -p -- "$HERE/rollback/$name" "$B/rollback-debs/"; say "  saved $name (sha256 verified)"
    else fail "rollback deb $name missing or sha256 mismatch"; fi
done <<'SUMS'
56a094238f0aefa15a05461ca91c6fec999d707f082f83efa09c339e5b170e3c task-launcher_0.3.4_all.deb
1ee136c8267d156dc98bd41a7750a3960fa495081bc951003f3b9420d8f8b234 task-resources_0.2.1_all.deb
SUMS
[ "$ok" = 1 ] || { say "Rollback debs could not be saved; NOT installing. Backup: $B"; exit 1; }
say "Backup: $B"
/usr/bin/sudo /usr/bin/apt-get install --no-remove "${DEBS[@]}"
say "installed task-launcher $(ver task-launcher), task-resources $(ver task-resources). Restart the launcher."
