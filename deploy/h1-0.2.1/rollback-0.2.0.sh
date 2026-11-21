#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Roll an installed rain-core 0.2.1 back to the delivered rain-core 0.2.0 wheel
# (sha256 253572c5…892bad, from rain-phase2-dist). Run from the unpacked deploy bundle:
#
#   sudo bash ./rollback-0.2.0.sh
#   sudo bash ./rollback-0.2.0.sh --restore-config   # only if a config hash drifted
#
# Exit status (bundle r3): as install-0.2.1.sh (0 OK, 1 FAIL-CORE / step failed,
# 2 INCOMPLETE, 3 FAIL-STATE). It never stops rain-core because of a health check result.
#
# Rollback means reinstalling the 0.2.0 wheel. Config restore is OFF by default
# because 0.2.1 never writes auth.toml / core.toml, and writes devices.json only on
# an explicit assign/unassign. Use --restore-config only when a drift was reported
# and you have inspected the backup.
#
# Bundle r2: devices.json drift vs the pre-0.2.1 backup is judged by the canonical
# projection (devices_projection.py): a lost/changed assignment, a lost device id,
# an owner/mode change or an invalid/missing file is drift; formatting/key order and
# NEW assignments are not. --restore-config never restores a devices.json that would
# drop an assignment made after the pre-0.2.1 backup (it warns instead).
# auth.toml / core.toml drift stays byte-strict.
#
# Further path back to 0.1.1: the Phase 2 bundle's rollback-0.1.1.sh (note only;
# this script never calls it).
#
set -euo pipefail
umask 022
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_rain_h1_common.sh
source "${HERE}/_rain_h1_common.sh"
say() { echo "[rollback-0.2.0] $*"; }
die() { echo "[rollback-0.2.0] ERROR: $*" >&2; exit 1; }

TARGET_VERSION="0.2.0"
FROM_VERSION="0.2.1"
WHEEL_NAME="rain_core-${TARGET_VERSION}-py3-none-any.whl"
WHEEL="${HERE}/${WHEEL_NAME}"
RESTORE_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --restore-config) RESTORE_CONFIG=1 ;;
    -h|--help) echo "usage: $0 [--restore-config]"; exit 0 ;;
    *) die "unknown argument: $arg" ;;
  esac
done

require_root
[[ -x "$PYTHON" ]] || die "$PYTHON not found"
[[ -f "$UNIT_FILE" ]] || die "$UNIT_FILE not found"
[[ -f "$CORE_TOML" && -f "$AUTH_TOML" ]] || die "auth.toml / core.toml missing"
[[ -x "$SMOKE" ]] || say "note: $SMOKE not found (not needed by bundle r3 checks)"
(cd / && "$PYTHON" -c 'import yaml, pyudev') || die "python3-yaml / python3-pyudev missing"

if getent passwd "$LEGACY_USER" >/dev/null 2>&1; then
  die "K3 pre-flight: an account named '${LEGACY_USER}' exists; stop and investigate"
fi
[[ -d "$STATE_DIR" ]] || die "${STATE_DIR} not found"
OWNER="$(stat -c '%U' "$STATE_DIR")"
[[ "$OWNER" == "$SERVICE_USER" ]] || die "K3: ${STATE_DIR} owned by '${OWNER}', expected '${SERVICE_USER}'"

CURRENT="$(installed_version)"
say "installed rain_core version: ${CURRENT:-none}"
if [[ "$CURRENT" == "$TARGET_VERSION" ]]; then
  say "already ${TARGET_VERSION}; nothing to install"
  if ! systemctl is-active --quiet "$UNIT"; then
    systemctl start "$UNIT"
  fi
  RC=0; bash "${HERE}/healthcheck.sh" "$TARGET_VERSION" || RC=$?
  RC2=0; health_verdict "$RC" "(already on ${TARGET_VERSION})" "" || RC2=$?
  [[ "$RC2" -eq 0 ]] && say "OK (no change)"
  exit "$RC2"
fi
[[ "$CURRENT" == "$FROM_VERSION" ]] || die "expected rain_core ${FROM_VERSION}, found '${CURRENT:-none}'; refusing"

