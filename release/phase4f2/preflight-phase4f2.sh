#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4F.2 preflight — READ-ONLY, no root, writes nothing, opens no device, no network.
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '%s\n' "$*"; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
say "== Versions (4F.2 expects 4F.1: task-mesh 0.3.1; launcher 0.3.3 -> 0.3.4)"
for p in task-launcher task-mesh python3-task-comms task-resources task-core; do printf '  %-20s %s\n' "$p" "$(ver "$p" || true)"; done
L="$(ver task-launcher || true)"; M="$(ver task-mesh || true)"
if [ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" ge 0.3.1; then say "  Phase 4F.1 detected (task-mesh $M)."
else say "  Phase 4F.1 NOT detected (task-mesh ${M:-none}); the installer will refuse. Install 4F.1 first."; fi
[ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" gt 0.3.4 && say "  NOTE: task-launcher $L is newer than 0.3.4; the installer will refuse (no downgrade)."
[ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" eq 0.3.4 && say "  task-launcher 0.3.4 already installed."
say "== Medical manifests (a user/admin copy that adds exec to builtin medical is rejected -> tile hidden)"
for d in /usr/share/task-launcher/apps.d /etc/task-launcher/apps.d "$HOME/.local/share/task-launcher/apps.d"; do
    for f in "$d"/*.toml; do
        [ -f "$f" ] && /usr/bin/grep -q 'builtin *= *"medical"' "$f" || continue
        if /usr/bin/grep -qE '^ *exec *=' "$f"; then say "  WARNING $f: builtin medical with exec (invalid; this hides the tile)"; else say "  ok: $f"; fi
    done
done
I="${XDG_DATA_HOME:-$HOME/.local/share}/task-resources/index.sqlite"
[ -f "$I" ] && say "  Resources index: $I sha256 $(/usr/bin/sha256sum "$I" | /usr/bin/cut -c1-16)… (read-only use)" || say "  Resources index: none yet (Medical shows the empty state)"
say "  launcher running: $(/usr/bin/pgrep -u "$(/usr/bin/id -u)" -fc 'task_launcher' || true) process(es)"
say "== apt simulation (-s, no changes)"
[ -d "$HERE/debs" ] && /usr/bin/apt-get -s install --no-remove "$HERE"/debs/*.deb 2>&1 | /usr/bin/grep -E '^(Inst|Remv|Conf|E:)' | /usr/bin/sed 's/^/  /'
say "Preflight done. Nothing was changed."
