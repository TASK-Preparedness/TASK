#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Roll back Phase 4F: ./rollback-phase4f.sh ~/task-backups/phase4f-YYYYmmdd-HHMMSS
# Stops+disables task-mesh-service if YOU enabled it, reinstalls the saved debs (downgrade, --no-remove),
# and restores the backed-up user data (current data is moved aside, never deleted). Asks first.
set -euo pipefail
export LC_ALL=C
B="${1:?usage: $0 BACKUP_DIR}"
[ "$(/usr/bin/id -u)" = "0" ] && { echo "Run as the desktop user."; exit 2; }
[ -d "$B/rollback-debs" ] || { echo "no $B/rollback-debs"; exit 1; }
D=("$B/rollback-debs/python3-task-comms_0.3.0_all.deb" "$B/rollback-debs/task-mesh_0.2.0_all.deb" "$B/rollback-debs/task-launcher_0.3.2_all.deb")
for d in "${D[@]}"; do [ -f "$d" ] || { echo "missing $d"; exit 1; }; done
echo "Will: stop/disable task-mesh-service (user), sudo apt-get install --no-remove --allow-downgrades ${D[*]},"
echo "      move current ~/.config/task-mesh ~/.local/share/task-mesh ~/.local/share/task-comms aside, restore from $B."
read -r -p "Type yes: " a; [ "$a" = yes ] || { echo "nothing changed"; exit 1; }
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_mesh.app' >/dev/null && { echo "Close T.A.S.K. Mesh first."; exit 1; }
/usr/bin/systemctl --user disable --now task-mesh-service.service 2>/dev/null || true
/usr/bin/sudo /usr/bin/apt-get install --no-remove --allow-downgrades "${D[@]}"
T="$(/usr/bin/date +%Y%m%d-%H%M%S)"
for rel in .config/task-mesh .local/share/task-mesh .local/state/task-mesh .config/task-comms .local/share/task-comms \
           .config/task-launcher .local/share/task-launcher; do
    if [ -e "$B/$rel" ]; then
        [ -e "$HOME/$rel" ] && /usr/bin/mv -- "$HOME/$rel" "$HOME/$rel.phase4f-$T"
        /usr/bin/mkdir -p "$HOME/$(dirname "$rel")"; /usr/bin/cp -a -- "$B/$rel" "$HOME/$rel"
    fi
done
/usr/bin/dpkg-query -W -f='${Package} ${Version}\n' python3-task-comms task-mesh task-launcher
echo "Rolled back. Newer data was kept as *.phase4f-$T."
