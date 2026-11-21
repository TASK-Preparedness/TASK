# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Manifest discovery with deterministic precedence and reported problems.

Directories, in order (MANIFEST-SPEC.md section 'Discovery and trust'):

1. ``/usr/share/task-launcher/apps.d``   trust=package (Debian package, root-owned)
2. ``/etc/task-launcher/apps.d``         trust=admin   (local administrator)
3. ``~/.local/share/task-launcher/apps.d`` trust=user  (this user only)

Rules: files ``*.toml`` sorted by name; within one directory the first file with an ID wins and later
duplicates are rejected; an admin manifest replaces a package manifest with the same ID (reported);
a user manifest can never replace a package/admin ID (rejected, reported).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from task_launcher import paths
from task_launcher.registry.manifest import ManifestError, load_file

MAX_MANIFESTS_PER_DIR = 256


@dataclass
class Problem:
    path: Path
    reason: str
    id: str = None
    severity: str = "error"   # error = rejected; info = replaced/overridden


BUNDLED_APPS_DIR = Path(__file__).resolve().parent.parent / "data" / "apps.d"


def default_dirs():
    package = paths.SYSTEM_APPS_DIRS[0]
    if not package.is_dir():
        package = BUNDLED_APPS_DIR   # running from a source checkout (the .deb installs the system dir)
    return [(package, "package"), (paths.SYSTEM_APPS_DIRS[1], "admin"),
            (paths.user_apps_dir(), "user")]


def discover(dirs=None):
    """Return (manifests_by_id: dict, problems: list[Problem])."""
    dirs = default_dirs() if dirs is None else dirs
    chosen, problems = {}, []
    for directory, trust in dirs:
        directory = Path(directory)
        try:
            names = sorted(n for n in os.listdir(directory) if n.endswith(".toml") and not n.startswith("."))
        except OSError:
            continue
        if len(names) > MAX_MANIFESTS_PER_DIR:
            problems.append(Problem(directory, f"more than {MAX_MANIFESTS_PER_DIR} manifests; extra files ignored"))
            names = names[:MAX_MANIFESTS_PER_DIR]
        seen_here = {}
        for name in names:
            path = directory / name
            try:
                m = load_file(path, trust)
            except ManifestError as exc:
                problems.append(Problem(path, str(exc)))
                continue
            except OSError as exc:
                problems.append(Problem(path, f"unreadable: {exc.strerror or exc}"))
                continue
            if m.id in seen_here:
                problems.append(Problem(path, f"duplicate id {m.id!r} (already defined by {seen_here[m.id].name})", m.id))
                continue
            seen_here[m.id] = path
            previous = chosen.get(m.id)
            if previous is not None:
                if trust == "user":
                    problems.append(Problem(path, f"user manifest cannot replace system id {m.id!r} "
                                                  f"(defined by {previous.path})", m.id))
                    continue
                problems.append(Problem(previous.path, f"id {m.id!r} replaced by administrator manifest {path}",
                                        m.id, severity="info"))
            chosen[m.id] = m
    return chosen, problems
