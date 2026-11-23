#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Check every Depends/Recommends/Suggests relation of the built debs against the development Pi's
reported package baseline (reference/pi-dpkg-baseline-20261122.txt). Read-only; compares versions with
`dpkg --compare-versions` on the build machine.

    /usr/bin/python3 packaging/debian/check_baseline.py BUILD_DIR [--json OUT]

Each relation gets one status: satisfied (baseline version meets the floor), VIOLATED (installed but
too old, or reported not installed: a Depends violation is an error), bundle (provided by a T.A.S.K.
package in BUILD_DIR), or not-in-baseline (not reported; for Depends this means PENDING confirmation).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "reference/pi-dpkg-baseline-20261122.txt"
REL = re.compile(r"^\s*([a-z0-9][a-z0-9+.-]*)(?::\w+)?\s*(?:\(\s*(<<|<=|=|>=|>>)\s*([^)\s]+)\s*\))?\s*$")


def load_baseline(path=BASELINE):
    b = {}
    for ln in path.read_text().splitlines():
        if ln.strip() and not ln.startswith("#"):
            name, ver = ln.split("\t")
            b[name] = None if ver == "-" else ver
    return b


def cmp(a, op, b):
    ops = {"<<": "lt", "<=": "le", "=": "eq", ">=": "ge", ">>": "gt"}
    return subprocess.run(["dpkg", "--compare-versions", a, ops[op], b]).returncode == 0


def field(deb, name):
    return subprocess.run(["dpkg-deb", "-f", str(deb), name], capture_output=True, text=True).stdout.strip()


def check_alt(alt, baseline, bundle):
    m = REL.match(alt)
    if not m:
        return "unparsable", alt
    name, op, ver = m.groups()
    if name in bundle:
        ok = op is None or cmp(bundle[name], op, ver)
        return ("bundle" if ok else "VIOLATED"), f"bundle has {bundle[name]}"
    if name not in baseline:
        return "not-in-baseline", ""
    have = baseline[name]
    if have is None:
        return "VIOLATED", "reported NOT installed"
    if op is None or cmp(have, op, ver):
        return "satisfied", f"Pi has {have}"
    return "VIOLATED", f"Pi has {have}, needs {op} {ver}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    baseline = load_baseline()
    debs = sorted(Path(a.build_dir).glob("*.deb"))
    bundle = {field(d, "Package"): field(d, "Version") for d in debs}
    rows, errors = [], 0
    rank = {"satisfied": 0, "bundle": 0, "not-in-baseline": 1, "VIOLATED": 2, "unparsable": 2}
    for d in debs:
        pkg = field(d, "Package")
        for f in ("Depends", "Recommends", "Suggests"):
            for group in (g.strip() for g in field(d, f).split(",") if g.strip()):
                results = [(alt.strip(),) + check_alt(alt.strip(), baseline, bundle) for alt in group.split("|")]
                best = min(results, key=lambda r: rank[r[1]])
                status = best[1]
                if f == "Depends" and status in ("VIOLATED", "unparsable"):
                    errors += 1
                rows.append({"package": pkg, "field": f, "relation": group, "status": status, "detail": best[2]})
    for r in rows:
        print(f"{r['status']:<16} {r['package']:<20} {r['field']:<10} {r['relation']}  {r['detail']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"baseline": str(BASELINE.name), "rows": rows, "depends_errors": errors},
                                           indent=1) + "\n")
    print(f"Depends violations: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
