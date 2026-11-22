#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Installer dry-run validation matrix over SIMULATED hosts (fake /proc, /sys, /etc, dpkg roots).

    /usr/bin/python3 installers/raspberry-pi/tools/dryrun_matrix.py --bundle BUILD_DIR --out REPORT_DIR

Nothing is installed; no real device or system file is read except the bundle. Every plan is checked with
plan.assert_safe(). UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from task_installer import __version__, bundle as B, compat, plan as P, preflight as PF  # noqa: E402
from task_installer.detect import detect  # noqa: E402

REPO = HERE.parents[2]
TRIXIE = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nVERSION_ID="13"\nVERSION_CODENAME=trixie\nID=debian\n'
BOOKWORM = 'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\nID=debian\n'
PI_INSTALLED = {"task-core": "0.3.0", "task-core-compat": "0.3.0", "python3-task-comms": "0.3.1", "task-aprs": "0.1.0",
                "task-mesh": "0.3.1", "task-launcher": "0.3.7", "task-console": "0.2.0", "task-maps": "0.1.1",
                "task-resources": "0.2.4", "task-sdr": "0.2.4"}
NOTIFIER = "/usr/lib/task-mesh/task_mesh/hub/notifier.py"

# id, description, device-tree model, cpuinfo revision, MemTotal kB, dpkg arch, kernel, os-release, extras
FIXTURES = [
    ("pi5-dev", "Pi 5 8 GB, Debian 13 arm64, T.A.S.K. installed as on the development Pi (modified notifier)",
     "Raspberry Pi 5 Model B Rev 1.0", "d04170", 8_000_000, "arm64", "aarch64", TRIXIE, {"installed": PI_INSTALLED}),
    ("pi5-clean", "Pi 5 4 GB, clean Debian 13 arm64", "Raspberry Pi 5 Model B Rev 1.0", "c04170", 4_000_000,
     "arm64", "aarch64", TRIXIE, {}),
    ("pi4-4gb", "Pi 4 4 GB, Debian 13 arm64", "Raspberry Pi 4 Model B Rev 1.5", "c03115", 3_900_000, "arm64", "aarch64",
     TRIXIE, {}),
    ("pi4-2gb", "Pi 4 2 GB, Debian 13 arm64", "Raspberry Pi 4 Model B Rev 1.4", "b03114", 1_900_000, "arm64", "aarch64",
     TRIXIE, {}),
    ("pi4-1gb", "Pi 4 1 GB, Debian 13 arm64", "Raspberry Pi 4 Model B Rev 1.1", "a03111", 950_000, "arm64", "aarch64",
     TRIXIE, {}),
    ("pi400", "Pi 400, Debian 13 arm64", "Raspberry Pi 400 Rev 1.0", "c03130", 3_900_000, "arm64", "aarch64", TRIXIE, {}),
    ("pi3bplus", "Pi 3 B+ 1 GB, Debian 13 arm64", "Raspberry Pi 3 Model B Plus Rev 1.3", "a020d3", 950_000, "arm64",
     "aarch64", TRIXIE, {}),
    ("zero2w", "Pi Zero 2 W, Debian 13 arm64", "Raspberry Pi Zero 2 W Rev 1.0", "902120", 430_000, "arm64", "aarch64",
     TRIXIE, {}),
    ("zero-w", "Pi Zero W (ARMv6)", "Raspberry Pi Zero W Rev 1.1", "9000c1", 430_000, "armhf", "armv6l", TRIXIE, {}),
    ("pi5-bookworm", "Pi 5, Debian 12 bookworm arm64", "Raspberry Pi 5 Model B Rev 1.0", "d04170", 8_000_000, "arm64",
     "aarch64", BOOKWORM, {}),
    ("pi4-32bit", "Pi 4, 32-bit userland (armhf) on a 64-bit kernel", "Raspberry Pi 4 Model B Rev 1.4", "c03114",
     3_900_000, "armhf", "aarch64", TRIXIE, {}),
    ("x86-trixie", "x86_64 PC, Debian 13 amd64", None, None, 16_000_000, "amd64", "x86_64", TRIXIE, {}),
    ("arm64-generic", "Generic arm64 board (no Pi device tree), Debian 13", None, None, 4_000_000, "arm64", "aarch64",
     TRIXIE, {}),
    ("pi5-manual-pi4", "Pi 5 detected, user manually selects Pi 4", "Raspberry Pi 5 Model B Rev 1.0", "d04170",
     8_000_000, "arm64", "aarch64", TRIXIE, {"manual": "pi4"}),
    ("x86-manual-pi5", "x86_64 PC, user manually selects Pi 5 (must not bypass)", None, None, 16_000_000, "amd64",
     "x86_64", TRIXIE, {"manual": "pi5"}),
    ("pi5-revision-mismatch", "Device tree says Pi 5, revision code says Zero 2 W", "Raspberry Pi 5 Model B Rev 1.0",
     "902120", 8_000_000, "arm64", "aarch64", TRIXIE, {}),
    ("pi5-pip-console", "Pi 5 with a legacy pip copy in /usr/local/bin/task-console", "Raspberry Pi 5 Model B Rev 1.0",
     "d04170", 8_000_000, "arm64", "aarch64", TRIXIE, {"shadow": True}),
    ("pi5-newer-installed", "Pi 5 with task-launcher 0.3.9 installed (newer than the bundle)",
     "Raspberry Pi 5 Model B Rev 1.0", "d04170", 8_000_000, "arm64", "aarch64", TRIXIE,
     {"installed": dict(PI_INSTALLED, **{"task-launcher": "0.3.9"})}),
]
MODES = [(P.COMPLETE, []), (P.CUSTOM, ["mesh", "maps"]), (P.MINIMAL, [])]


