#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# In-place update of an installed rain-core 0.2.0 to rain-core 0.2.1 (H1).
# Run from the unpacked deploy bundle:
#
#   sudo bash ./install-0.2.1.sh
#
# Steps:
#   1. preflight.sh (stops on any failure; nothing changed yet)
#   2. backup.sh
#   3. stop rain-core
#   4. pip-install the 0.2.1 wheel (--no-deps --no-index; offline)
#   5. verify installed version
#   6. start rain-core
#   7. healthcheck.sh 0.2.1 against the backup snapshot (bundle r2: devices.json is
#      compared by canonical projection + owner/mode, auth/core.toml by sha256 + owner/mode;
#      bundle r3: rain-core checked through public methods only, no rain-smoke devices)
#
# Exit status (bundle r3): 0 OK; 1 FAIL-CORE or an install step failed; 2 INCOMPLETE
# (validation tool problem; rain-core running); 3 FAIL-STATE (rain-core running, config
# or state differs). After rain-core 0.2.1 has been started, this script never stops it
# because of a health check result (see health_verdict in _rain_h1_common.sh).
#
# Never writes auth.toml, core.toml, devices.json, accounts.json, sessions.toml;
# never creates users/groups; never touches the systemd unit; never runs
# pi-install.sh / update-0.2.0.sh / any other installer; never uses the network.
# On health-check failure the exact rollback command is printed (no auto-rollback);
# the service is not stopped (r3; r1/r2 stopped it).
#
set -euo pipefail
umask 022
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_rain_h1_common.sh
source "${HERE}/_rain_h1_common.sh"
say() { echo "[install-0.2.1] $*"; }
die() { echo "[install-0.2.1] ERROR: $*" >&2; exit 1; }

TARGET_VERSION="0.2.1"
FROM_VERSION="0.2.0"
WHEEL_NAME="rain_core-${TARGET_VERSION}-py3-none-any.whl"
WHEEL="${HERE}/${WHEEL_NAME}"

require_root

# ---- 1. preflight -------------------------------------------------------------------
bash "${HERE}/preflight.sh"

CURRENT="$(installed_version)"
if [[ "$CURRENT" == "$TARGET_VERSION" ]]; then
  say "already ${TARGET_VERSION}; nothing to install"
  if ! systemctl is-active --quiet "$UNIT"; then
    say "starting ${UNIT}"
    systemctl start "$UNIT"
  fi
  RC=0; bash "${HERE}/healthcheck.sh" "$TARGET_VERSION" || RC=$?
  RC2=0; health_verdict "$RC" "sudo bash ${HERE}/rollback-0.2.0.sh" "" || RC2=$?
  [[ "$RC2" -eq 0 ]] && say "OK (no change)"
  exit "$RC2"
fi
[[ "$CURRENT" == "$FROM_VERSION" ]] || die "expected ${FROM_VERSION}, found '${CURRENT:-none}'"

# ---- 2. backup ----------------------------------------------------------------------
BACKUP_LINE="$(bash "${HERE}/backup.sh" | tee /dev/stderr | awk -F= '/^BACKUP=/{print $2; exit}')"
[[ -n "$BACKUP_LINE" && -d "$BACKUP_LINE" ]] || die "backup.sh did not report BACKUP=..."
BACKUP="$BACKUP_LINE"
DEVICES_SHA_BEFORE="$(sha_of "$DEVICES_JSON")"
AUTH_SHA_BEFORE="$(sha_of "$AUTH_TOML")"
CORE_SHA_BEFORE="$(sha_of "$CORE_TOML")"

# ---- 3. stop ------------------------------------------------------------------------
say "stopping ${UNIT}"
systemctl stop "$UNIT"
# Re-take the devices.json snapshot now that rain-core cannot write it (an assign /
# unassign between backup.sh and the stop is legitimate). This snapshot (projection +
# owner:group:mode + STAT.txt) is what healthcheck.sh compares against.
if [[ "$(sha_of "$DEVICES_JSON")" != "$DEVICES_SHA_BEFORE" ]]; then
  say "devices.json changed between backup and stop (assign/unassign?); snapshot refreshed"
fi
write_state_snapshot "$BACKUP" || { systemctl start "$UNIT" || true; die "devices.json snapshot after stop failed (invalid for rain-core's loader?); ${UNIT} restarted on the old version; nothing installed; backup at ${BACKUP}"; }
DEVICES_SHA_BEFORE="$(sha_of "$DEVICES_JSON")"

# ---- 4. install wheel ---------------------------------------------------------------
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

# ---- 5. verify version --------------------------------------------------------------
NOW="$(installed_version)"
[[ "$NOW" == "$TARGET_VERSION" ]] || die "installed version is '${NOW}', expected ${TARGET_VERSION}; ${UNIT} left stopped; backup at ${BACKUP}; rollback: sudo bash ${HERE}/rollback-0.2.0.sh"
say "installed rain_core version: ${NOW}"
# rain-core is stopped here, so nothing may write config: byte-strict for all three files.
[[ "$(sha_of "$DEVICES_JSON")" == "$DEVICES_SHA_BEFORE" ]] || die "devices.json changed while ${UNIT} was stopped (should be impossible)"
[[ "$(sha_of "$AUTH_TOML")" == "$AUTH_SHA_BEFORE" ]] || die "auth.toml changed during install (should be impossible)"
[[ "$(sha_of "$CORE_TOML")" == "$CORE_SHA_BEFORE" ]] || die "core.toml changed during install (should be impossible)"

# ---- 6. start -----------------------------------------------------------------------
say "starting ${UNIT}"
systemctl start "$UNIT"

# ---- 7. health ----------------------------------------------------------------------
export RAIN_PRE_SNAPSHOT="$BACKUP"
RC=0; bash "${HERE}/healthcheck.sh" "$TARGET_VERSION" || RC=$?
if [[ "$RC" -ne 0 ]]; then
  RC2=0; health_verdict "$RC" "sudo bash ${HERE}/rollback-0.2.0.sh" "$BACKUP" || RC2=$?
  say "rain-core ${TARGET_VERSION} is installed. Rollback (reinstalls the delivered 0.2.0 wheel; no config restore unless --restore-config): sudo bash ${HERE}/rollback-0.2.0.sh"
  exit "$RC2"
fi

say "devices.json: projection + owner/mode unchanged (sha256 before=${DEVICES_SHA_BEFORE} now=$(sha_of "$DEVICES_JSON"), informational)"
say "auth.toml and core.toml sha256 + owner/mode unchanged"
say "OK: rain-core ${TARGET_VERSION} running. Backup: ${BACKUP}"
say "Rollback if needed: sudo bash ${HERE}/rollback-0.2.0.sh"
