#!/bin/bash
# In-place update of an installed rain-core 0.1.0 (installed by deploy/pi-install.sh)
# to rain-core 0.1.1. Run from the unpacked update bundle:
#
#   sudo ./update-0.1.1.sh
#
# It does exactly this and nothing else:
#   1. verify the current install (0.1.0, or already 0.1.1 -> nothing to install)
#   2. back up /var/lib/rain/devices.json and /etc/rain/*.toml to a timestamped dir
#   3. stop rain-core
#   4. pip-install the 0.1.1 wheel into the same system python3 (--no-deps --no-index)
#   5. verify the installed version
#   6. start rain-core
#   7. run health
#
# It never writes /etc/rain/auth.toml, /etc/rain/core.toml, or devices.json; never
# creates or changes users or groups; never touches the systemd unit, the modules,
# the rules, or rain-smoke; never runs pi-install.sh; never uses the network.
#
# Environment overrides exist only so the script can be exercised off-target:
#   PYTHON, RAIN_STATE_DIR, RAIN_ETC_DIR, RAIN_BACKUP_ROOT, RAIN_UNIT, RAIN_UNIT_FILE,
#   RAIN_SMOKE, RAIN_ALLOW_NONROOT=1
set -euo pipefail
# Files pip writes must stay world-readable: the unit runs python3 as the rain-core user.
umask 022

TARGET_VERSION="0.1.1"
FROM_VERSION="0.1.0"
HERE="$(cd "$(dirname "$0")" && pwd)"
WHEEL_NAME="rain_core-${TARGET_VERSION}-py3-none-any.whl"
WHEEL="${HERE}/${WHEEL_NAME}"
PYTHON="${PYTHON:-/usr/bin/python3}"
STATE_DIR="${RAIN_STATE_DIR:-/var/lib/rain}"
ETC_DIR="${RAIN_ETC_DIR:-/etc/rain}"
BACKUP_ROOT="${RAIN_BACKUP_ROOT:-/var/backups/rain-core}"
UNIT="${RAIN_UNIT:-rain-core}"
UNIT_FILE="${RAIN_UNIT_FILE:-/etc/systemd/system/rain-core.service}"
SMOKE="${RAIN_SMOKE:-/usr/local/bin/rain-smoke}"
DEVICES_JSON="${STATE_DIR}/devices.json"

say() { echo "[update-${TARGET_VERSION}] $*"; }
die() { echo "[update-${TARGET_VERSION}] ERROR: $*" >&2; exit 1; }

installed_version() {
  # Run from / so a rain_core directory in the current directory cannot shadow the install.
  (cd / && "$PYTHON" -c 'import rain_core; print(rain_core.__version__)' 2>/dev/null) || true
}

sha_of() { if [[ -f "$1" ]]; then sha256sum "$1" | cut -d' ' -f1; else echo absent; fi; }

health() {
  local out="" i
  for i in $(seq 1 20); do
    if out="$("$SMOKE" health 2>/dev/null)"; then
      echo "$out"
      echo "$out" | "$PYTHON" -c '
import json, sys
r = json.load(sys.stdin)
sys.exit(0 if r.get("ok") and r["result"].get("version") == sys.argv[1] else 1)' "$1" && return 0
    fi
    sleep 0.5
  done
  echo "$out"
  return 1
}

# ---- 1. verify the current install -------------------------------------------------
if [[ "$(id -u)" -ne 0 && "${RAIN_ALLOW_NONROOT:-0}" != "1" ]]; then
  die "re-run as root: sudo $0"
fi
[[ -x "$PYTHON" ]] || die "$PYTHON not found"
[[ -f "$UNIT_FILE" ]] || die "$UNIT_FILE not found; this is not a pi-install.sh install"
[[ -f "${ETC_DIR}/core.toml" ]] || die "${ETC_DIR}/core.toml not found"
[[ -f "${ETC_DIR}/auth.toml" ]] || die "${ETC_DIR}/auth.toml not found"
[[ -x "$SMOKE" ]] || die "$SMOKE not found"
(cd / && "$PYTHON" -c 'import yaml, pyudev') || die "python3-yaml / python3-pyudev missing (pi-install.sh installs them)"

