#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Remove T.A.S.K. Console (PHASE-2.md section 10.1 item 7):
#
#   sudo ./uninstall-console.sh
#
# Removes only the console's files under /usr/local: the pip-installed task-console package and
# command, the menu entry and the icon. It leaves the Debian Qt packages installed (remove them with
# apt yourself if wanted), and it leaves every user's ~/.config/task-console and
# ~/.local/state/task-console (preferences and log; no secrets). No session change was ever made,
# so none is undone. task-core is not touched.
#
# Environment overrides for off-target tests: PYTHON, RAIN_ROOT, RAIN_ALLOW_NONROOT=1
set -euo pipefail

PYTHON="${PYTHON:-/usr/bin/python3}"
ROOT="${RAIN_ROOT:-}"

say() { echo "[uninstall-console] $*"; }
die() { echo "[uninstall-console] ERROR: $*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 && "${RAIN_ALLOW_NONROOT:-0}" != "1" ]]; then
  die "re-run as root: sudo $0"
fi
PIP_ARGS=(uninstall -y)
if "$PYTHON" -m pip uninstall --help 2>/dev/null | grep -q break-system-packages; then
  PIP_ARGS+=(--break-system-packages)
fi
say "pip ${PIP_ARGS[*]} task-console"
(cd / && "$PYTHON" -m pip "${PIP_ARGS[@]}" task-console) || say "task-console was not installed by pip"
rm -f "${ROOT}/usr/local/share/applications/task-console.desktop"
rm -f "${ROOT}/usr/local/share/icons/hicolor/scalable/apps/task-console.svg"
say "OK"
