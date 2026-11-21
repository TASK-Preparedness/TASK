#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
#
# Run the whole Phase 2 suite (task-core, then task-console) with Debian trixie packages only
# (test 75, PHASE-2.md section 17.6). No pip installs, no network (test 77 creates a throwaway venv in a temp dir).
#
#   ./run_tests_debian.sh
#
# Needs (Debian trixie):
#   sudo apt-get install python3-pip python3-pytest python3-pytestqt python3-yaml python3-setuptools \
#        python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets \
#        python3-pyside6.qtnetwork python3-pyside6.qttest   (qttest: needed by pytest-qt)
# Runs as a normal user (the task-core tests refuse root, as in Phase 1).
set -euo pipefail
cd "$(dirname "$0")"
PY=/usr/bin/python3
export QT_QPA_PLATFORM=offscreen
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -p no:cacheprovider"
# keep the console tests on Debian's packages: ignore any user site-packages
export PYTHONNOUSERSITE=1

missing=()
for mod in pytest pytestqt yaml setuptools PySide6.QtCore PySide6.QtGui PySide6.QtWidgets PySide6.QtNetwork PySide6.QtTest pip; do
  "$PY" -c "import ${mod}" 2>/dev/null || missing+=("$mod")
done
if (( ${#missing[@]} )); then
  echo "missing Python modules: ${missing[*]}" >&2
  echo "install: sudo apt-get install python3-pip python3-pytest python3-pytestqt python3-yaml python3-setuptools python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtnetwork python3-pyside6.qttest" >&2
  exit 2
fi
for mod in PySide6 pytest pytestqt; do
  where="$("$PY" -c "import ${mod}, os; print(os.path.dirname(${mod}.__file__))")"
  case "$where" in
    /usr/lib/python3/dist-packages*) ;;
    *) echo "${mod} is not the Debian package (${where}); refusing (Debian packages only)" >&2; exit 2 ;;
  esac
done

echo "== task-core ($("$PY" -c 'import pytest; print("pytest", pytest.__version__)'))"
"$PY" -m pytest tests
echo "== task-console"
(cd console && "$PY" -m pytest tests)
echo "== both suites passed"