CURRENT="$(installed_version)"
say "installed rain_core version: ${CURRENT:-none}"
if [[ "$CURRENT" == "$TARGET_VERSION" ]]; then
  say "already ${TARGET_VERSION}; nothing to install"
  if ! systemctl is-active --quiet "$UNIT"; then
    say "starting ${UNIT}"
    systemctl start "$UNIT"
  fi
  health "$TARGET_VERSION" || die "health check failed"
  say "OK (no change)"
  exit 0
fi
[[ "$CURRENT" == "$FROM_VERSION" ]] || die "expected rain_core ${FROM_VERSION}, found '${CURRENT:-none}'; refusing"

[[ -f "$WHEEL" ]] || die "$WHEEL not found next to this script"
[[ -f "${HERE}/SHA256SUMS" ]] || die "${HERE}/SHA256SUMS not found"
(cd "$HERE" && grep " ${WHEEL_NAME}\$" SHA256SUMS | sha256sum -c --status) \
  || die "${WHEEL_NAME} does not match SHA256SUMS"
say "wheel checksum OK"

# ---- 2. back up state and configuration --------------------------------------------
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${BACKUP_ROOT}/${TS}-pre-${TARGET_VERSION}"
(umask 077 && mkdir -p "$BACKUP")
chmod 0700 "$BACKUP"
if [[ -f "$DEVICES_JSON" ]]; then
  cp -a "$DEVICES_JSON" "$BACKUP/devices.json"
else
  say "no ${DEVICES_JSON} yet (nothing assigned); nothing to back up there"
fi
cp -a "${ETC_DIR}"/*.toml "$BACKUP/"
{
  echo "rain_core_version=${CURRENT}"
  echo "python=${PYTHON}"
  echo "created_utc=${TS}"
} > "$BACKUP/INFO"
(cd "$BACKUP" && sha256sum -- * > SHA256SUMS)
say "backup: ${BACKUP}"
DEVICES_SHA_BEFORE="$(sha_of "$DEVICES_JSON")"

# ---- 3. stop rain-core --------------------------------------------------------------
say "stopping ${UNIT}"
systemctl stop "$UNIT"
# An assignment could have been written between the backup and the stop; keep the backup exact.
if [[ "$(sha_of "$DEVICES_JSON")" != "$DEVICES_SHA_BEFORE" ]]; then
  cp -a "$DEVICES_JSON" "$BACKUP/devices.json"
  (cd "$BACKUP" && sha256sum -- * > SHA256SUMS)
  DEVICES_SHA_BEFORE="$(sha_of "$DEVICES_JSON")"
  say "devices.json changed before stop; backup refreshed"
fi

# ---- 4. install the wheel into the existing system python ---------------------------
PIP_ARGS=(install --no-deps --no-index)
if "$PYTHON" -m pip install --help 2>/dev/null | grep -q break-system-packages; then
  PIP_ARGS+=(--break-system-packages)
fi
say "pip ${PIP_ARGS[*]} ${WHEEL_NAME}"
if ! (cd / && "$PYTHON" -m pip "${PIP_ARGS[@]}" "$WHEEL"); then
  say "pip failed; restarting the previous version"
  systemctl start "$UNIT" || true
  die "update not applied; backup kept at ${BACKUP}"
fi

# ---- 5. verify the version ----------------------------------------------------------
NOW="$(installed_version)"
[[ "$NOW" == "$TARGET_VERSION" ]] || die "installed version is '${NOW}', expected ${TARGET_VERSION}; ${UNIT} left stopped, backup at ${BACKUP}"
say "installed rain_core version: ${NOW}"
[[ "$(sha_of "$DEVICES_JSON")" == "$DEVICES_SHA_BEFORE" ]] || die "devices.json changed during install (should be impossible)"

# ---- 6. start rain-core -------------------------------------------------------------
say "starting ${UNIT}"
systemctl start "$UNIT"

# ---- 7. health ----------------------------------------------------------------------
health "$TARGET_VERSION" || die "health did not report ${TARGET_VERSION}; backup at ${BACKUP}"
systemctl is-active "$UNIT"
say "devices.json sha256 before=${DEVICES_SHA_BEFORE} now=$(sha_of "$DEVICES_JSON")"
say "OK: rain-core ${TARGET_VERSION} running. Backup: ${BACKUP}"
