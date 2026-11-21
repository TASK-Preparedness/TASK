#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Post-install / post-rollback health check for rain-core (bundle r3). Read-only:
# never stops, starts or restarts anything and never writes config or state.
#
#   sudo bash ./healthcheck.sh 0.2.1
#   sudo bash ./healthcheck.sh 0.2.0
#   sudo bash ./healthcheck.sh 0.2.1 --authenticated --user dragon     # optional, prompts
#
# Default checks need NO rain-core credentials. They use only what rain-core serves to
# a public peer (root is not in /etc/rain/auth.toml [peers]):
#   unit active; v1 core.health; v2 core.health (+ hotplug alive on 0.2.1);
#   v2 core.protocol; v2 device.counts (public, redacted: totals only) with
#   total >= assigned device ids in devices.json; devices.json valid for rain-core's loader.
# With RAIN_PRE_SNAPSHOT=<dir> (set by install/rollback, from backup.sh):
#   auth.toml, core.toml : STRICT sha256 + STRICT owner:group:mode
#   devices.json         : STRICT owner:group:mode + canonical projection (r2)
# Optional --authenticated --user NAME [--password-stdin]: runs
#   rain-core-admin devices --user NAME --json
# as the invoking desktop user ($SUDO_USER; root has no session bypass,
# rain_core/admin_client.py:567-570). The password is typed at rain-core-admin's own
# no-echo prompt on the terminal (or piped by the operator with --password-stdin); this
# script never reads, stores or passes it. Without --authenticated this step prints
# "SKIPPED (requires operator credentials)".
#
# Exit status (RESULT= line at the end):
#   0  PASS
#   1  FAIL-CORE   rain-core demonstrably unhealthy (unit inactive, unreachable, wrong
#                  version, malformed reply, hotplug not alive)
#   2  INCOMPLETE  a validation tool could not complete (authentication refused, tool
#                  missing, no terminal, unexpected tool output, unusable snapshot);
#                  says nothing bad about rain-core
#   3  FAIL-STATE  rain-core is healthy but config/state differs (auth/core.toml bytes or
#                  owner/mode, devices.json projection, device.counts below assignments,
#                  device.list contradicting devices.json)
#   64 usage
# This script deliberately does NOT use `set -e`: every check is handled explicitly so a
# refused or failing validation command can never abort the run (the r2 defect).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_rain_h1_common.sh
source "${HERE}/_rain_h1_common.sh"
say() { echo "[healthcheck] $*"; }
usage() { echo "[healthcheck] ERROR: $*" >&2; echo "RESULT=USAGE"; exit 64; }
die() { usage "$@"; }   # require_root() calls die

WANT=""
AUTH=0
AUTH_USER=""
PW_STDIN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --authenticated) AUTH=1 ;;
    --user) [[ $# -ge 2 ]] || usage "--user needs a name"; AUTH_USER="$2"; shift ;;
    --password-stdin) PW_STDIN=1 ;;
    -h|--help) sed -n '5,40p' "$0"; exit 0 ;;
    -*) usage "unknown option $1" ;;
    *) [[ -z "$WANT" ]] || usage "unexpected argument $1"; WANT="$1" ;;
  esac
  shift
done
[[ "$WANT" == "0.2.1" || "$WANT" == "0.2.0" ]] || usage "usage: $0 <0.2.1|0.2.0> [--authenticated --user NAME [--password-stdin]]"
if [[ "$AUTH" -eq 1 ]]; then
  [[ -n "$AUTH_USER" ]] || usage "--authenticated needs --user NAME"
  [[ "$AUTH_USER" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$ ]] || usage "invalid --user name"
elif [[ -n "$AUTH_USER" || "$PW_STDIN" -eq 1 ]]; then
  usage "--user / --password-stdin only with --authenticated"
fi
require_root
[[ -f "$CORE_CHECKS" ]] || usage "${CORE_CHECKS} not found next to this script"
[[ -f "$PROJECTION" ]] || usage "${PROJECTION} not found next to this script"

