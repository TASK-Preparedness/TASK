#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. Phase 4F.3 preflight — READ-ONLY: no root, writes nothing, opens no device, no network.
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '%s\n' "$*"; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
say "== Versions (4F.3: launcher 0.3.4 -> 0.3.5, task-resources 0.2.1 -> 0.2.2; needs task-mesh >= 0.3.1)"
for p in task-launcher task-resources task-mesh python3-task-comms task-core task-sdr python3-libzim \
         python3-pyside6.qtwebenginewidgets python3-pyside6.qtpdf; do printf '  %-36s %s\n' "$p" "$(ver "$p" || true)"; done
L="$(ver task-launcher || true)"; R="$(ver task-resources || true)"; M="$(ver task-mesh || true)"
{ [ -n "$M" ] && /usr/bin/dpkg --compare-versions "$M" ge 0.3.1; } && say "  OK task-mesh $M (4F.1)" || say "  BLOCKER: task-mesh ${M:-none} < 0.3.1"
{ [ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" ge 0.3.4; } && say "  OK task-launcher $L (4F.2)" || say "  BLOCKER: task-launcher ${L:-none} < 0.3.4"
[ -n "$L" ] && /usr/bin/dpkg --compare-versions "$L" gt 0.3.5 && say "  BLOCKER: task-launcher $L newer than 0.3.5 (no downgrade)"
[ -n "$R" ] && /usr/bin/dpkg --compare-versions "$R" gt 0.2.2 && say "  BLOCKER: task-resources $R newer than 0.2.2 (no downgrade)"
say "== Medical manifests (exec on builtin medical is invalid and hides the tile)"
for d in /usr/share/task-launcher/apps.d /etc/task-launcher/apps.d "$HOME/.local/share/task-launcher/apps.d"; do
    for f in "$d"/*.toml; do
        [ -f "$f" ] && /usr/bin/grep -q 'builtin *= *"medical"' "$f" || continue
        /usr/bin/grep -qE '^ *exec *=' "$f" && say "  WARNING $f: exec present" || say "  ok: $f"
    done
done
I="${XDG_DATA_HOME:-$HOME/.local/share}/task-resources/index.sqlite"
[ -f "$I" ] && say "  Resources index: $I sha256 $(/usr/bin/sha256sum "$I" | /usr/bin/cut -c1-16)… (Medical opens it read-only)" || say "  Resources index: none yet"
say "  launcher processes: $(/usr/bin/pgrep -u "$(/usr/bin/id -u)" -fc 'task_launcher' || true); resources: $(/usr/bin/pgrep -u "$(/usr/bin/id -u)" -fc 'task_resources' || true)"
say "== apt simulation (-s, no changes)"
[ -d "$HERE/debs" ] && /usr/bin/apt-get -s install --no-remove "$HERE"/debs/*.deb 2>&1 | /usr/bin/grep -E '^(Inst|Remv|Conf|E:)' | /usr/bin/sed 's/^/  /'
say "Preflight done. Nothing was changed."
