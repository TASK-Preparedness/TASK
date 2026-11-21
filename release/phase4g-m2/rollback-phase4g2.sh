#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Roll back task-sdr 0.2.1 -> 0.2.0 from an installer backup. Optional --restore-data restores ~/.config/task-sdr.
set -euo pipefail
export LC_ALL=C
RBSUM=50fd915ca6ab9f5c4e442d308bfa29c06f32174fb29045b76efae41eda86be27
B="${1:?usage: $0 BACKUP_DIR [--restore-data]}"; R="${2:-}"
[ "$(/usr/bin/id -u)" = "0" ] && { echo "Run as the desktop user."; exit 2; }
D="$B/rollback-debs/task-sdr_0.2.0_all.deb"
[ "$(/usr/bin/sha256sum "$D" | /usr/bin/cut -d' ' -f1)" = "$RBSUM" ] || { echo "rollback deb missing/mismatch"; exit 1; }
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_sdr' >/dev/null && { echo "Close T.A.S.K. SDR first."; exit 1; }
echo "Will run: sudo apt-get install --no-remove --allow-downgrades $D"
read -r -p "Type yes: " a; [ "$a" = yes ] || { echo "nothing changed"; exit 1; }
/usr/bin/sudo /usr/bin/apt-get install --no-remove --allow-downgrades "$D"
if [ "$R" = --restore-data ] && [ -e "$B/.config/task-sdr" ]; then
    [ -e "$HOME/.config/task-sdr" ] && /usr/bin/mv -- "$HOME/.config/task-sdr" "$HOME/.config/task-sdr.phase4g2-$(/usr/bin/date +%Y%m%d-%H%M%S)"
    /usr/bin/cp -a -- "$B/.config/task-sdr" "$HOME/.config/task-sdr"
fi
echo "now: task-sdr $(/usr/bin/dpkg-query -W -f='${Version}' task-sdr)"