[[ -f "$WHEEL" ]] || die "$WHEEL not found"
[[ -f "${HERE}/SHA256SUMS" ]] || die "SHA256SUMS not found"
(cd "$HERE" && grep " ${WHEEL_NAME}\$" SHA256SUMS | sha256sum -c --status) \
  || die "${WHEEL_NAME} does not match SHA256SUMS"
[[ "$(sha_of "$WHEEL")" == "$WHEEL_020_SHA256" ]] \
  || die "${WHEEL_NAME} is not the delivered 0.2.0 wheel"
say "wheel checksum OK (delivered 0.2.0)"

# Backup current (0.2.1) state before rolling back (backup.sh: tomls, devices.json copy +
# projection, STAT.txt). Refuses, changing nothing, if devices.json is invalid.
[[ -f "$PROJECTION" ]] || die "${PROJECTION} not found next to this script"
BACKUP_LINE="$(bash "${HERE}/backup.sh" pre-rollback-0.2.0 | tee /dev/stderr | awk -F= '/^BACKUP=/{print $2; exit}')"
[[ -n "$BACKUP_LINE" && -d "$BACKUP_LINE" ]] || die "backup.sh did not report BACKUP=...; nothing changed"
BACKUP="$BACKUP_LINE"
DEVICES_SHA_BEFORE="$(sha_of "$DEVICES_JSON")"

say "stopping ${UNIT}"
systemctl stop "$UNIT"
# rain-core can no longer write devices.json: re-take the snapshot (assign/unassign
# between backup and stop is legitimate), then hold all three files byte-strict.
if [[ "$(sha_of "$DEVICES_JSON")" != "$DEVICES_SHA_BEFORE" ]]; then
  say "devices.json changed between backup and stop (assign/unassign?); snapshot refreshed"
fi
write_state_snapshot "$BACKUP" || { systemctl start "$UNIT" || true; die "devices.json snapshot after stop failed; ${UNIT} restarted unchanged; backup at ${BACKUP}"; }
DEVICES_SHA_BEFORE="$(sha_of "$DEVICES_JSON")"
AUTH_SHA_BEFORE="$(sha_of "$AUTH_TOML")"
CORE_SHA_BEFORE="$(sha_of "$CORE_TOML")"

PIP_ARGS=(install --no-deps --no-index)
if "$PYTHON" -m pip install --help 2>/dev/null | grep -q break-system-packages; then
  PIP_ARGS+=(--break-system-packages)
fi
say "pip ${PIP_ARGS[*]} ${WHEEL_NAME}"
if ! (cd / && "$PYTHON" -m pip "${PIP_ARGS[@]}" "$WHEEL"); then
  say "pip failed; attempting to restart whatever is installed"
  systemctl start "$UNIT" || true
  die "rollback not applied; backup at ${BACKUP}"
fi

NOW="$(installed_version)"
[[ "$NOW" == "$TARGET_VERSION" ]] || die "installed version is '${NOW}', expected ${TARGET_VERSION}; ${UNIT} left stopped; backup at ${BACKUP}"

# rain-core is stopped: nothing may have written config during pip.
[[ "$(sha_of "$AUTH_TOML")" == "$AUTH_SHA_BEFORE" ]] || die "auth.toml changed while ${UNIT} was stopped (should be impossible)"
[[ "$(sha_of "$CORE_TOML")" == "$CORE_SHA_BEFORE" ]] || die "core.toml changed while ${UNIT} was stopped (should be impossible)"
[[ "$(sha_of "$DEVICES_JSON")" == "$DEVICES_SHA_BEFORE" ]] || die "devices.json changed while ${UNIT} was stopped (should be impossible)"