def build_root(tmp, fx):
    fid, _, model, rev, mem, arch, _kernel, osr, extra = fx
    r = Path(tmp) / fid
    (r / "proc/device-tree").mkdir(parents=True)
    if model:
        (r / "proc/device-tree/model").write_text(model + "\x00")
    (r / "proc/meminfo").write_text(f"MemTotal:       {mem} kB\n")
    if rev:
        (r / "proc/cpuinfo").write_text(f"processor\t: 0\nRevision\t: {rev}\n")
    (r / "etc").mkdir()
    (r / "etc/os-release").write_text(osr)
    (r / "var/lib/dpkg").mkdir(parents=True)
    (r / "var/lib/dpkg/arch-native").write_text(arch + "\n")
    inst = extra.get("installed", {})
    (r / "var/lib/dpkg/status").write_text("".join(
        f"Package: {n}\nStatus: install ok installed\nVersion: {v}\nArchitecture: all\n\n" for n, v in inst.items()))
    verify = None
    if "task-mesh" in inst:
        n = r / NOTIFIER.lstrip("/")
        n.parent.mkdir(parents=True)
        shutil.copy(REPO / "mesh/task_mesh/hub/notifier.py", n)   # == the Pi's hand-modified file
        verify = f"??5??????   {NOTIFIER}\n"
    if extra.get("shadow"):
        (r / "usr/local/bin").mkdir(parents=True)
        (r / "usr/local/bin/task-console").write_text("#!/usr/bin/python3\n")
    return r, verify