CORE_FAIL=0
STATE_FAIL=0
INCOMPLETE=0
finish() {
  local result code
  if [[ "$CORE_FAIL" -gt 0 ]]; then result="FAIL-CORE"; code=1
  elif [[ "$STATE_FAIL" -gt 0 ]]; then result="FAIL-STATE"; code=3
  elif [[ "$INCOMPLETE" -gt 0 ]]; then result="INCOMPLETE"; code=2
  else result="PASS"; code=0; fi
  say "summary: core_failures=${CORE_FAIL} state_failures=${STATE_FAIL} incomplete=${INCOMPLETE}"
  echo "RESULT=${result}"
  exit "$code"
}
core_check() {  # core_check <core_checks.py args...>
  if ! "$PYTHON" "$CORE_CHECKS" "$@"; then CORE_FAIL=$((CORE_FAIL + 1)); return 1; fi
}

# ---- 1. rain-core itself (public; no credentials) -----------------------------------
if systemctl is-active --quiet "$UNIT"; then
  echo "OK    unit ${UNIT} active"
else
  echo "FAIL  unit ${UNIT} is not active ($(systemctl is-active "$UNIT" 2>/dev/null || true))"
  CORE_FAIL=$((CORE_FAIL + 1))
  finish
fi
core_check v1-health "$WANT" || finish
core_check v2-health "$WANT"
core_check protocol "$WANT"
# rain-core keeps a record for every assigned device id (devices.py:180-199), so the
# public total must be >= the number of distinct assigned ids on disk.
ASSIGNED_IDS="$("$PYTHON" -c '
import sys
sys.path.insert(0, sys.argv[1])
import devices_projection as dp
try:
    state = dp.read_state(sys.argv[2])
except Exception:
    print(0); raise SystemExit
print(len(state["projection"]["device_ids"]) if state["present"] else 0)' "$HERE" "$DEVICES_JSON" 2>/dev/null || echo 0)"
"$PYTHON" "$CORE_CHECKS" counts --min-total "${ASSIGNED_IDS:-0}"
case $? in
  0) ;;
  3) STATE_FAIL=$((STATE_FAIL + 1)) ;;
  *) CORE_FAIL=$((CORE_FAIL + 1)) ;;
esac
[[ "$CORE_FAIL" -eq 0 ]] || finish

# ---- 2. config / persisted state (root-readable files; no credentials) --------------
if [[ -n "${RAIN_PRE_SNAPSHOT:-}" ]]; then
  SNAP="${RAIN_PRE_SNAPSHOT}"
  if [[ ! -d "$SNAP" || ! -f "${SNAP}/STAT.txt" || ! -f "${SNAP}/devices.projection.json" ]]; then
    echo "INCOMPLETE  RAIN_PRE_SNAPSHOT=${SNAP} is not a usable r2/r3 snapshot (needs STAT.txt + devices.projection.json); config comparison not done"
    INCOMPLETE=$((INCOMPLETE + 1))
    "$PYTHON" "$PROJECTION" validate "$DEVICES_JSON" || STATE_FAIL=$((STATE_FAIL + 1))
  else
    for name in auth.toml core.toml; do
      live="${ETC_DIR}/${name}"
      if [[ ! -f "${SNAP}/${name}" ]]; then
        echo "INCOMPLETE  snapshot missing ${name}"; INCOMPLETE=$((INCOMPLETE + 1)); continue
      fi
      before_sha="$(sha_of "${SNAP}/${name}")"; now_sha="$(sha_of "$live")"
      if [[ "$before_sha" != "$now_sha" ]]; then
        echo "FAIL  ${name} sha256 changed: before=${before_sha} now=${now_sha}"
        [[ -f "$live" ]] && diff -u "${SNAP}/${name}" "$live" 2>/dev/null | sed 's/^/      /' | head -n 40
        STATE_FAIL=$((STATE_FAIL + 1))
      else
        echo "OK    ${name} sha256 ${now_sha}"
      fi
      before="$(awk -v p="$live" '$2==p{print $1}' "${SNAP}/STAT.txt" | cut -d: -f1-3)"
      now="$(stat_record "$live" | cut -d: -f1-3)"
      if [[ -z "$before" || "$before" != "$now" ]]; then
        echo "FAIL  owner:group:mode of ${live} changed: before=${before:-unrecorded} now=${now}"
        STATE_FAIL=$((STATE_FAIL + 1))
      else
        echo "OK    ${name} owner:group:mode ${now}"
      fi
    done
    "$PYTHON" "$PROJECTION" compare "${SNAP}/devices.projection.json" "$DEVICES_JSON"
    case $? in
      0) ;;
      1) STATE_FAIL=$((STATE_FAIL + 1)) ;;
      *) echo "INCOMPLETE  devices.json projection compare could not run"; INCOMPLETE=$((INCOMPLETE + 1)) ;;
    esac
  fi
