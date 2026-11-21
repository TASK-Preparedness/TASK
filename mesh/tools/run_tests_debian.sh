#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Run the test suite with ONLY Debian python3-* packages + the vendored meshtastic wheel
# (isolated interpreter, explicit sys.path — the same mechanism as the .deb launcher). AT-26.
# Needs: python3-pytest python3-pytestqt python3-pytest-timeout python3-pyside6.qttest + runtime deps.
# Usage: tools/run_tests_debian.sh [pytest args...]
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VENDOR=$(mktemp -d)
trap 'rm -rf "$VENDOR"' EXIT
(cd "$ROOT/packaging/vendor" && sha256sum -c --quiet SHA256SUMS)
# extract every pinned, checksum-verified vendored wheel (meshtastic, meshcore, pycayennelpp,
# pyserial-asyncio-fast), matching what packaging/build-deb.sh ships in task_mesh/_vendor
for whl in "$ROOT"/packaging/vendor/*.whl; do
  /usr/bin/python3 -I -S -m zipfile -e "$whl" "$VENDOR"
done
rm -rf "$VENDOR/meshtastic/tests" "$VENDOR/meshtastic/analysis"
cd "$ROOT"
export QT_QPA_PLATFORM=offscreen
exec /usr/bin/python3 -I -S -c '
import sys
root, vendor = sys.argv[1], sys.argv[2]
sys.path[:0] = [root, vendor]
sys.path.append("/usr/lib/python3/dist-packages")
import pytest
sys.exit(pytest.main(["-p", "no:cacheprovider"] + sys.argv[3:]))
' "$ROOT" "$VENDOR" "$@"
