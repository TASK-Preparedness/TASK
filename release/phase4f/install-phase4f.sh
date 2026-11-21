#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# T.A.S.K. Phase 4F installer: python3-task-comms 0.3.1 + task-mesh 0.3.0 + task-launcher 0.3.3.
#
#   ./install-phase4f.sh            check only (default). Changes nothing.
#   ./install-phase4f.sh --install  back up mesh/comms/launcher user data + config + current debs, then
#                                   `sudo apt-get install --no-remove` of exactly these three .deb files. Asks first.
#
# Run as the desktop user. Never: apt autoremove, removing packages, touching /etc/rain, /var/lib/rain,
# task-core / task-core.service, the Core 0.3.1 lock patch, radio/GPS/SDR config, autostart, or enabling
# task-mesh-service (it stays disabled).
set -euo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "$0")" && pwd)"
DEBS=("$HERE/debs/python3-task-comms_0.3.1_all.deb" "$HERE/debs/task-mesh_0.3.0_all.deb" "$HERE/debs/task-launcher_0.3.3_all.deb")
PKGS=(python3-task-comms task-mesh task-launcher)
MODE="${1:-check}"
ok=1
say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*"; }
fail() { printf 'PROBLEM: %s\n' "$*"; ok=0; }
ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
ge()  { /usr/bin/dpkg --compare-versions "$1" ge "$2"; }

[ "$(/usr/bin/id -u)" = "0" ] && { say "Run as the desktop user, not root."; exit 2; }
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) say "usage: $0 [--install]"; exit 2 ;; esac

say "== 1. Checksums"
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS ) && say "SHA256SUMS: OK" || fail "SHA256SUMS mismatch"
for d in "${DEBS[@]}"; do [ -f "$d" ] || fail "missing $d"; done
say "== 2. Installed versions"
for p in "${PKGS[@]}" task-core task-resources rain-mesh; do printf '  %-20s %s\n' "$p" "$(ver "$p" || true)"; done
L="$(ver task-launcher || true)"; [ -n "$L" ] && ! ge "$L" 0.3.2 && fail "task-launcher $L < 0.3.2: install Phase 4E first"
C="$(ver task-core || true)"; [ -z "$C" ] && warn "task-core not installed: receiving works, sending needs a Core sign-in"
say "== 2b. New Debian dependencies (python3-jeepney, python3-pycryptodome)"
for dep in python3-jeepney python3-pycryptodome; do
    if [ -n "$(ver "$dep" || true)" ]; then say "  $dep $(ver "$dep") installed"
    else
        f="$(ls "$HERE"/deps-arm64/"${dep}"_*.deb 2>/dev/null | head -n1 || true)"
        if [ -n "$f" ] && [ "$(/usr/bin/dpkg --print-architecture)" = arm64 -o "${f%_all.deb}" != "$f" ]; then
            DEBS+=("$f"); say "  $dep not installed: will install bundled $(basename "$f") (Debian trixie, sha256 in SHA256SUMS)"
        else say "  $dep not installed: apt will fetch it from the configured Debian archive"; fi
    fi
done
say "== 3. Radios in use right now (the upgrade restarts nothing, but close Mesh before installing)"
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -af 'task_mesh|task-mesh' | /usr/bin/sed 's/^/  running: /' || say "  task-mesh not running"
say "== 4. Plan"
say "  sudo apt-get install --no-remove ${DEBS[*]}"
say "  task-mesh-service is installed DISABLED; nothing is enabled or started."
[ "$ok" = 1 ] || { say "Checks failed; nothing changed."; exit 1; }
[ "$MODE" = check ] && { say "Check only; nothing changed. Run ./preflight-phase4f.sh for the full read-only report."; exit 0; }
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_mesh' >/dev/null && { say "Close T.A.S.K. Mesh first."; exit 1; }

read -r -p "Back up and install now? Type yes: " answer
[ "$answer" = "yes" ] || { say "Not confirmed; nothing changed."; exit 1; }

B="$HOME/task-backups/phase4f-$(/usr/bin/date +%Y%m%d-%H%M%S)"
/usr/bin/mkdir -p -m 0700 "$B"
# Databases (mesh history, hub, comms notifications), radio-protocol assignments, notification rules, configs.
for src in "$HOME/.config/task-mesh" "$HOME/.local/share/task-mesh" "$HOME/.local/state/task-mesh" \
           "$HOME/.config/task-comms" "$HOME/.local/share/task-comms" \
           "$HOME/.config/task-launcher" "$HOME/.local/share/task-launcher"; do
    if [ -e "$src" ]; then
        rel="${src#"$HOME"/}"; /usr/bin/mkdir -p "$B/$(dirname "$rel")"; /usr/bin/cp -a -- "$src" "$B/$rel"
    fi
done
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' "${PKGS[@]}" > "$B/versions-before.txt" 2>/dev/null || true
/usr/bin/mkdir -p "$B/rollback-debs"
if [ -x /usr/bin/dpkg-repack ]; then
    for p in "${PKGS[@]}"; do
        [ -n "$(ver "$p" || true)" ] && ( cd "$B/rollback-debs" && /usr/bin/dpkg-repack "$p" ) >/dev/null 2>&1 \
            && say "  repacked installed $p" || true
    done
fi
while read -r sum name; do
    src="$HERE/rollback/$name"
    if [ -f "$src" ] && [ "$(/usr/bin/sha256sum "$src" | /usr/bin/cut -d' ' -f1)" = "$sum" ]; then
        /usr/bin/cp -p -- "$src" "$B/rollback-debs/$name"; say "  saved $name (sha256 verified)"
    else fail "rollback deb $name missing or sha256 mismatch"; fi
done <<'SUMS'
4da951669a55a9a068b60abc788a1b7cccaf6b2212b6d6ce20fa20307d4dfe34 python3-task-comms_0.3.0_all.deb
39882d18a62ea896c27a54ed8bbc1238837b197d492498283f925c93f6193f28 task-mesh_0.2.0_all.deb
6c520b302121b90dd077a9f82e097e6fa02ecc8ec4aa140d8f658215c83f343e task-launcher_0.3.2_all.deb
SUMS
[ "$ok" = 1 ] || { say "Rollback debs could not be saved; NOT installing. Backup is in $B."; exit 1; }
say "Backup written to $B"
/usr/bin/sudo /usr/bin/apt-get install --no-remove "${DEBS[@]}"
say "== Installed:"; for p in "${PKGS[@]}"; do printf '  %-20s %s\n' "$p" "$(ver "$p")"; done
say "task-mesh-service: $(/usr/bin/systemctl --user is-enabled task-mesh-service 2>/dev/null || echo disabled) (left as is)"
say "Done. Rollback: ROLLBACK.md (backup in $B)."
