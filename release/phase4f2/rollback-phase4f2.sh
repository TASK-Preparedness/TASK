#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Roll back 4F.2: ./rollback-phase4f2.sh ~/task-backups/phase4f2-YYYYmmdd-HHMMSS [--restore-data]
# Reinstalls task-launcher 0.3.3 (--allow-downgrades --no-remove). 4F.1 (task-mesh 0.3.1) is left in place.
set -euo pipefail
export LC_ALL=C
B="${1:?usage: $0 BACKUP_DIR [--restore-data]}"; R="${2:-}"
[ "$(/usr/bin/id -u)" = "0" ] && { echo "Run as the desktop user."; exit 2; }
D="$B/rollback-debs/task-launcher_0.3.3_all.deb"; [ -f "$D" ] || { echo "missing $D"; exit 1; }
[ "$(/usr/bin/sha256sum "$D" | /usr/bin/cut -d' ' -f1)" = d0d5a5ff3243373a55ae4832ad6204fa2120837b7b8e5ce7e31ea2c57871a2cc ] || { echo "sha256 mismatch"; exit 1; }
echo "Will run: sudo apt-get install --no-remove --allow-downgrades $D ${R:+and restore launcher settings from $B}"
read -r -p "Type yes: " a; [ "$a" = yes ] || { echo "nothing changed"; exit 1; }
/usr/bin/sudo /usr/bin/apt-get install --no-remove --allow-downgrades "$D"
if [ "$R" = --restore-data ]; then
    T="$(/usr/bin/date +%Y%m%d-%H%M%S)"
    for rel in .config/task-launcher .local/state/task-launcher .local/share/task-launcher; do
        if [ -e "$B/$rel" ]; then
            [ -e "$HOME/$rel" ] && /usr/bin/mv -- "$HOME/$rel" "$HOME/$rel.phase4f2-$T"
            /usr/bin/mkdir -p "$HOME/$(dirname "$rel")"; /usr/bin/cp -a -- "$B/$rel" "$HOME/$rel"
        fi
    done
fi
echo "task-launcher now $(/usr/bin/dpkg-query -W -f='${Version}' task-launcher). Restart the launcher."
