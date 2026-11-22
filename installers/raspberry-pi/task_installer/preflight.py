# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Pre-installation conflict detection (read-only).

Finds, before anything is planned:
* downgrades (installed version newer than the bundle) -> blocker;
* corrupt or incomplete offline bundles -> blocker;
* packages a selected module needs that the bundle does not contain -> blocker;
* locally modified package files (``dpkg --verify``) that an upgrade or re-install would overwrite
  -> the plan gets a backup step first (e.g. the hand-modified Mesh notifier);
* pip/legacy copies under /usr/local/bin that would shadow the packaged programs;
* legacy R.A.I.N. packages still installed.
Nothing here opens a device, starts or stops a service or writes a file.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import debver

# Files intentionally modified on the development Pi that a newer package now ships as maintained source.
MAINTAINED = {
    "/usr/lib/task-mesh/task_mesh/hub/notifier.py": (
        "task-mesh", "0.3.2~alpha1", "2864d2425cee7be738863139f4edb1a6d9fd83345693a5690503a46c933bbe1a"),
}
LEGACY = {"rain-core": "replaced by task-core (run task-core-migrate; see MIGRATION.md)",
          "rain-console": "replaced by task-console", "rain-mesh": "replaced by task-mesh (handled by Breaks/Replaces)"}


@dataclass
class Preflight:
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)   # need a backup before install
    upgrades: dict[str, tuple[str, str]] = field(default_factory=dict)
    reinstalls: dict[str, str] = field(default_factory=dict)
    downgrades: dict[str, tuple[str, str]] = field(default_factory=dict)
    fresh: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers


def parse_dpkg_verify(text: str | None) -> list[str]:
    """Paths whose checksum differs ('5' in column 3 of dpkg --verify output)."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^(\S{9})\s+(?:c\s+)?(/\S.*)$", line.rstrip())
        if m and len(m.group(1)) >= 3 and m.group(1)[2] == "5":
            out.append(m.group(2))
    return out


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _owner(path: str, candidates, root) -> str | None:
    """Which of ``candidates`` owns ``path`` (read-only: /var/lib/dpkg/info/<pkg>.list)."""
    info = Path(root) / "var/lib/dpkg/info"
    for pkg in candidates:
        for name in (f"{pkg}.list", f"{pkg}:all.list", f"{pkg}:arm64.list"):
            f = info / name
            try:
                if path in f.read_text().splitlines():
                    return pkg
            except OSError:
                continue
    m = MAINTAINED.get(path)
    if m and m[0] in candidates:
        return m[0]
    return None


def check(facts, packages: list[str], bundle=None, dpkg_verify_text: str | None = None, root="/",
          action: str = "install") -> Preflight:
    """``action``: "install"/"update" overwrite files only of packages that are upgraded (apt keeps an
    identical version as is); "repair" re-installs identical versions too."""
    pf = Preflight()
    installed = facts.installed_packages
    if bundle is not None:
        for prob in bundle.verify():
            pf.blockers.append(f"offline bundle: {prob}")
        for p in packages:
            if p not in bundle.packages:
                pf.blockers.append(f"offline bundle does not contain {p}")
    for p in packages:
        new = bundle.packages[p].version if bundle is not None and p in bundle.packages else None
        old = installed.get(p)
        if old is None:
            pf.fresh.append(p)
        elif new is None:
            continue
        else:
            c = debver.compare(new, old)
            if c > 0:
                pf.upgrades[p] = (old, new)
            elif c == 0:
                pf.reinstalls[p] = old
            else:
                pf.downgrades[p] = (old, new)
                pf.blockers.append(f"{p}: installed {old} is newer than the bundle's {new}; downgrades are refused")
    touched = set(pf.upgrades) | (set(pf.reinstalls) if action == "repair" else set())
    for path in parse_dpkg_verify(dpkg_verify_text):
        owner = _owner(path, touched, root)
        if owner is None and (Path(root) / "var/lib/dpkg/info").is_dir() and \
                any((Path(root) / "var/lib/dpkg/info").glob("*.list")):
            continue  # owned by a package this plan does not overwrite
        if owner is None and path not in MAINTAINED and touched:
            owner = "unknown"  # cannot tell: back it up to be safe
        if owner is None:
            continue
        pf.modified_files.append(path)
        m = MAINTAINED.get(path)
        current = _sha256(Path(root) / path.lstrip("/"))
        if m and m[0] in pf.upgrades and debver.compare(pf.upgrades[m[0]][1], m[1]) >= 0 and current == m[2]:
            pf.warnings.append(f"{path} is locally modified; {m[0]} {pf.upgrades[m[0]][1]} ships this same "
                               "modification as maintained source. It is still backed up first.")
        else:
            pf.warnings.append(f"{path} is locally modified and would be overwritten by an upgrade or re-install; "
                               "it is backed up first (restore it yourself if wanted).")
    for f in facts.shadowing_files:
        pf.warnings.append(f"{f} exists (pip or legacy install) and comes before /usr/bin on PATH, so it would "
                           "shadow the packaged program. Remove it with its own uninstaller.")
    for pkg, why in LEGACY.items():
        if pkg in installed:
            pf.warnings.append(f"legacy package {pkg} {installed[pkg]} is installed: {why}.")
    return pf
