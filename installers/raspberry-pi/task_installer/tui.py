# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Text installer (headless fallback) and command-line entry point.

    python3 -m task_installer detect            # read-only hardware/OS report
    python3 -m task_installer plan --mode minimal
    python3 -m task_installer tui               # interactive, dry run
    python3 -m task_installer gui               # PySide6 wizard, dry run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from . import __version__
from .catalog import CATALOG, INSTALLABLE
from .compat import MODELS, evaluate
from .detect import detect
from .executor import DryRunExecutor
from .plan import (COMPLETE, CUSTOM, MINIMAL, SOURCE_OFFLINE, SOURCE_ONLINE, install_plan, recovery_plan, repair_plan,
                   select, uninstall_plan, update_plan, _packages)
from . import bundle as _bundle, preflight as _preflight

BANNER = f"T.A.S.K. Raspberry Pi installer {__version__} (pre-alpha, DRY RUN ONLY)"


def render_preflight(pre) -> str:
    L = ["Preflight: " + ("OK" if pre.ok else "BLOCKED")]
    L += [f"  BLOCKER: {b}" for b in pre.blockers]
    L += [f"  warning: {w}" for w in pre.warnings]
    L += [f"  new install: {p}" for p in pre.fresh]
    L += [f"  upgrade: {p} {o} -> {n}" for p, (o, n) in sorted(pre.upgrades.items())]
    L += [f"  same version (re-install only if repairing): {p} {v}" for p, v in sorted(pre.reinstalls.items())]
    L += [f"  locally modified (backed up first): {f}" for f in pre.modified_files]
    return "\n".join(L)


def _dpkg_verify_text(a, facts):
    """Read-only. Fixture file if given; on the real system run `dpkg --verify` for installed T.A.S.K. packages."""
    if a.dpkg_verify:
        with open(a.dpkg_verify, encoding="utf-8") as fh:
            return fh.read()
    if facts.simulated or not facts.installed_task_packages:
        return None
    import shutil
    import subprocess
    if not shutil.which("dpkg"):
        return None
    try:
        r = subprocess.run(["dpkg", "--verify"] + sorted(facts.installed_task_packages), capture_output=True,
                           text=True, timeout=60, check=False)  # noqa: S603 - read-only query, argv list
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout


def report(facts, verdict) -> str:
    L = [BANNER, "", "Detected (read-only):"]
    L.append(f"  Board:        {facts.model or 'not detected'}")
    if facts.revision:
        L.append(f"  Revision:     {facts.revision} ({facts.revision_family or 'unknown type'}, "
                 f"{facts.revision_mem_mib or '?'} MiB)")
    L.append(f"  Architecture: userland {facts.dpkg_arch or 'unknown'}, kernel {facts.kernel_machine}")
    L.append(f"  OS:           {facts.os_pretty or 'unknown'}")
    L.append(f"  RAM:          {facts.mem_total_mib or '?'} MiB   Free disk: {facts.disk_free_mib or '?'} MiB")
    L.append(f"  Desktop:      {facts.desktop or 'none'} ({facts.session_type or 'no session'})")
    known = [u for u in facts.usb if u.kind]
    L.append(f"  USB devices:  {len(facts.usb)} ({len(known)} recognised, none opened)")
    for u in known:
        L.append(f"    - {u.usb_id} {u.description}")
    L.append(f"  Bluetooth:    {', '.join(facts.bluetooth_adapters) or 'no adapter'} (not scanned)")
    inst = facts.installed_task_packages
    L.append(f"  Installed T.A.S.K. packages: {', '.join(f'{k} {v}' for k, v in sorted(inst.items())) or 'none'}")
    L.append("")
    L.append("Compatibility: " + ("OK" if verdict.ok else "NOT COMPATIBLE"))
    if verdict.model:
        L.append(f"  Model status: {verdict.model.label}: {verdict.model.status}")
    for b in verdict.blockers:
        L.append(f"  BLOCKER: {b}")
    for w in verdict.warnings:
        L.append(f"  warning: {w}")
    return "\n".join(L)


def _ask(prompt, choices, inp=input, out=print):
    while True:
        a = inp(f"{prompt} [{'/'.join(choices)}]: ").strip().lower()
        if a in choices:
            return a
        out("Please type one of: " + ", ".join(choices))


