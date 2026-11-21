#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# Build the development .deb: copies the source tree (without VCS/venv/caches) to a temporary
# build directory, adds packaging/debian as ./debian and runs dpkg-buildpackage.
# Usage: packaging/build-deb.sh [extra dpkg-buildpackage args, e.g. -aarm64 -d]
set -eu
SRC=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^task-mesh (\([^)]*\)).*/\1/p' "$SRC/packaging/debian/changelog" | head -1)
OUT=${OUT:-$SRC/dist}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
TREE="$WORK/task-mesh-$VERSION"
mkdir -p "$TREE" "$OUT"
tar -C "$SRC" --exclude=.git --exclude=.venv --exclude=dist --exclude=__pycache__ \
    --exclude=.pytest_cache -cf - . | tar -C "$TREE" -xf -
cp -a "$SRC/packaging/debian" "$TREE/debian"
(cd "$TREE" && dpkg-buildpackage -b -us -uc "$@")
cp "$WORK"/*.deb "$OUT"/
for f in "$WORK"/*.buildinfo "$WORK"/*.changes; do [ -e "$f" ] && cp "$f" "$OUT"/; done
ls -l "$OUT"
