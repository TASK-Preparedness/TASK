# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Shared helpers for the H1 0.2.1 deploy scripts. Sourced; not run directly.
# Environment overrides (off-target / simulation only):
#   PYTHON, RAIN_STATE_DIR, RAIN_ETC_DIR, RAIN_BACKUP_ROOT, RAIN_UNIT, RAIN_UNIT_FILE,
#   RAIN_SMOKE, RAIN_CORE_ADMIN, RAIN_SOCKET, RAIN_SERVICE_USER, RAIN_LEGACY_USER, RAIN_ALLOW_NONROOT=1,
#   RAIN_SKIP_ARCH=1, RAIN_SKIP_DEBIAN=1, RAIN_CONSOLE_WHEEL (optional path check)

: "${PYTHON:=/usr/bin/python3}"
: "${STATE_DIR:=${RAIN_STATE_DIR:-/var/lib/rain}}"
: "${ETC_DIR:=${RAIN_ETC_DIR:-/etc/rain}}"
: "${BACKUP_ROOT:=${RAIN_BACKUP_ROOT:-/var/backups/rain}}"
: "${UNIT:=${RAIN_UNIT:-rain-core}}"
: "${UNIT_FILE:=${RAIN_UNIT_FILE:-/etc/systemd/system/rain-core.service}}"
: "${SMOKE:=${RAIN_SMOKE:-/usr/local/bin/rain-smoke}}"
: "${SERVICE_USER:=${RAIN_SERVICE_USER:-rain-core}}"
: "${LEGACY_USER:=${RAIN_LEGACY_USER:-rain}}"
DEVICES_JSON="${STATE_DIR}/devices.json"
AUTH_TOML="${ETC_DIR}/auth.toml"
CORE_TOML="${ETC_DIR}/core.toml"
# Canonical devices.json projection helper (bundle r2). Python 3 stdlib only.
PROJECTION="${HERE}/devices_projection.py"

# Delivered rain-core 0.2.0 wheel (rollback target); must match rain-phase2-dist.
WHEEL_020_SHA256="253572c5e3f7b09012292b451460f2cae8a97ad529f20780c05174790b892bad"

installed_version() {
  (cd / && "$PYTHON" -c 'import rain_core; print(rain_core.__version__)' 2>/dev/null) || true
}

sha_of() { if [[ -f "$1" ]]; then sha256sum "$1" | cut -d' ' -f1; else echo absent; fi; }

stat_record() {
  # owner:group:mode octal:size:mtime_ns (portable enough for Linux)
  if [[ -e "$1" ]]; then
    stat -c '%U:%G:%a:%s:%Y' "$1"
  else
    echo absent
  fi
}

require_root() {
  if [[ "$(id -u)" -ne 0 && "${RAIN_ALLOW_NONROOT:-0}" != "1" ]]; then
    die "re-run as root: sudo bash $0"
  fi
}

# Bundle r3: rain-core is checked only through methods it serves to a PUBLIC peer
# (core_checks.py: v1/v2 core.health, v2 core.protocol, v2 device.counts). The r1/r2
# `rain-smoke devices` (v1 device.list, operator-only: rain_core/api.py:26,135-138)
# is gone: root is not in auth.toml [peers] on the Pi, so it was refused (forbidden).
CORE_CHECKS="${HERE}/core_checks.py"
# Optional authenticated check only (healthcheck.sh --authenticated): rain-core-admin,
# run as the invoking desktop user, with its own password prompt.
: "${ADMIN:=${RAIN_CORE_ADMIN:-}}"
if [[ -z "$ADMIN" ]]; then
  ADMIN="$(PATH=/usr/local/bin:/usr/bin:/bin command -v rain-core-admin 2>/dev/null || true)"
fi

# Bundle r2: write the comparison snapshot healthcheck.sh uses (RAIN_PRE_SNAPSHOT).
#   devices.json            byte copy (evidence / --restore-config source) or devices.json.ABSENT
#   devices.projection.json canonical projection + owner:group:mode (compared, not the bytes)
#   STAT.txt                owner:group:mode:size:mtime for the config files (strict owner/mode)
#   SHA256SUMS              of everything in the directory
# auth.toml / core.toml byte copies are taken once by the caller (strict sha256 compare).
# Fails (non-zero) if devices.json exists but is not valid for rain-core's loader.
write_state_snapshot() {
  local dir="$1" f
  [[ -d "$dir" ]] || return 1
  rm -f "$dir/devices.json" "$dir/devices.json.ABSENT" || return 1
  if [[ -f "$DEVICES_JSON" ]]; then
    cp -a "$DEVICES_JSON" "$dir/devices.json" || return 1
  else
    echo absent > "$dir/devices.json.ABSENT" || return 1
  fi
  "$PYTHON" "$PROJECTION" snapshot "$DEVICES_JSON" "$dir/devices.projection.json" >/dev/null || return 1
  {
    echo "# path owner:group:mode:size:mtime"
    for f in "$AUTH_TOML" "$CORE_TOML" "$DEVICES_JSON" "$STATE_DIR" "$UNIT_FILE"; do
      echo "$(stat_record "$f")  $f"
    done
  } > "$dir/STAT.txt" || return 1
  (cd "$dir" && find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' | LC_ALL=C sort \
    | xargs -d '\n' sha256sum -- > SHA256SUMS) || return 1
}

# Bundle r3: interpret healthcheck.sh's exit status after the unit has been started.
# The installer/rollback NEVER stops rain-core because of a health check result:
#   * a validation-tool problem (INCOMPLETE) says nothing bad about rain-core (the r2
#     incident: a refused `rain-smoke devices` stopped a healthy Core);
#   * FAIL-STATE means rain-core runs but config/persisted state differs; stopping it
#     would not restore anything and removes the only hardware authority;
#   * FAIL-CORE: the operator decides (journal / rollback); a running process keeps its
#     evidence, and an inactive unit is already stopped. Rollback stops it itself.
# Prints guidance and returns the exit status the caller should use.
health_verdict() {
  local rc="$1" rollback_cmd="$2" backup="$3" state
  state="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
  case "$rc" in
    0) return 0 ;;
    2) say "healthcheck INCOMPLETE: a validation step could not run (see INCOMPLETE/SKIPPED lines)."
       say "rain-core was NOT stopped (unit: ${state:-unknown}); its public health checks passed."
       say "Finish validation with: sudo bash ${HERE}/healthcheck.sh <version> --authenticated --user <you>"
       return 2 ;;
    3) say "healthcheck FAIL-STATE: rain-core is running and healthy, but config/state differs (see FAIL lines)."
       say "rain-core was NOT stopped (unit: ${state:-unknown}). Inspect, then if needed: ${rollback_cmd} [--restore-config]"
       [[ -n "$backup" ]] && say "Backup kept at: ${backup}"
       return 3 ;;
    1) say "healthcheck FAIL-CORE: rain-core is not healthy (see FAIL lines). Unit state: ${state:-unknown}."
       say "This script did NOT stop it. Inspect: journalctl -u ${UNIT} -b --no-pager | tail -n 80"
       say "Rollback command: ${rollback_cmd}"
       [[ -n "$backup" ]] && say "Backup kept at: ${backup}"
       return 1 ;;
    *) say "healthcheck exited ${rc} (usage/unexpected); treated as INCOMPLETE. rain-core was NOT stopped (unit: ${state:-unknown})."
       return 2 ;;
  esac
}