else
  "$PYTHON" "$PROJECTION" validate "$DEVICES_JSON" || STATE_FAIL=$((STATE_FAIL + 1))
fi

# ---- 3. optional authenticated device detail ----------------------------------------
if [[ "$AUTH" -ne 1 ]]; then
  echo "SKIPPED  authenticated device.list (requires operator credentials; run with --authenticated --user NAME)"
  finish
fi
if [[ -z "$ADMIN" || ! -x "$ADMIN" ]]; then
  echo "INCOMPLETE  rain-core-admin not found (${ADMIN:-not on PATH}); authenticated device.list not done"
  INCOMPLETE=$((INCOMPLETE + 1)); finish
fi
RUNAS=()
if [[ "$(id -u)" -eq 0 ]]; then
  if [[ -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
    echo "INCOMPLETE  --authenticated needs to know your desktop user: run 'sudo bash $0 ${WANT} --authenticated --user ${AUTH_USER}' from your own login (rain-core-admin refuses root)"
    INCOMPLETE=$((INCOMPLETE + 1)); finish
  fi
  RUNAS=(runuser -u "$SUDO_USER" --)
fi
if [[ "$PW_STDIN" -eq 0 ]] && ! { : </dev/tty; } 2>/dev/null; then
  echo "SKIPPED  authenticated device.list (requires operator credentials; no terminal for the password prompt)"
  INCOMPLETE=$((INCOMPLETE + 1)); finish
fi
ADMIN_ARGS=(devices --user "$AUTH_USER" --json --socket "$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import core_checks; print(core_checks.socket_path())' "$HERE")")
[[ "$PW_STDIN" -eq 1 ]] && ADMIN_ARGS+=(--password-stdin)
say "authenticated device.list: rain-core-admin ${ADMIN_ARGS[*]} as ${SUDO_USER:-$(id -un)} (password prompt is rain-core-admin's own)"
if [[ "$PW_STDIN" -eq 1 ]]; then
  ADMIN_OUT="$("${RUNAS[@]}" "$ADMIN" "${ADMIN_ARGS[@]}")"; ADMIN_RC=$?
else
  ADMIN_OUT="$("${RUNAS[@]}" "$ADMIN" "${ADMIN_ARGS[@]}" </dev/null)"; ADMIN_RC=$?
fi
case "$ADMIN_RC" in
  0)
    printf '%s' "$ADMIN_OUT" | "$PYTHON" "$PROJECTION" check-list "$DEVICES_JSON"
    case $? in
      0) ;;
      3) STATE_FAIL=$((STATE_FAIL + 1)) ;;
      *) INCOMPLETE=$((INCOMPLETE + 1)) ;;
    esac ;;
  3) echo "INCOMPLETE  rain-core-admin: authentication or authorization refused (exit 3); rain-core itself is healthy (public checks passed)"
     INCOMPLETE=$((INCOMPLETE + 1)) ;;
  4) echo "INCOMPLETE  rain-core-admin could not reach rain-core as ${SUDO_USER:-$(id -un)} (exit 4: socket permission/group?); public checks passed"
     INCOMPLETE=$((INCOMPLETE + 1)) ;;
  5) echo "INCOMPLETE  rain-core-admin cancelled (exit 5)"; INCOMPLETE=$((INCOMPLETE + 1)) ;;
  *) echo "INCOMPLETE  rain-core-admin exited ${ADMIN_RC}"; INCOMPLETE=$((INCOMPLETE + 1)) ;;
esac
finish
