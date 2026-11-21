#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4G M1 installer: task-sdr 0.2.0 (SDR Studio). Default: check only. --install: backup, then one
# `sudo apt-get install --no-remove`. Never: autoremove, removals, services, firmware, udev/blacklist, radio config.
set -euo pipefail
export LC_ALL=C
RBSUM=2a78a379785bdacbb67d1fa0af0016f0070515b19e2087e17703c91d8b5da141
HERE="$(cd "$(dirname "$0")" && pwd)"
DEB="$HERE/debs/task-sdr_0.2.0_all.deb"; MODE="${1:-check}"; ok=1
say() { printf '%s\n' "$*"; }
fail() { printf 'PROBLEM: %s\n' "$*"; ok=0; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
[ "$(/usr/bin/id -u)" = "0" ] && { say "Run as the desktop user, not root."; exit 2; }
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) say "usage: $0 [--install]"; exit 2 ;; esac
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS ) && say "SHA256SUMS: OK" || fail "SHA256SUMS mismatch"
S="$(ver task-sdr || true)"; say "installed: task-sdr=${S:-none}"
[ -n "$S" ] && /usr/bin/dpkg --compare-versions "$S" gt 0.2.0 && fail "task-sdr $S is newer than 0.2.0: refusing to downgrade"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_sdr' >/dev/null && fail "close T.A.S.K. SDR first"
say "plan: sudo apt-get install --no-remove $DEB"
[ "$ok" = 1 ] || { say "Checks failed; nothing changed."; exit 1; }
[ "$MODE" = check ] && { say "Check only; nothing changed."; exit 0; }
read -r -p "Back up and install now? Type yes: " a; [ "$a" = yes ] || { say "Not confirmed; nothing changed."; exit 1; }
B="$HOME/task-backups/phase4g-$(/usr/bin/date +%Y%m%d-%H%M%S)"; /usr/bin/mkdir -p -m 0700 "$B/rollback-debs"
[ -e "$HOME/.config/task-sdr" ] && { /usr/bin/mkdir -p "$B/.config"; /usr/bin/cp -a -- "$HOME/.config/task-sdr" "$B/.config/"; }
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' task-sdr python3-soapysdr librtlsdr0 > "$B/versions-before.txt" 2>/dev/null || true
R="$HERE/rollback/task-sdr_0.1.0_all.deb"
[ "$(/usr/bin/sha256sum "$R" | /usr/bin/cut -d' ' -f1)" = "$RBSUM" ] && /usr/bin/cp -p -- "$R" "$B/rollback-debs/" \
  || { say "rollback deb missing/mismatch; NOT installing. Backup: $B"; exit 1; }
say "Backup: $B"
/usr/bin/sudo /usr/bin/apt-get install --no-remove "$DEB"
say "installed task-sdr $(ver task-sdr). python3-soapysdr is kept (now optional); nothing was removed."
