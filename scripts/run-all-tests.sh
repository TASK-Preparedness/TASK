#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Run every automated test suite with the Debian system interpreter (no pip, no network).
#   scripts/run-all-tests.sh [LOGDIR]
# Optional: RAIN_020_WHEEL=<path to rain_core-0.2.0-py3-none-any.whl> for core test_77
# (historical update-path test; sha256 253572c5…2bad).
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
LOG=${1:-$ROOT/build/test-logs}
mkdir -p "$LOG"
export QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
PY=/usr/bin/python3
status=0
run() {
  local name=$1 dir=$2; shift 2
  (cd "$dir" && "$@") >"$LOG/$name.log" 2>&1
  local rc=$?
  local summary
  summary=$(grep -E '[0-9]+ (passed|failed|error)' "$LOG/$name.log" | tail -n 1)
  printf '%-16s exit=%-3s %s\n' "$name" "$rc" "$summary" | tee -a "$LOG/SUMMARY.txt"
  [ $rc -eq 0 ] || status=1
}
: >"$LOG/SUMMARY.txt"
PT=(-m pytest -p no:cacheprovider -o addopts= -q -rfEs)
run core        "$ROOT"                     $PY "${PT[@]}" tests
for m in console comms aprs launcher maps resources sdr; do
  run "$m"      "$ROOT/$m"                  $PY "${PT[@]}" tests
done
run release-common "$ROOT/release/common"   $PY "${PT[@]}" tests
run platform    "$ROOT/platform"            $PY "${PT[@]}" tests
run installer   "$ROOT/installers/raspberry-pi" $PY "${PT[@]}" tests
run windows-prep "$ROOT/installers/windows" $PY "${PT[@]}" tests   # Linux-side checks only, NOT a Windows test
run packaging   "$ROOT/packaging/debian" $PY "${PT[@]}" tests   # volunteer guide vs. builder/chroot consistency
run mesh        "$ROOT/mesh"                sh tools/run_tests_debian.sh -o addopts= -q -rfEs
exit $status
