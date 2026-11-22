#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# DEVELOPER / LEGACY PATH ONLY. The supported install is the Debian package task-console
# (/usr/bin/task-console -> /usr/lib/task-console). This script pip-installs the console wheel under
# /usr/local and is kept for development machines without the .deb.
#
# Install T.A.S.K. Console 0.2.0 (PHASE-2.md section 14 item 6). Run from the unpacked bundle:
#
#   sudo ./install-console.sh
#
# It does exactly this and nothing else:
#   1. check the console wheel against SHA256SUMS
#   2. apt-get install the Debian trixie Qt packages (python3-pyside6.qtcore, qtgui, qtwidgets,
#      qtnetwork; qt6-wayland). This step needs the network or a local apt cache.
#   3. pip-install the console wheel into the system python3 (--no-deps --no-index). Debian's
#      python3 uses the "posix_local" install scheme, which already maps the default prefix to
#      /usr/local (bin: /usr/local/bin, modules: /usr/local/lib/python3.X/dist-packages). Never pass
#      "--prefix /usr/local" in addition: Debian appends /local again (/usr/local/local/...).
#   4. install the application-menu entry to /usr/local/share/applications/ and the icon to
#      /usr/local/share/icons/hicolor/scalable/apps/
#
# It creates NO autostart entry, no user or system unit, no labwc or display-manager change, and no
# account or group change (PHASE-2.md section 10.1). It never touches task-core, /etc/task or
# /var/lib/task. Reverse it with uninstall-console.sh.
#
# Socket access is a separate, explicit administrator command (section 12 item 1), not done here:
#   sudo usermod -aG task-core <desktop user>     (then log out and in)
#
# It refuses to run when the Debian package task-console is installed: /usr/local/bin comes first
# on PATH, so a pip copy would silently shadow the packaged /usr/bin/task-console. Remove the
# package first, or set TASK_CONSOLE_ALLOW_SHADOW=1 if you really want both.
#
# Environment overrides exist only so the script can be exercised off-target:
#   PYTHON, APT_GET, DPKG_QUERY, RAIN_ROOT (prefix for the share files), RAIN_PIP_ARGS (extra pip
#   arguments), RAIN_ALLOW_NONROOT=1
set -euo pipefail
umask 022

VERSION="0.2.0"
HERE="$(cd "$(dirname "$0")" && pwd)"
WHEEL_NAME="task_console-${VERSION}-py3-none-any.whl"
PYTHON="${PYTHON:-/usr/bin/python3}"
APT_GET="${APT_GET:-apt-get}"
DPKG_QUERY="${DPKG_QUERY:-dpkg-query}"
ROOT="${RAIN_ROOT:-}"
PACKAGES=(python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork
          qt6-wayland)

say() { echo "[install-console] $*"; }
die() { echo "[install-console] ERROR: $*" >&2; exit 1; }

find_file() {
  local name="$1" dir
  for dir in "$HERE" "$HERE/.." "$HERE/../dist"; do
    if [[ -e "$dir/$name" ]]; then (cd "$dir" && echo "$(pwd)/$name"); return 0; fi
  done
  return 1
}

if [[ "$(id -u)" -ne 0 && "${RAIN_ALLOW_NONROOT:-0}" != "1" ]]; then
  die "re-run as root: sudo $0"
fi
[[ -x "$PYTHON" ]] || die "$PYTHON not found"

# ---- 0. never shadow the Debian package ------------------------------------------------
if command -v "$DPKG_QUERY" >/dev/null 2>&1 \
   && [[ "$("$DPKG_QUERY" -W -f='${Status}' task-console 2>/dev/null || true)" == "install ok installed" ]] \
   && [[ "${TASK_CONSOLE_ALLOW_SHADOW:-0}" != "1" ]]; then
  die "the Debian package task-console is installed (/usr/bin/task-console); this pip install would shadow it. Nothing was changed."
fi

# ---- 1. checksum ---------------------------------------------------------------------
WHEEL="$(find_file "$WHEEL_NAME")" || die "$WHEEL_NAME not found next to this script"
SUMS="$(dirname "$WHEEL")/SHA256SUMS"
[[ -f "$SUMS" ]] || die "SHA256SUMS not found next to $WHEEL_NAME"
(cd "$(dirname "$WHEEL")" && grep " ${WHEEL_NAME}\$" SHA256SUMS | sha256sum -c --status) \
  || die "${WHEEL_NAME} does not match SHA256SUMS"
SHARE="$(find_file share)" || die "share/ (menu entry and icon) not found next to this script"
DESKTOP="${SHARE}/task-console.desktop"
ICON="${SHARE}/icons/hicolor/scalable/apps/task-console.svg"
[[ -f "$DESKTOP" && -f "$ICON" ]] || die "menu entry or icon missing under ${SHARE}"
say "wheel checksum OK"

# ---- 2. Debian packages -------------------------------------------------------------------
say "${APT_GET} install -y ${PACKAGES[*]}"
"$APT_GET" install -y "${PACKAGES[@]}" || die "apt-get failed (network or local apt cache needed); nothing else was changed"

# ---- 3. the console wheel ------------------------------------------------------------
PIP_ARGS=(install --no-deps --no-index)
if "$PYTHON" -m pip install --help 2>/dev/null | grep -q break-system-packages; then
  PIP_ARGS+=(--break-system-packages)
fi
# shellcheck disable=SC2206
EXTRA=(${RAIN_PIP_ARGS:-})
say "pip ${PIP_ARGS[*]} ${EXTRA[*]} ${WHEEL_NAME}"
(cd / && "$PYTHON" -m pip "${PIP_ARGS[@]}" "${EXTRA[@]}" "$WHEEL") || die "pip failed"

# ---- 4. menu entry and icon (application menu only) -----------------------------------
install -D -m 0644 "$DESKTOP" "${ROOT}/usr/local/share/applications/task-console.desktop"
install -D -m 0644 "$ICON" "${ROOT}/usr/local/share/icons/hicolor/scalable/apps/task-console.svg"
say "menu entry: ${ROOT}/usr/local/share/applications/task-console.desktop"
say "OK. Start it from the application menu (T.A.S.K. Console) or run: task-console"
say "Socket access (once, separate): sudo usermod -aG task-core <desktop user>, then log out and in"