# Drift vs the latest pre-0.2.1 backup. auth/core.toml: byte-strict. devices.json:
# canonical projection + owner/mode (NEW assignments are not drift). Restore ONLY with
# --restore-config (cp -a keeps the backup's owner/mode, i.e. the pre-0.2.1 owner/mode).
PRE="$(ls -1d "${BACKUP_ROOT}"/*-pre-0.2.1 2>/dev/null | LC_ALL=C sort | tail -n 1 || true)"
DRIFT=()
if [[ -n "$PRE" && -d "$PRE" ]]; then
  for name in auth.toml core.toml; do
    if [[ -f "${PRE}/${name}" && "$(sha_of "${PRE}/${name}")" != "$(sha_of "${ETC_DIR}/${name}")" ]]; then
      DRIFT+=("${name}")
    fi
  done
  PRE_PROJ="${PRE}/devices.projection.json"
  if [[ ! -f "$PRE_PROJ" && -f "${PRE}/devices.json" ]]; then
    # backup made by bundle r1 (byte copy only): project the copy (cp -a kept owner/mode)
    PRE_PROJ="${BACKUP}/pre-0.2.1.devices.projection.json"
    "$PYTHON" "$PROJECTION" snapshot "${PRE}/devices.json" "$PRE_PROJ" >/dev/null \
      || die "pre-0.2.1 backup ${PRE}/devices.json is not valid; inspect it; nothing restored"
  fi
  if [[ -f "$PRE_PROJ" ]]; then
    say "devices.json vs pre-0.2.1 backup (projection):"
    if ! "$PYTHON" "$PROJECTION" compare "$PRE_PROJ" "$DEVICES_JSON" | sed 's/^/    /'; then
      DRIFT+=("devices.json")
    fi
  fi
  say "compared config with pre-0.2.1 backup ${PRE}: ${#DRIFT[@]} file(s) drifted${DRIFT:+ (${DRIFT[*]})}"
else
  say "no *-pre-0.2.1 backup under ${BACKUP_ROOT}; config drift check skipped"
fi
if [[ "${#DRIFT[@]}" -gt 0 ]]; then
  if [[ "$RESTORE_CONFIG" -eq 1 ]]; then
    for name in "${DRIFT[@]}"; do
      if [[ "$name" == "devices.json" ]]; then
        if [[ ! -f "${PRE}/devices.json" ]]; then
          say "WARNING: pre-0.2.1 backup had no devices.json; devices.json NOT restored"
          continue
        fi
        NEWER="$("$PYTHON" -c '
import json, sys
sys.path.insert(0, sys.argv[1])
import devices_projection as dp
def logicals(path):
    try:
        return set(dp.read_state(path).get("projection", {}).get("assignments", {}))
    except Exception:
        return set()
print(" ".join(sorted(logicals(sys.argv[3]) - logicals(sys.argv[2]))))' "$HERE" "${PRE}/devices.json" "$DEVICES_JSON")"
        if [[ -n "$NEWER" ]]; then
          say "WARNING: restoring devices.json would drop assignment(s) made after the pre-0.2.1 backup: ${NEWER}; NOT restored"
          continue
        fi
        cp -a "${PRE}/devices.json" "$DEVICES_JSON"
      else
        cp -a "${PRE}/${name}" "${ETC_DIR}/${name}"
      fi
      say "restored ${name} from ${PRE} (sha256 now $(sha_of "${PRE}/${name}"))"
    done
  else
    say "WARNING: ${DRIFT[*]} drifted from the pre-0.2.1 backup; NOT restored (no --restore-config)."
    say "         Inspect: diff ${PRE}/<file> <live file>; then re-run with --restore-config if wanted."
  fi
elif [[ "$RESTORE_CONFIG" -eq 1 ]]; then
  say "--restore-config: nothing drifted; nothing restored"
fi

# Reference for the post-start health check: the state just before start (after any
# --restore-config), so a deliberate restore is not reported as a change.
PRESTART="${BACKUP}/prestart"
(umask 077 && mkdir -p "$PRESTART")
cp -a "$AUTH_TOML" "$CORE_TOML" "$PRESTART/" || die "prestart snapshot failed; ${UNIT} left stopped; backup at ${BACKUP}"
write_state_snapshot "$PRESTART" || die "prestart snapshot failed; ${UNIT} left stopped; backup at ${BACKUP}"

say "starting ${UNIT}"
systemctl start "$UNIT"
export RAIN_PRE_SNAPSHOT="$PRESTART"
RC=0; bash "${HERE}/healthcheck.sh" "$TARGET_VERSION" || RC=$?
if [[ "$RC" -ne 0 ]]; then
  RC2=0; health_verdict "$RC" "re-install: sudo bash ${HERE}/install-0.2.1.sh" "$BACKUP" || RC2=$?
  exit "$RC2"
fi

say "OK: rain-core ${TARGET_VERSION} running. Backup: ${BACKUP}"
say "Note: further rollback to 0.1.1 uses the Phase 2 bundle's rollback-0.1.1.sh (not called by this script)."
