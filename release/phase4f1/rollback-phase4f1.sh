#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Roll back 4F.1: ./rollback-phase4f1.sh ~/task-backups/phase4f1-YYYYmmdd-HHMMSS
# Reinstalls task-mesh 0.3.0 (--allow-downgrades --no-remove). User data is NOT replaced unless you add
# --restore-data (then the current dirs are moved aside, never deleted). Never starts/stops/enables the service.
set -euo pipefail
export LC_ALL=C
B="${1:?usage: $0 BACKUP_DIR [--restore-data]}"; R="${2:-}"
[ "$(/usr/bin/id -u)" = "0" ] && { echo "Run as the desktop user."; exit 2; }
D="$B/rollback-debs/task-mesh_0.3.0_all.deb"; [ -f "$D" ] || { echo "missing $D"; exit 1; }
[ "$(/usr/bin/systemctl --user is-active task-mesh-service 2>/dev/null || true)" = active ] && \
    { echo "Stop it yourself first: systemctl --user stop task-mesh-service"; exit 1; }
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_mesh.app' >/dev/null && { echo "Close T.A.S.K. Mesh first."; exit 1; }
echo "Will run: sudo apt-get install --no-remove --allow-downgrades $D ${R:+and restore user data from $B}"
read -r -p "Type yes: " a; [ "$a" = yes ] || { echo "nothing changed"; exit 1; }
/usr/bin/sudo /usr/bin/apt-get install --no-remove --allow-downgrades "$D"
if [ "$R" = --restore-data ]; then
    T="$(/usr/bin/date +%Y%m%d-%H%M%S)"
    for rel in .config/task-mesh .local/share/task-mesh .local/state/task-mesh .config/task-comms .local/share/task-comms; do
        if [ -e "$B/$rel" ]; then
            [ -e "$HOME/$rel" ] && /usr/bin/mv -- "$HOME/$rel" "$HOME/$rel.phase4f1-$T"
            /usr/bin/mkdir -p "$HOME/$(dirname "$rel")"; /usr/bin/cp -a -- "$B/$rel" "$HOME/$rel"
        fi
    done
fi
echo "task-mesh now $(/usr/bin/dpkg-query -W -f='${Version}' task-mesh). If you used task-mesh-notify-setup --enable, undo with --disable before or after (0.3.0 lacks the tool: delete the two files listed in its doc)."
