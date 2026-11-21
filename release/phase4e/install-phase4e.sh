#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# T.A.S.K. Phase 4E installer: task-launcher 0.3.2 + task-resources 0.2.1.
#
#   ./install-phase4e.sh            check only (default): versions, dependencies, checksums, plan. Changes nothing.
#   ./install-phase4e.sh --install  back up affected user config/state, then `sudo apt-get install --no-remove`
#                                   of exactly the two .deb files. Asks before installing.
#
# Run as the desktop user (NOT root; it calls sudo only for the apt step). Never runs apt autoremove,
# never removes packages (--no-remove aborts instead), never touches /etc/rain, /var/lib/rain, /var/lib/task,
# task-core, task-mesh, Kiwix, the ZIM library, the desktop session or autostart.
set -euo pipefail
export LC_ALL=C

HERE="$(cd "$(dirname "$0")" && pwd)"
DEBS=("$HERE/debs/task-launcher_0.3.2_all.deb" "$HERE/debs/task-resources_0.2.1_all.deb")
MODE="${1:-check}"
ok=1

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*"; }
fail() { printf 'PROBLEM: %s\n' "$*"; ok=0; }

ver() { /usr/bin/dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
ge()  { /usr/bin/dpkg --compare-versions "$1" ge "$2"; }

if [ "$(/usr/bin/id -u)" = "0" ]; then
    say "Run this as the desktop user, not as root (sudo is used only for the apt step)."; exit 2
fi
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) say "usage: $0 [--install]"; exit 2 ;; esac

say "== 1. Package files and checksums"
( cd "$HERE" && /usr/bin/sha256sum --quiet -c SHA256SUMS ) && say "SHA256SUMS: OK" || fail "SHA256SUMS mismatch"
for d in "${DEBS[@]}"; do [ -f "$d" ] || fail "missing $d"; done

say "== 2. Installed versions"
for p in task-launcher task-resources task-core task-mesh python3-task-comms; do
    printf '  %-22s %s\n' "$p" "$(ver "$p" || true)"
done
L="$(ver task-launcher || true)"; R="$(ver task-resources || true)"
[ -n "$L" ] && ! ge "$L" 0.3.0 && fail "task-launcher $L is older than 0.3.0; install the Phase 4C/4D packages first"
[ -n "$L" ] && ge "$L" 0.3.2 && warn "task-launcher $L is already >= 0.3.2"
[ -n "$R" ] && ge "$R" 0.2.1 && warn "task-resources $R is already >= 0.2.1"

say "== 3. Dependencies (installed from Debian by apt; nothing is downloaded by this script itself)"
need=(python3 python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork
      python3-pyside6.qtsvg python3-pyside6.qtdbus python3-libzim ca-certificates)
for p in "${need[@]}"; do
    v="$(ver "$p" || true)"
    if [ -z "$v" ]; then warn "$p not installed (apt will install it; needs the Debian archive or the 4D deps-arm64 debs)"
    else printf '  %-34s %s\n' "$p" "$v"; fi
done
v="$(ver python3-pyside6.qtcore || true)"; [ -n "$v" ] && ! ge "$v" 6.8 && fail "PySide6 $v < 6.8"
for p in python3-pyside6.qtwebenginewidgets python3-pyside6.qtpdfwidgets; do
    [ -n "$(ver "$p" || true)" ] && printf '  %-34s %s (recommended)\n' "$p" "$(ver "$p")" \
        || warn "$p not installed (optional; lightweight viewer / no PDF view)"
done

say "== 4. Local modifications that the upgrade replaces"
MW=/usr/share/task-launcher/task_launcher/ui/main_window.py
if [ -f "$MW" ] && /usr/bin/grep -q 'builtin in ("radio", "library")' "$MW"; then
    say "  $MW contains the manual Library fix; 0.3.2 ships the same fix (file is replaced, backed up below)."
