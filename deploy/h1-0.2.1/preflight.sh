#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# H1 preflight for rain-core 0.2.0 → 0.2.1. Read-only: never stops the service,
# never writes config. Exit 0 only when every check passes.
#
#   sudo bash ./preflight.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_rain_h1_common.sh
source "${HERE}/_rain_h1_common.sh"
say() { echo "[preflight-0.2.1] $*"; }
die() { echo "[preflight-0.2.1] ERROR: $*" >&2; exit 1; }

TARGET_VERSION="0.2.1"
FROM_VERSION="0.2.0"
WHEEL_NAME="rain_core-${TARGET_VERSION}-py3-none-any.whl"
WHEEL="${HERE}/${WHEEL_NAME}"
WHEEL_020_NAME="rain_core-${FROM_VERSION}-py3-none-any.whl"
WHEEL_020="${HERE}/${WHEEL_020_NAME}"
MIN_FREE_KB=51200  # 50 MiB

require_root
say "checking install environment"

# Arch: Pi 5 is aarch64; pure-python wheel is py3-none-any so any arch works for the
# wheel itself, but the target must be aarch64 Debian 13 as installed.
ARCH="$(uname -m)"
if [[ "${RAIN_SKIP_ARCH:-0}" != "1" ]]; then
  [[ "$ARCH" == "aarch64" ]] || die "arch is '${ARCH}', expected aarch64 (Pi 5); set RAIN_SKIP_ARCH=1 only for off-target simulation"
else
  say "RAIN_SKIP_ARCH=1: arch ${ARCH} accepted for simulation"
fi

if [[ "${RAIN_SKIP_DEBIAN:-0}" != "1" ]]; then
  [[ -f /etc/os-release ]] || die "/etc/os-release missing"
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "debian" ]] || die "ID=${ID:-?} (expected debian)"
  [[ "${VERSION_ID:-}" == "13" ]] || die "VERSION_ID=${VERSION_ID:-?} (expected 13 / Debian trixie)"
  say "Debian ${VERSION_ID} (${VERSION_CODENAME:-?})"
else
  say "RAIN_SKIP_DEBIAN=1: skipping /etc/os-release check"
fi

[[ -x "$PYTHON" ]] || die "$PYTHON not found"
PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
# requires-python >=3.10; wheel tag is py3-none-any
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "python ${PY_VER} is older than 3.10"
say "python ${PY_VER} at ${PYTHON}"

[[ -f "$UNIT_FILE" ]] || die "$UNIT_FILE not found; this is not a pi-install.sh install"
[[ -f "$CORE_TOML" ]] || die "${CORE_TOML} not found"
[[ -f "$AUTH_TOML" ]] || die "${AUTH_TOML} not found"
[[ -x "$SMOKE" ]] || say "note: $SMOKE not found (not needed by bundle r3 checks)"
(cd / && "$PYTHON" -c 'import yaml, pyudev') || die "python3-yaml / python3-pyudev missing"

# K3
if getent passwd "$LEGACY_USER" >/dev/null 2>&1; then
  die "K3 pre-flight: an account named '${LEGACY_USER}' exists (web-station installer?); stop and investigate, nothing was changed"
fi
[[ -d "$STATE_DIR" ]] || die "${STATE_DIR} not found"
OWNER="$(stat -c '%U' "$STATE_DIR")"
[[ "$OWNER" == "$SERVICE_USER" ]] \
  || die "K3 pre-flight: ${STATE_DIR} is owned by '${OWNER}', expected '${SERVICE_USER}'; stop and investigate, nothing was changed"
say "K3 OK (${STATE_DIR} owned by ${SERVICE_USER}; no '${LEGACY_USER}' account)"

# Record owner/mode of config files (install/healthcheck will re-check)
for f in "$AUTH_TOML" "$CORE_TOML" "$DEVICES_JSON"; do
  [[ -e "$f" || "$f" == "$DEVICES_JSON" ]] || die "$f missing"
  say "stat $(basename "$f"): $(stat_record "$f")"
done

