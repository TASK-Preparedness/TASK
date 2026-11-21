#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Roll back 4F.3: ./rollback-phase4f3.sh ~/task-backups/phase4f3-YYYYmmdd-HHMMSS [--restore-data]
# Reinstalls task-launcher 0.3.4 + task-resources 0.2.1 (--allow-downgrades --no-remove). Never touches ZIMs.
set -euo pipefail
export LC_ALL=C
B="${1:?usage: $0 BACKUP_DIR [--restore-data]}"; R="${2:-}"
[ "$(/usr/bin/id -u)" = "0" ] && { echo "Run as the desktop user."; exit 2; }
L="$B/rollback-debs/task-launcher_0.3.4_all.deb"; S="$B/rollback-debs/task-resources_0.2.1_all.deb"
[ "$(/usr/bin/sha256sum "$L" | /usr/bin/cut -d' ' -f1)" = 56a094238f0aefa15a05461ca91c6fec999d707f082f83efa09c339e5b170e3c ] || { echo "launcher deb missing/mismatch"; exit 1; }
[ "$(/usr/bin/sha256sum "$S" | /usr/bin/cut -d' ' -f1)" = 1ee136c8267d156dc98bd41a7750a3960fa495081bc951003f3b9420d8f8b234 ] || { echo "resources deb missing/mismatch"; exit 1; }
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_resources' >/dev/null && { echo "Close T.A.S.K. Resources first."; exit 1; }
echo "Will run: sudo apt-get install --no-remove --allow-downgrades $L $S ${R:+and restore launcher/resources settings from $B}"
read -r -p "Type yes: " a; [ "$a" = yes ] || { echo "nothing changed"; exit 1; }
/usr/bin/sudo /usr/bin/apt-get install --no-remove --allow-downgrades "$L" "$S"
if [ "$R" = --restore-data ]; then
    T="$(/usr/bin/date +%Y%m%d-%H%M%S)"
    for rel in .config/task-launcher .local/state/task-launcher .local/share/task-launcher .config/task-resources; do
        if [ -e "$B/$rel" ]; then
            [ -e "$HOME/$rel" ] && /usr/bin/mv -- "$HOME/$rel" "$HOME/$rel.phase4f3-$T"
            /usr/bin/mkdir -p "$HOME/$(dirname "$rel")"; /usr/bin/cp -a -- "$B/$rel" "$HOME/$rel"
        fi
    done
fi
echo "now: task-launcher $(/usr/bin/dpkg-query -W -f='${Version}' task-launcher), task-resources $(/usr/bin/dpkg-query -W -f='${Version}' task-resources). Restart the launcher."
