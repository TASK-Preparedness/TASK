#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Roll back task-sdr 0.2.0 -> 0.1.0 from an installer backup. Optional --restore-data restores ~/.config/task-sdr.
set -euo pipefail
export LC_ALL=C
RBSUM=2a78a379785bdacbb67d1fa0af0016f0070515b19e2087e17703c91d8b5da141
B="${1:?usage: $0 BACKUP_DIR [--restore-data]}"; R="${2:-}"
[ "$(/usr/bin/id -u)" = "0" ] && { echo "Run as the desktop user."; exit 2; }
D="$B/rollback-debs/task-sdr_0.1.0_all.deb"
[ "$(/usr/bin/sha256sum "$D" | /usr/bin/cut -d' ' -f1)" = "$RBSUM" ] || { echo "rollback deb missing/mismatch"; exit 1; }
/usr/bin/pgrep -u "$(/usr/bin/id -u)" -f 'task_sdr' >/dev/null && { echo "Close T.A.S.K. SDR first."; exit 1; }
echo "Will run: sudo apt-get install --no-remove --allow-downgrades $D (0.1.0 needs python3-soapysdr; apt may add it)"
read -r -p "Type yes: " a; [ "$a" = yes ] || { echo "nothing changed"; exit 1; }
/usr/bin/sudo /usr/bin/apt-get install --no-remove --allow-downgrades "$D"
if [ "$R" = --restore-data ] && [ -e "$B/.config/task-sdr" ]; then
    [ -e "$HOME/.config/task-sdr" ] && /usr/bin/mv -- "$HOME/.config/task-sdr" "$HOME/.config/task-sdr.phase4g-$(/usr/bin/date +%Y%m%d-%H%M%S)"
    /usr/bin/cp -a -- "$B/.config/task-sdr" "$HOME/.config/task-sdr"
fi
echo "now: task-sdr $(/usr/bin/dpkg-query -W -f='${Version}' task-sdr)"