# Bundle r2: devices.json must be valid for rain-core's loader (persist.py:135-164);
# healthcheck compares its canonical projection, not its bytes.
[[ -f "$PROJECTION" ]] || die "${PROJECTION} not found next to this script"
"$PYTHON" "$PROJECTION" validate "$DEVICES_JSON" \
  || die "${DEVICES_JSON} is not valid for rain-core's loader; nothing was changed; inspect it first"

CURRENT="$(installed_version)"
say "installed rain_core version: ${CURRENT:-none}"
[[ "$CURRENT" == "$FROM_VERSION" || "$CURRENT" == "$TARGET_VERSION" ]] \
  || die "expected rain_core ${FROM_VERSION} (or already ${TARGET_VERSION}), found '${CURRENT:-none}'; refusing"

# rain-console 0.1.0 present (optional path; do not repackage)
CONSOLE_OK=0
if (cd / && "$PYTHON" -c 'import rain_console; assert rain_console.__version__ == "0.1.0"' 2>/dev/null); then
  CONSOLE_OK=1
  say "rain-console 0.1.0 importable in ${PYTHON}"
elif [[ -f /usr/local/share/applications/rain-console.desktop ]] || [[ -f /usr/share/applications/rain-console.desktop ]]; then
  CONSOLE_OK=1
  say "rain-console desktop entry present (wheel may be user-site; OK)"
elif [[ -n "${RAIN_CONSOLE_WHEEL:-}" && -f "${RAIN_CONSOLE_WHEEL}" ]]; then
  CONSOLE_OK=1
  say "RAIN_CONSOLE_WHEEL=${RAIN_CONSOLE_WHEEL} present"
else
  die "rain-console 0.1.0 not found (import rain_console failed and no desktop entry); refusing so the console stays paired with this core"
fi
[[ "$CONSOLE_OK" -eq 1 ]]

# Bundle integrity
[[ -f "$WHEEL" ]] || die "$WHEEL not found next to this script"
[[ -f "$WHEEL_020" ]] || die "$WHEEL_020 not found (needed for rollback)"
[[ -f "${HERE}/SHA256SUMS" ]] || die "${HERE}/SHA256SUMS not found"
(cd "$HERE" && grep " ${WHEEL_NAME}\$" SHA256SUMS | sha256sum -c --status) \
  || die "${WHEEL_NAME} does not match SHA256SUMS"
(cd "$HERE" && grep " ${WHEEL_020_NAME}\$" SHA256SUMS | sha256sum -c --status) \
  || die "${WHEEL_020_NAME} does not match SHA256SUMS"
[[ "$(sha_of "$WHEEL_020")" == "$WHEEL_020_SHA256" ]] \
  || die "${WHEEL_020_NAME} is not the delivered 0.2.0 wheel (expected ${WHEEL_020_SHA256})"
say "wheel checksums OK (0.2.1 + delivered 0.2.0)"
for script in _rain_h1_common.sh backup.sh healthcheck.sh install-0.2.1.sh rollback-0.2.0.sh devices_projection.py core_checks.py; do
  (cd "$HERE" && grep " ${script}\$" SHA256SUMS | sha256sum -c --status) \
    || die "${script} does not match SHA256SUMS"
done
say "script checksums OK"

# Free disk on state and on the python prefix
for path in "$STATE_DIR" /usr/local /var; do
  [[ -d "$path" ]] || continue
  free="$(df -Pk "$path" | awk 'NR==2{print $4}')"
  [[ "$free" -ge "$MIN_FREE_KB" ]] || die "free space on ${path} is ${free} KiB (< ${MIN_FREE_KB})"
done
say "disk space OK"

# Service unit exists; prefer active for a live update but allow inactive (preflight is read-only)
if systemctl cat "$UNIT" >/dev/null 2>&1; then
  say "unit ${UNIT}: $(systemctl is-active "$UNIT" 2>/dev/null || true) / $(systemctl is-enabled "$UNIT" 2>/dev/null || true)"
else
  die "systemctl cannot see unit ${UNIT}"
fi

# Conflicting process: another pip install of rain-core holding the site-packages
if pgrep -f 'pip .*rain_core|pip .*rain-core' >/dev/null 2>&1; then
  die "a pip process involving rain_core/rain-core is running; refuse to race it"
fi

say "OK: preflight passed (current=${CURRENT})"
exit 0