fi
/usr/bin/dpkg --verify task-launcher 2>/dev/null | sed 's/^/  dpkg --verify: /' || true
TOML=/usr/share/task-launcher/apps.d/050-library.toml
[ -f "$TOML" ] && say "  $TOML present (0.3.2 ships it unchanged)."

say "== 5. Plan"
say "  sudo apt-get install --no-remove ${DEBS[*]}"
say "  backup: user config/state of task-launcher and task-resources -> ~/task-backups/phase4e-<time>/"
say "  NOT touched: task-core (lock-fix 0.3.1 is a separate, optional patch), task-mesh, comms, Kiwix, ZIMs."

[ "$ok" = 1 ] || { say "Checks failed; nothing changed."; exit 1; }
[ "$MODE" = check ] && { say "Check only; nothing changed. Run with --install to install."; exit 0; }

read -r -p "Back up and install now? Type yes: " answer
[ "$answer" = "yes" ] || { say "Not confirmed; nothing changed."; exit 1; }

B="$HOME/task-backups/phase4e-$(/usr/bin/date +%Y%m%d-%H%M%S)"
/usr/bin/mkdir -p -m 0700 "$B"
for src in "$HOME/.config/task-launcher" "$HOME/.local/share/task-launcher" "$HOME/.config/task-resources" \
           "$HOME/.local/share/task-resources"; do
    if [ -e "$src" ]; then
        rel="${src#"$HOME"/}"
        /usr/bin/mkdir -p "$B/$(dirname "$rel")"
        /usr/bin/cp -a -- "$src" "$B/$rel"          # -a keeps modes, owner (same user) and times
    fi
done
for f in "$MW" "$TOML"; do [ -f "$f" ] && /usr/bin/cp -p -- "$f" "$B/$(basename "$f").installed"; done
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' task-launcher task-resources > "$B/versions-before.txt" 2>/dev/null || true
# Rollback debs: (1) the exact installed packages via dpkg-repack when available (captures local edits),
# (2) always: the original 4D debs shipped in rollback/, verified against their 4D sha256 values.
/usr/bin/mkdir -p "$B/rollback-debs"
if [ -x /usr/bin/dpkg-repack ]; then
    for p in task-launcher task-resources; do
        [ -n "$(ver "$p" || true)" ] || continue
        ( cd "$B/rollback-debs" && /usr/bin/dpkg-repack "$p" ) >/dev/null 2>&1 \
            && say "  repacked installed $p $(ver "$p")" || warn "dpkg-repack $p failed (original 4D deb is still saved)"
    done
else
    say "  dpkg-repack not installed (not installed by this script); saving the original 4D debs instead"
fi
while read -r sum name; do
    src="$HERE/rollback/$name"
    if [ -f "$src" ] && [ "$(/usr/bin/sha256sum "$src" | /usr/bin/cut -d' ' -f1)" = "$sum" ]; then
        /usr/bin/cp -p -- "$src" "$B/rollback-debs/$name"; say "  saved $name (sha256 verified)"
    else
        fail "rollback deb $name missing or sha256 mismatch"
    fi
done <<'SUMS'
24a7adb70e57ce10802cab0ecccb38d55308ee362003cb54b24d8734db545049 task-launcher_0.3.1_all.deb
cb8159f1321cb7dd4114222ea437f90ce583e55d3b69b33266ad5d7a4aa6edfb task-resources_0.1.0_all.deb
SUMS
[ "$ok" = 1 ] || { say "Rollback debs could not be saved; NOT installing. Backup is in $B."; exit 1; }
say "Backup written to $B"

/usr/bin/sudo /usr/bin/apt-get install --no-remove "${DEBS[@]}"

say "== Installed:"
for p in task-launcher task-resources; do printf '  %-16s %s\n' "$p" "$(ver "$p")"; done
say "Done. Rollback: see INSTALL-UPGRADE-ROLLBACK.md (backup in $B)."
