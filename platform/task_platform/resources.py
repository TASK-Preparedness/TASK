# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Offline resource management (read-only discovery + integrity checks), both platforms.

Offline content (ZIM libraries, MBTiles maps, PDFs/EPUBs, firmware later) is always user-supplied: T.A.S.K.
bundles none. This module finds such files where they already are, lists them with sizes, and verifies
them against a SHA-256 manifest. It never moves, copies, renames, modifies or deletes a resource; Kiwix
libraries (e.g. /library on the development Pi) and ZIM files stay exactly as they are.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import LINUX, WINDOWS, current_platform, paths

KINDS = {".zim": "zim", ".mbtiles": "mbtiles", ".pdf": "pdf", ".epub": "epub", ".gpx": "gpx"}
MAX_DEPTH = 6


@dataclass(frozen=True)
class Resource:
    path: str
    kind: str
    size: int


def default_roots(*, env=None, home=None, platform=None) -> list:
    """Where T.A.S.K. modules already look for offline content (read-only)."""
    env = os.environ if env is None else env
    plat = platform or current_platform()
    roots = [paths.data_dir("task-resources", env=env, home=home, platform=plat),
             paths.data_dir("task-maps", env=env, home=home, platform=plat)]
    if plat == LINUX:
        roots += [Path("/library"), Path("/usr/share/task-resources/content")]
    elif plat == WINDOWS:
        prof = env.get("USERPROFILE")
        if prof:
            roots += [PureWindowsPath(prof) / "Documents" / "TASK"]
    return roots


def scan(roots, max_depth: int = MAX_DEPTH) -> list[Resource]:
    """Walk ``roots`` (no symlink following) and list known resource files. Read-only."""
    out: list[Resource] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        base = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if len(Path(dirpath).parts) - base >= max_depth:
                dirnames[:] = []
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for f in sorted(filenames):
                kind = KINDS.get(Path(f).suffix.lower())
                if not kind:
                    continue
                p = Path(dirpath) / f
                try:
                    if p.is_symlink() or not p.is_file():
                        continue
                    out.append(Resource(str(p), kind, p.stat().st_size))
                except OSError:
                    continue
    return out


def sha256(path: os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def parse_manifest(text: str) -> dict[str, str]:
    """``sha256sum`` format: '<hex>  <relative path>' per line."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition(" ")
        name = name.lstrip(" *")
        if len(digest) != 64 or not name or name.startswith(("/", "\\")) or ".." in Path(name).parts:
            raise ValueError(f"bad manifest line: {line!r}")
        out[name] = digest.lower()
    return out


def verify(directory: os.PathLike, manifest_text: str) -> dict[str, str]:
    """Return {name: "ok" | "missing" | "mismatch"} for each manifest entry. Read-only."""
    d = Path(directory)
    res = {}
    for name, digest in parse_manifest(manifest_text).items():
        p = d / name
        if not p.is_file():
            res[name] = "missing"
        else:
            res[name] = "ok" if sha256(p) == digest else "mismatch"
    return res