def run(bundle_dir, out):
    bnd = B.load(bundle_dir) if bundle_dir else None
    rows, details = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for fx in FIXTURES:
            fid, desc, *_rest = fx
            kernel, extra = fx[6], fx[8]
            root, verify = build_root(tmp, fx)
            facts = detect(root, env={"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}, kernel_machine=kernel)
            v = compat.evaluate(facts, extra.get("manual"))
            entry = {"id": fid, "description": desc, "detected_model": facts.model, "family": facts.pi_family,
                     "revision": facts.revision, "revision_family": facts.revision_family, "arch": facts.dpkg_arch,
                     "os": facts.os_pretty, "compatible": v.ok, "profile": v.profile, "blockers": v.blockers,
                     "warnings": v.warnings, "modes": {}}
            for mode, ids in MODES:
                res = {}
                try:
                    mods = P.select(mode, v, ids)
                    pkgs = P._packages(mods)
                    pf = PF.check(facts, pkgs, bnd, verify, root)
                    res["preflight_ok"] = pf.ok
                    res["preflight_blockers"] = pf.blockers
                    res["preflight_warnings"] = pf.warnings
                    res["packages"] = pkgs
                    if pf.ok:
                        installed = facts.installed_task_packages
                        if installed:
                            pl = P.update_plan(installed, [m for m in mods if any(p in installed for p in m.packages)],
                                               bnd, pf)
                        else:
                            pl = P.install_plan(mods, v, P.SOURCE_OFFLINE, bundle=bnd, preflight=pf)
                        P.assert_safe(pl)
                        res["result"] = f"{pl.action} plan, {len(pl.steps)} steps, assert_safe OK"
                        res["steps"] = [" ".join(s.argv) for s in pl.steps]
                    else:
                        res["result"] = "refused by preflight"
                except PermissionError as e:
                    res["result"] = "refused (host not compatible)"
                    res["error"] = str(e)
                except ValueError as e:
                    res["result"] = "refused (mode not allowed on this board)"
                    res["error"] = str(e)
                entry["modes"][mode] = res
            if facts.installed_task_packages:
                inst = facts.installed_task_packages
                pf = PF.check(facts, sorted(inst), bnd, verify, root, action="repair")
                extra_plans = {"repair": P.repair_plan(inst, bnd, pf), "uninstall": P.uninstall_plan(inst),
                               "recovery": P.recovery_plan(inst, None)}
                entry["maintenance"] = {}
                for k, pl in extra_plans.items():
                    P.assert_safe(pl)
                    entry["maintenance"][k] = {"steps": [" ".join(s.argv) for s in pl.steps], "notes": pl.notes}
            details.append(entry)
            rows.append(entry)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dryrun-matrix.json").write_text(json.dumps({"installer": __version__, "bundle": str(bundle_dir),
                                                       "fixtures": details}, indent=2) + "\n")
    L = [f"# Installer dry-run validation matrix (task_installer {__version__})", "",
         "SIMULATED hosts only (fake /proc, /sys, /etc and dpkg roots). Nothing was installed. Every generated plan "
         "passed `plan.assert_safe()` (no purge/autoremove/enable/restart/flash/pip/rm). "
         "**UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST.**", "",
         f"Bundle: `{bundle_dir}` (real Milestone B .debs, checksums verified by the installer)" if bnd else "Bundle: none", "",
         "| Fixture | Host | Compatible | Profile | Complete | Custom (mesh, maps) | Minimal |", "|---|---|---|---|---|---|---|"]
    for e in rows:
        cells = []
        for mode, _ in MODES:
            r = e["modes"][mode]
            cells.append(r["result"])
        L.append(f"| `{e['id']}` | {e['description']} | {'yes' if e['compatible'] else 'NO'} | {e['profile']} | "
                 + " | ".join(cells) + " |")
    L += ["", "## Details", ""]
    for e in rows:
        L.append(f"### `{e['id']}` — {e['description']}")
        L.append(f"* Detected: model `{e['detected_model']}`, family `{e['family']}`, revision `{e['revision']}` "
                 f"({e['revision_family']}), userland `{e['arch']}`, OS `{e['os']}`")
        for b in e["blockers"]:
            L.append(f"* BLOCKER: {b}")
        for w in e["warnings"]:
            L.append(f"* warning: {w}")
        for mode, _ in MODES:
            r = e["modes"][mode]
            L.append(f"* **{mode}**: {r['result']}")
            for b in r.get("preflight_blockers", []):
                L.append(f"  * preflight BLOCKER: {b}")
            for w in r.get("preflight_warnings", []):
                L.append(f"  * preflight warning: {w}")
            if mode == P.COMPLETE and r.get("steps"):
                L.append("  * steps: " + "; ".join(f"`{s}`" for s in r["steps"]))
        for k, m in e.get("maintenance", {}).items():
            L.append(f"* **{k}**: " + "; ".join(f"`{s}`" for s in m["steps"]))
        L.append("")
    (out / "DRYRUN-MATRIX.md").write_text("\n".join(L) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = run(a.bundle, Path(a.out))
    for e in rows:
        print(f"{e['id']:24} compatible={'yes' if e['compatible'] else 'NO ':3} profile={e['profile']:13} " +
              " | ".join(f"{m}: {e['modes'][m]['result']}" for m, _ in MODES))


if __name__ == "__main__":
    main()
