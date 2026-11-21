#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Timestamped backup of rain-core state before installing 0.2.1 (or, with the
# label pre-rollback-0.2.0, before rolling back). Never stops the service.
# Prints the backup directory path on the last line as:
#   BACKUP=<path>
#
#   sudo bash ./backup.sh                       # <ts>-pre-0.2.1
#   sudo bash ./backup.sh pre-rollback-0.2.0    # used by rollback-0.2.0.sh
#
# Bundle r2: devices.json is recorded as a byte copy (evidence) AND as a canonical
# projection (devices.projection.json: assignments, device ids, owner:group:mode),
# which is what healthcheck.sh compares. See devices_projection.py.
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_rain_h1_common.sh
source "${HERE}/_rain_h1_common.sh"
say() { echo "[backup-0.2.1] $*"; }
die() { echo "[backup-0.2.1] ERROR: $*" >&2; exit 1; }

require_root
CURRENT="$(installed_version)"
[[ -n "$CURRENT" ]] || die "rain_core is not installed"
[[ -d "$STATE_DIR" ]] || die "${STATE_DIR} not found"
[[ -f "$AUTH_TOML" && -f "$CORE_TOML" ]] || die "auth.toml / core.toml missing"

LABEL="${1:-pre-0.2.1}"
case "$LABEL" in
  pre-0.2.1|pre-rollback-0.2.0) ;;
  *) die "unknown backup label: ${LABEL}" ;;
esac
[[ -f "$PROJECTION" ]] || die "${PROJECTION} not found next to this script"
"$PYTHON" "$PROJECTION" validate "$DEVICES_JSON" \
  || die "${DEVICES_JSON} is not valid for rain-core's loader; nothing was changed; inspect it first"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${BACKUP_ROOT}/${TS}-${LABEL}"
[[ ! -e "$BACKUP" ]] || die "${BACKUP} already exists"
(umask 077 && mkdir -p "$BACKUP")
chmod 0700 "$BACKUP"

[[ -f "$DEVICES_JSON" ]] || say "no ${DEVICES_JSON} yet; noting absence"
cp -a "${ETC_DIR}"/*.toml "$BACKUP/" 2>/dev/null || die "failed to copy ${ETC_DIR}/*.toml"

# pip freeze of the interpreter that runs rain-core
(cd / && "$PYTHON" -m pip freeze 2>/dev/null || true) > "$BACKUP/pip-freeze.txt" || true

# Record which 0.2.0 files are currently installed (for evidence; rollback uses the bundle wheel)
(cd / && "$PYTHON" -c 'import rain_core, inspect, os; print(os.path.dirname(inspect.getfile(rain_core)))' 2>/dev/null) \
  > "$BACKUP/rain_core_location.txt" || true

{
  echo "rain_core_version=${CURRENT}"
  echo "python=${PYTHON}"
  echo "python_version=$("$PYTHON" -c 'import sys; print(sys.version.split()[0])')"
  echo "created_utc=${TS}"
  echo "label=${LABEL}"
  echo "bundle_revision=r2"
  echo "hostname=$(hostname 2>/dev/null || echo unknown)"
  echo "arch=$(uname -m)"
} > "$BACKUP/INFO"

# devices.json copy + projection, STAT.txt (owner/mode), SHA256SUMS
write_state_snapshot "$BACKUP" || die "devices.json snapshot failed; backup incomplete at ${BACKUP}"
say "devices.json projection: $(cd / && "$PYTHON" -c 'import json,sys; r=json.load(open(sys.argv[1])); print(json.dumps(r.get("projection", "absent"), sort_keys=True))' "$BACKUP/devices.projection.json")"
say "backup: ${BACKUP}"
echo "BACKUP=${BACKUP}"