def interactive(facts, inp=input, out=print, manual=None) -> int:
    verdict = evaluate(facts, manual)
    out(report(facts, verdict))
    if verdict.model is None or _ask("Is the detected board correct?", ["y", "n"], inp, out) == "n":
        fams = [f for f, m in MODELS.items() if m.status != "unsupported"]
        manual = _ask("Select your board", fams, inp, out)
        verdict = evaluate(facts, manual)
        out(report(facts, verdict))
    if not verdict.ok:
        out("Installation cannot continue on this system. Nothing was changed.")
        return 2
    inst = facts.installed_task_packages
    actions = ["install"] + (["repair", "update", "uninstall"] if inst else []) + ["quit"]
    action = _ask("What would you like to do?", actions, inp, out)
    if action == "quit":
        return 0
    if action == "repair":
        plan = repair_plan(inst)
    elif action == "uninstall":
        plan = uninstall_plan(inst)
    else:
        modes = [MINIMAL] if verdict.profile == "minimal-only" else [COMPLETE, CUSTOM, MINIMAL]
        mode = _ask("Installation type", modes, inp, out)
        ids = []
        if mode == CUSTOM:
            out("Modules (maturity shown honestly; planned modules cannot be selected):")
            for m in CATALOG:
                tag = "" if m.maturity in INSTALLABLE else "  (not available)"
                out(f"  {m.id:16} {m.name} {m.version} [{m.maturity}]{tag}")
            raw = inp("Module ids, separated by spaces: ")
            ids = raw.split()
        try:
            mods = select(mode, verdict, ids)
        except (ValueError, KeyError) as e:
            out(f"Cannot plan: {e}")
            return 2
        plan = update_plan(inst, mods) if action == "update" else install_plan(mods, verdict, SOURCE_OFFLINE)
    out(plan.render())
    if _ask("Run this plan now (dry run only in this version)?", ["y", "n"], inp, out) == "y":
        DryRunExecutor(out).run(plan)
        out("Dry run complete. Nothing was installed or changed.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="task-installer", description=BANNER)
    ap.add_argument("--root", default="/", help="filesystem root to inspect (for simulation)")
    ap.add_argument("--model", help="manually select board family (cannot bypass architecture/OS checks)")
    ap.add_argument("--bundle", help="offline bundle directory containing BUNDLE.json and the .debs")
    ap.add_argument("--dpkg-verify", help="file with `dpkg --verify` output (default: run it read-only on the real system)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("--mode", choices=[COMPLETE, CUSTOM, MINIMAL], default=COMPLETE)
    pf.add_argument("--modules", nargs="*", default=[])
    for name in ("repair", "update", "uninstall", "recovery"):
        sp = sub.add_parser(name)
        if name == "update":
            sp.add_argument("--mode", choices=[COMPLETE, CUSTOM, MINIMAL], default=COMPLETE)
            sp.add_argument("--modules", nargs="*", default=[])
        if name == "recovery":
            sp.add_argument("--previous-bundle")
    d = sub.add_parser("detect")
    d.add_argument("--json", action="store_true")
    p = sub.add_parser("plan")
    p.add_argument("--mode", choices=[COMPLETE, CUSTOM, MINIMAL], default=MINIMAL)
    p.add_argument("--modules", nargs="*", default=[])
    p.add_argument("--online", action="store_true")
    sub.add_parser("tui")
    sub.add_parser("gui")
    a = ap.parse_args(argv)
    facts = detect(a.root)
    bnd = _bundle.load(a.bundle) if a.bundle else None
    verify_text = _dpkg_verify_text(a, facts)
    if a.cmd == "detect":
        verdict = evaluate(facts, a.model)
        if a.json:
            print(json.dumps({"facts": asdict(facts), "ok": verdict.ok, "blockers": verdict.blockers,
                              "warnings": verdict.warnings}, indent=2, default=str))
        else:
            print(report(facts, verdict))
        return 0 if verdict.ok else 2
    if a.cmd == "plan":
        verdict = evaluate(facts, a.model)
        if not verdict.ok:
            print(report(facts, verdict))
            return 2
        mods = select(a.mode, verdict, a.modules)
        pre = _preflight.check(facts, _packages(mods), bnd, verify_text, a.root)
        if not pre.ok:
            print("\n".join(f"BLOCKER: {b}" for b in pre.blockers))
            return 2
        print(install_plan(mods, verdict, SOURCE_ONLINE if a.online else SOURCE_OFFLINE, bundle=bnd,
                           preflight=pre).render())
        return 0
    if a.cmd in ("preflight", "update"):
        verdict = evaluate(facts, a.model)
        if not verdict.ok:
            print(report(facts, verdict))
            return 2
        mods = select(a.mode, verdict, a.modules)
        pre = _preflight.check(facts, _packages(mods), bnd, verify_text, a.root)
        if a.cmd == "preflight":
            print(render_preflight(pre))
            return 0 if pre.ok else 2
        if not pre.ok:
            print(render_preflight(pre))
            return 2
        print(update_plan(facts.installed_task_packages, mods, bnd, pre).render())
        return 0
    if a.cmd == "repair":
        inst = facts.installed_task_packages
        pre = _preflight.check(facts, sorted(inst), bnd, verify_text, a.root, action="repair")
        print(repair_plan(inst, bnd, pre).render())
        return 0
    if a.cmd == "uninstall":
        print(uninstall_plan(facts.installed_task_packages).render())
        return 0
    if a.cmd == "recovery":
        prev = _bundle.load(a.previous_bundle) if a.previous_bundle else None
        print(recovery_plan(facts.installed_task_packages, prev).render())
        return 0
    if a.cmd == "gui":
        from .gui import run_gui
        return run_gui(facts, a.model, bnd, verify_text, a.root)
    return interactive(facts, manual=a.model)


if __name__ == "__main__":
    sys.exit(main())
