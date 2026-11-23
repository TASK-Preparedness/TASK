#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Compare built .debs with (1) the .debs delivered earlier (byte identity) and (2) the files installed
on the development Pi (packaging/debian/reference/pi-installed-usr-20261108.sha256), file by file.

    /usr/bin/python3 packaging/debian/verify_debs.py BUILD_DIR [--json OUT.json]

Read-only. It only proves source/payload equality; it is not an installation or hardware test.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF = HERE / "reference"


# Differences that are intended and explained (anything else fails the check).
EXPECTED_DIFF = {
    # new changelog entry for the proposed version; every other file equals the Pi, incl. the modified notifier
    "task-mesh_0.3.2~alpha1_all.deb": {"/usr/share/doc/task-mesh/changelog.gz"},
    # verification rebuild of 0.3.1 with the pre-audio notifier: the Pi carries the hand-modified notifier
    "task-mesh_0.3.1_all.deb": {"/usr/lib/task-mesh/task_mesh/hub/notifier.py"},
    # launcher 0.3.8: Windows portability + /usr/bin/task-console preference (approved 2026-11-23)
    "task-launcher_0.3.8_all.deb": {"/usr/share/doc/task-launcher/changelog.gz",
                                    "/usr/share/task-launcher/task_launcher/__init__.py",
                                    "/usr/share/task-launcher/task_launcher/app.py",
                                    "/usr/share/task-launcher/task_launcher/paths.py",
                                    "/usr/share/task-launcher/task_launcher/registry/manifest.py",
                                    "/usr/share/task-launcher/task_launcher/services/meshbadge.py",
                                    "/usr/share/task-launcher/task_launcher/services/statuscards.py",
                                    "/usr/share/task-launcher/apps.d/090-devices.toml"},
    # proposed Depends fix: only the changelog differs in the payload (control Depends differs too)
    "task-console_0.2.1~alpha1_all.deb": {"/usr/share/doc/task-console/changelog.gz"},
}


def load_sums(path):
    out = {}
    for ln in path.read_text().splitlines():
        if ln and not ln.startswith("#"):
            digest, name = ln.split(None, 1)
            out[name.strip()] = digest
    return out


def payload(deb):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["dpkg-deb", "-x", str(deb), tmp], check=True)
        root = Path(tmp)
        return {"/" + str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    delivered = load_sums(REF / "delivered-debs.sha256")
    installed = load_sums(REF / "pi-installed-usr-20261108.sha256")
    results = []
    for deb in sorted(Path(a.build_dir).glob("*.deb")):
        sha = hashlib.sha256(deb.read_bytes()).hexdigest()
        files = payload(deb)
        common = sorted(set(files) & set(installed))
        allowed = EXPECTED_DIFF.get(deb.name, set())
        differ = [f for f in common if files[f] != installed[f] and f not in allowed]
        expected = [f for f in common if files[f] != installed[f] and f in allowed]
        r = {"deb": deb.name, "sha256": sha,
             "identical_to_delivered": delivered.get(deb.name) == sha if deb.name in delivered else None,
             "payload_files": len(files), "compared_with_pi": len(common),
             "differ_from_pi": differ, "expected_differences": expected, "not_collected_from_pi": len(files) - len(common)}
        results.append(r)
        ident = {True: "byte-identical to delivered", False: "DIFFERS from delivered",
                 None: "new version (no delivered deb)"}[r["identical_to_delivered"]]
        print(f"{deb.name}: {ident}; {len(common)}/{len(files)} payload files compared with the Pi, "
              f"{len(differ)} unexpected and {len(expected)} expected differences")
        for f in expected:
            print(f"    expected difference: {f}")
        for f in differ:
            print(f"    differs from Pi: {f}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2) + "\n")
    bad = [r for r in results if r["identical_to_delivered"] is False or r["differ_from_pi"]]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
