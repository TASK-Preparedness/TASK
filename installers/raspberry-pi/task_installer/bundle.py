# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Offline bundle manifest (BUNDLE.json, written by packaging/debian/build_debs.py).

The manifest names every .deb exactly (no globs at run time), with version, SHA-256 and the
package's own Depends line. ``verify()`` re-hashes the files in Python before any plan uses them.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BundlePackage:
    name: str
    version: str
    file: str
    sha256: str
    depends: str = ""


@dataclass
class Bundle:
    directory: Path
    packages: dict[str, BundlePackage]
    label: str = ""

    def file_for(self, name: str) -> Path:
        return self.directory / self.packages[name].file

    def verify(self) -> list[str]:
        """Return problems: missing files or checksum mismatches (empty list = OK)."""
        problems = []
        for p in self.packages.values():
            f = self.directory / p.file
            if not f.is_file():
                problems.append(f"missing {p.file}")
                continue
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != p.sha256:
                problems.append(f"checksum mismatch: {p.file}")
        return problems


def load(directory: str | Path) -> Bundle:
    d = Path(directory)
    data = json.loads((d / "BUNDLE.json").read_text())
    pkgs = {}
    for e in data["packages"]:
        if "/" in e["file"] or e["file"].startswith("."):
            raise ValueError(f"unsafe file name in manifest: {e['file']!r}")
        pkgs[e["name"]] = BundlePackage(e["name"], e["version"], e["file"], e["sha256"], e.get("depends", ""))
    return Bundle(d, pkgs, data.get("label", ""))
