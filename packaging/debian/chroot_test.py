#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Install/upgrade/remove/purge tests of the built .debs in a throwaway Debian 13 arm64 chroot
(qemu-user emulation on a build machine). piuparts-style leftover checks. BUILD MACHINE ONLY.

    sudo /usr/bin/python3 packaging/debian/chroot_test.py --base BASE.tar --debs BUILD_DIR \\
         [--reference-debs DIR] [--installer installers/raspberry-pi] --work WORKDIR --log LOGDIR

BASE.tar: `mmdebstrap --variant=apt --arch=arm64 --include=python3 trixie BASE.tar <debian mirrors>`.
What this proves: the packages install, resolve their Depends from Debian 13 arm64 (main), import and
byte-compile under the arm64 python3, and remove/purge cleanly. What it does NOT prove: anything about
Raspberry Pi hardware, Raspberry Pi OS (archive.raspberrypi.com) package versions, a desktop session,
USB devices, audio, or radios. It must never be pointed at a real system root.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "DEBIAN_FRONTEND": "noninteractive", "LANG": "C.UTF-8",
       "HOME": "/root", "QT_QPA_PLATFORM": "offscreen"}
VOLATILE = ("proc", "dev", "sys", "tmp", "run", "var/cache", "var/lib/apt", "var/log", "var/lib/dpkg",
            "root", "var/tmp", "etc/ld.so.cache", "var/lib/systemd/deb-systemd", "work")
SMOKE = {
    "python3-task-comms": "import task_comms, task_comms.txpolicy, task_comms.notifications",
    "task-core": "import task_core, task_core.main, task_core.admin, task_core_migrate",
    "task-console": "import sys; sys.path.insert(0, '/usr/lib/task-console'); import task_console.app",
    "task-aprs": "import sys; sys.path.insert(0, '/usr/lib/task-aprs'); import task_aprs.app",
    "task-sdr": "import sys; sys.path.insert(0, '/usr/lib/task-sdr'); import task_sdr.app",
    "task-launcher": "import sys; sys.path.insert(0, '/usr/share/task-launcher'); import task_launcher.app",
    "task-maps": "import sys; sys.path.insert(0, '/usr/share/task-maps'); import task_maps.app",
    "task-resources": "import sys; sys.path.insert(0, '/usr/share/task-resources'); import task_resources.app",
}
MESH_SMOKE = ("import sys; sys.path[:0] = ['/usr/lib/task-mesh', '/usr/lib/task-mesh/task_mesh/_vendor']; "
              "sys.path.append('/usr/lib/python3/dist-packages'); import task_mesh.app, task_mesh.service, "
              "task_mesh.notify_setup, meshtastic")
PI_NOTIFIER_SHA = "2864d2425cee7be738863139f4edb1a6d9fd83345693a5690503a46c933bbe1a"


class Chroot:
    def __init__(self, base, work, name, log):
        self.dir = Path(work) / name
        self.log = open(Path(log) / f"{name}.log", "w")
        self.mounted = []
        if self.dir.exists():
            subprocess.run(["rm", "-rf", "--one-file-system", str(self.dir)], check=True)
        self.dir.mkdir(parents=True)
        subprocess.run(["tar", "-xf", str(base), "-C", str(self.dir)], check=True)
        shutil.copy("/etc/resolv.conf", self.dir / "etc/resolv.conf")
        pol = self.dir / "usr/sbin/policy-rc.d"   # standard chroot guard: never start services
        pol.write_text("#!/bin/sh\nexit 101\n")
        pol.chmod(0o755)
        for fs, args in (("proc", ["-t", "proc", "proc"]), ("dev", ["--bind", "/dev"])):
            subprocess.run(["mount"] + args + [str(self.dir / fs)], check=True)
            self.mounted.append(self.dir / fs)
        (self.dir / "work").mkdir()

    def close(self):
        for m in reversed(self.mounted):
            subprocess.run(["umount", "-l", str(m)], check=False)
        self.log.close()

    def run(self, argv, check=True, cwd="/"):
        self.log.write(f"\n$ {' '.join(argv)}   (cwd {cwd})\n")
        self.log.flush()
        t = time.time()
        r = subprocess.run(["chroot", str(self.dir), "/usr/bin/env", "-i"] + [f"{k}={v}" for k, v in ENV.items()]
                           + ["/bin/sh", "-c", 'cd "$0" && exec "$@"', cwd] + list(argv),
                           capture_output=True, text=True)
        self.log.write(r.stdout + r.stderr + f"[exit {r.returncode}, {time.time() - t:.1f}s]\n")
        self.log.flush()
        if check and r.returncode != 0:
            raise RuntimeError(f"{argv} failed with {r.returncode}; see {self.log.name}")
        return r

    def local_repo(self, rel="/work/debs"):
        """Flat file repository so apt can resolve T.A.S.K.-to-T.A.S.K. Depends (e.g. task-core-compat ->
        task-core) when one package is installed alone. trusted=yes only inside this throwaway chroot."""
        d = self.dir / rel.lstrip("/")
        pk = subprocess.run(["dpkg-scanpackages", "--multiversion", "."], cwd=d, check=True, capture_output=True,
                            text=True).stdout
        (d / "Packages").write_text(pk)
        (self.dir / "etc/apt/sources.list.d/task-local.list").write_text(f"deb [trusted=yes] file:{rel} ./\n")

    def put(self, src, dest):
        d = self.dir / dest.lstrip("/")
        d.parent.mkdir(parents=True, exist_ok=True)
        if Path(src).is_dir():
            shutil.copytree(src, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
        else:
            shutil.copy(src, d)

    def snapshot(self):
        out = set()
        for p in self.dir.rglob("*"):
            rel = str(p.relative_to(self.dir))
            if any(rel == v or rel.startswith(v + "/") for v in VOLATILE):
                continue
            if p.is_file() or p.is_symlink():
                out.add("/" + rel)
        return out

    def owned(self):
        out = set()
        for f in (self.dir / "var/lib/dpkg/info").glob("*.list"):
            out.update(ln.strip() for ln in f.read_text().splitlines() if ln.strip())
        return out

    def sha(self, path):
        return hashlib.sha256((self.dir / path.lstrip("/")).read_bytes()).hexdigest()


def dep_groups(debs, fields=("Depends",), exclude=()):
    """Dependency groups of the given debs (as apt-get satisfy arguments), without groups that name one of
    `exclude` (our own packages). Used to install dependencies BEFORE the leftover snapshot, so that files
    created by dependency maintainer scripts (fonts, certificates, alternatives, .pyc) are not blamed on
    the package under test."""
    groups = []
    for d in debs:
        for f in fields:
            v = subprocess.run(["dpkg-deb", "-f", str(d), f], capture_output=True, text=True).stdout.strip()
            for g in (x.strip() for x in v.split(",") if x.strip()):
                if not any(alt.strip().split()[0] in exclude for alt in g.split("|")) and g not in groups:
                    groups.append(g)
    return groups


def payload_files(deb):
    r = subprocess.run(["dpkg-deb", "-c", str(deb)], check=True, capture_output=True, text=True)
    out = []
    for ln in r.stdout.splitlines():
        parts = ln.split()
        if parts[0][0] in "-l":
            out.append(parts[5][1:])
    return out


def check_policy(c, results, label):
    """No enabled units, no autostart, no files in /home created by packages."""
    probs = []
    for d in ("etc/systemd/system", "etc/systemd/user", "etc/xdg/autostart"):
        base = c.dir / d
        if base.exists():
            for p in base.rglob("*"):
                if "task" in p.name or "rain" in p.name:
                    probs.append(f"/{p.relative_to(c.dir)}")
    home = c.dir / "home"
    if home.exists() and any(home.iterdir()):
        probs.append("files under /home")
    results.append({"check": f"{label}: no enabled units / autostart / home files", "ok": not probs, "detail": probs})


def syntax_check(c, results, label, pkgs):
    code = ("import sys, subprocess\n"
            "bad = []\n"
            "for pkg in sys.argv[1:]:\n"
            "    files = subprocess.run(['dpkg', '-L', pkg], capture_output=True, text=True).stdout.split()\n"
            "    for f in files:\n"
            "        if f.endswith('.py'):\n"
            "            try:\n"
            "                compile(open(f, 'rb').read(), f, 'exec')\n"
            "            except SyntaxError as e:\n"
            "                bad.append(f'{f}: {e}')\n"
            "print(len(bad)); print('\\n'.join(bad)); sys.exit(1 if bad else 0)\n")
    r = c.run(["python3", "-I", "-c", code] + list(pkgs), check=False)
    results.append({"check": f"{label}: all payload .py files compile under arm64 python3", "ok": r.returncode == 0,
                    "detail": r.stdout.strip().splitlines()[1:]})


def smoke(c, results, label, pkgs):
    for p in pkgs:
        code = MESH_SMOKE if p == "task-mesh" else SMOKE.get(p)
        if not code:
            continue
        argv = ["python3", "-I", "-S", "-B", "-c", code] if p == "task-mesh" else ["python3", "-I", "-B", "-c", code]
        r = c.run(argv, check=False)
        results.append({"check": f"{label}: import entry modules of {p} (no GUI started, no device opened)",
                        "ok": r.returncode == 0, "detail": (r.stderr.strip().splitlines() or [""])[-1:]})


def scenario_each(args, results):
    """Each package alone on a clean system: install (deps from Debian arm64), smoke, remove, purge, leftovers."""
    c = Chroot(args.base, args.work, "each", args.log)
    try:
        debs = sorted(Path(args.debs).glob("*.deb"))
        for d in debs:
            c.put(d, f"/work/debs/{d.name}")
        c.local_repo()
        c.run(["apt-get", "update"])
        for d in debs:
            name = d.name.split("_")[0]
            # all Depends, incl. T.A.S.K. ones from the local repo (task-core-compat -> task-core -> python3-yaml),
            # so that dependency maintainer scripts (py3compile) run before the snapshot
            deps = dep_groups([d])
            if deps:   # dependencies first (from Debian 13 arm64), then the snapshot
                c.run(["apt-get", "satisfy", "-y", "--no-install-recommends"] + deps, check=False)
            before = c.snapshot()
            r = c.run(["apt-get", "install", "-y", "--no-install-recommends", f"/work/debs/{d.name}"], check=False)
            results.append({"check": f"each/{name}: apt-get install alone (Depends resolved from Debian 13 arm64)",
                            "ok": r.returncode == 0, "detail": [ln for ln in r.stdout.splitlines()
                                                                if ln.startswith(("Setting up task", "Setting up python3-task"))]})
            if r.returncode != 0:
                continue
            smoke(c, results, f"each/{name}", [name])
            check_policy(c, results, f"each/{name}")
            c.run(["apt-get", "remove", "-y", name])
            after_remove = c.snapshot()
            left = sorted(set(payload_files(d)) & after_remove - c.owned())
            results.append({"check": f"each/{name}: remove leaves none of its payload files", "ok": not left,
                            "detail": left[:20]})
            c.run(["dpkg", "--purge", name])
            new_unowned = sorted((c.snapshot() - before) - c.owned())
            results.append({"check": f"each/{name}: purge leaves no unowned files (piuparts-style)",
                            "ok": not new_unowned, "detail": new_unowned[:20]})
    finally:
        c.close()


def scenario_all(args, results):
    c = Chroot(args.base, args.work, "all", args.log)
    try:
        c.run(["apt-get", "update"])
        debs = sorted(Path(args.debs).glob("*.deb"))
        for d in debs:
            c.put(d, f"/work/debs/{d.name}")
        names = [d.name.split("_")[0] for d in debs]
        c.run(["apt-get", "satisfy", "-y"] + dep_groups(debs, ("Depends", "Recommends"), set(names)), check=False)
        before = c.snapshot()
        r = c.run(["apt-get", "install", "-y"] + [f"/work/debs/{d.name}" for d in debs], check=False)
        results.append({"check": "all: install every package together with Recommends", "ok": r.returncode == 0,
                        "detail": [ln for ln in r.stdout.splitlines() if "newly installed" in ln]})
        if r.returncode != 0:
            return
        r = c.run(["dpkg", "--verify"] + names, check=False)
        results.append({"check": "all: dpkg --verify clean after install", "ok": r.returncode == 0 and not r.stdout.strip(),
                        "detail": r.stdout.splitlines()[:10]})
        r = c.run(["apt-get", "check"], check=False)
        results.append({"check": "all: apt-get check (no broken dependencies)", "ok": r.returncode == 0, "detail": []})
        syntax_check(c, results, "all", names)
        smoke(c, results, "all", names)
        check_policy(c, results, "all")
        r = c.run(["sh", "-c", "ls /usr/lib/systemd/system/task-core.service /usr/lib/systemd/user/task-mesh-service.service"],
                  check=False)
        results.append({"check": "all: unit files present but not enabled", "ok": r.returncode == 0, "detail": []})
        r = c.run(["sh", "-c", "find /usr/lib/task-mesh -name __pycache__ | head -1"], check=False)
        results.append({"check": "all: task-mesh postinst byte-compiled its private tree (py3compile)",
                        "ok": bool(r.stdout.strip()), "detail": []})
        r = c.run(["apt-get", "remove", "-y"] + names, check=False)
        results.append({"check": "all: apt-get remove (no purge, no autoremove)", "ok": r.returncode == 0, "detail": []})
        r = c.run(["sh", "-c", "find /usr/lib/task-mesh -name __pycache__ | head -1"], check=False)
        results.append({"check": "all: task-mesh prerm removed byte-code (py3clean)", "ok": not r.stdout.strip(),
                        "detail": [r.stdout.strip()]})
        c.run(["dpkg", "--purge"] + names, check=False)
        new_unowned = sorted((c.snapshot() - before) - c.owned())
        results.append({"check": "all: purge leaves no unowned files", "ok": not new_unowned, "detail": new_unowned[:20]})
    finally:
        c.close()


def scenario_upgrade(args, results):
    """Delivered set (task-mesh 0.3.1) with the hand-modified notifier -> Milestone B set (0.3.2~alpha1)."""
    if not args.reference_debs:
        return
    c = Chroot(args.base, args.work, "upgrade", args.log)
    try:
        c.run(["apt-get", "update"])
        ref = sorted(Path(args.reference_debs).glob("*.deb"))
        new = sorted(Path(args.debs).glob("*.deb"))
        for d in ref:
            c.put(d, f"/work/ref/{d.name}")
        for d in new:
            c.put(d, f"/work/new/{d.name}")
        c.run(["apt-get", "install", "-y"] + [f"/work/ref/{d.name}" for d in ref])
        notifier = "/usr/lib/task-mesh/task_mesh/hub/notifier.py"
        shutil.copy(args.pi_notifier, c.dir / notifier.lstrip("/"))   # simulate the Pi's hand edit
        # simulate the Pi's migration-created, package-unowned configuration (contents are a placeholder)
        cfg = c.dir / "etc/task/core.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("# simulated site configuration (placeholder)\n[core]\nsocket = \"/run/task/core.sock\"\n")
        cfg_sha = c.sha("/etc/task/core.toml")
        r = c.run(["dpkg", "--verify", "task-mesh"], check=False)
        results.append({"check": "upgrade: simulated Pi state shows only notifier.py modified",
                        "ok": notifier in r.stdout and len(r.stdout.strip().splitlines()) == 1,
                        "detail": r.stdout.strip().splitlines()})
        files = [f"/work/new/{d.name}" for d in new]
        r = c.run(["apt-get", "install", "--print-uris", "-qq", "--only-upgrade"] + files, check=False)
        remote = [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.strip().startswith("'file:")]
        results.append({"check": "upgrade: --print-uris check lists only the bundle's local files", "ok": r.returncode == 0 and not remote,
                        "detail": remote[:10]})
        r = c.run(["apt-get", "install", "-y", "--only-upgrade"] + files, check=False)
        results.append({"check": "upgrade: offline --only-upgrade from the new bundle", "ok": r.returncode == 0,
                        "detail": [ln for ln in r.stdout.splitlines() if "upgraded" in ln]})
        r = c.run(["dpkg-query", "-W", "task-mesh"], check=False)
        results.append({"check": "upgrade: task-mesh is 0.3.2~alpha1", "ok": "0.3.2~alpha1" in r.stdout,
                        "detail": [r.stdout.strip()]})
        results.append({"check": "upgrade: notifier after upgrade == Pi's modified notifier (sha256 2864d242…)",
                        "ok": c.sha(notifier) == PI_NOTIFIER_SHA, "detail": [c.sha(notifier)]})
        r = c.run(["dpkg", "--verify"] + [d.name.split("_")[0] for d in new], check=False)
        results.append({"check": "upgrade: dpkg --verify clean after upgrade", "ok": not r.stdout.strip(),
                        "detail": r.stdout.strip().splitlines()})
        r = c.run(["dpkg-query", "-W", "task-console"], check=False)
        results.append({"check": "upgrade: task-console is 0.2.1~alpha1", "ok": "0.2.1~alpha1" in r.stdout,
                        "detail": [r.stdout.strip()]})
        results.append({"check": "upgrade: site configuration /etc/task/core.toml untouched",
                        "ok": cfg.exists() and c.sha("/etc/task/core.toml") == cfg_sha, "detail": []})
        r = c.run(["dpkg-query", "-W", "task-launcher"], check=False)
        results.append({"check": "upgrade: task-launcher is 0.3.8", "ok": "0.3.8" in r.stdout, "detail": [r.stdout.strip()]})
        toml = (c.dir / "usr/share/task-launcher/apps.d/090-devices.toml").read_text()
        results.append({"check": "upgrade: launcher Devices tile prefers /usr/bin/task-console",
                        "ok": 'exec = ["/usr/bin/task-console"]' in toml, "detail": []})
        smoke(c, results, "upgrade", ["task-mesh", "task-console", "task-launcher"])
        check_policy(c, results, "upgrade")
        # rollback to the versions installed on the Pi (previous debs kept), then restore the backed-up notifier
        r = c.run(["apt-get", "install", "-y", "--allow-downgrades"] + [f"/work/ref/{d.name}" for d in ref], check=False)
        results.append({"check": "rollback: re-install the Pi's previous versions with --allow-downgrades", "ok": r.returncode == 0,
                        "detail": [ln for ln in r.stdout.splitlines() if "downgraded" in ln]})
        r = c.run(["dpkg-query", "-W", "-f", "${Package} ${Version}\n"] + [d.name.split("_")[0] for d in ref], check=False)
        want = {d.name.split("_")[0] + " " + d.name.split("_")[1] for d in ref}
        results.append({"check": "rollback: every package is back at the Pi's version", "ok": set(r.stdout.split("\n")) - {""} == want,
                        "detail": sorted(set(r.stdout.split("\n")) ^ want - {""})})
        shutil.copy(args.pi_notifier, c.dir / notifier.lstrip("/"))   # restore from the backup, as the guide says
        results.append({"check": "rollback: restored notifier == Pi's modified notifier",
                        "ok": c.sha(notifier) == PI_NOTIFIER_SHA, "detail": []})
        results.append({"check": "rollback: /etc/task/core.toml untouched",
                        "ok": cfg.exists() and c.sha("/etc/task/core.toml") == cfg_sha, "detail": []})
        c.run(["apt-get", "remove", "-y"] + [d.name.split("_")[0] for d in new], check=False)
        results.append({"check": "upgrade: after remove, /etc/task/core.toml still present and unchanged",
                        "ok": cfg.exists() and c.sha("/etc/task/core.toml") == cfg_sha, "detail": []})
    finally:
        c.close()


def scenario_installer(args, results):
    """Run the installer's read-only detection + plan INSIDE arm64, then let this harness (not the installer)
    execute the planned argv: offline install from the bundle with a pre-filled apt cache."""
    if not args.installer:
        return
    c = Chroot(args.base, args.work, "installer", args.log)
    try:
        c.run(["apt-get", "update"])
        c.put(args.installer, "/work/installer")
        for d in sorted(Path(args.debs).glob("*.deb")) + [Path(args.debs) / "BUNDLE.json", Path(args.debs) / "SHA256SUMS"]:
            c.put(d, f"/work/bundle/{d.name}")
        r = c.run(["python3", "-I", "-c", "import sys; sys.path.insert(0, '/work/installer'); "
                   "from task_installer.tui import main; sys.exit(main(['detect']))"], check=False)
        results.append({"check": "installer: detect inside arm64 chroot (real files, read-only)",
                        "ok": "arm64" in r.stdout and "trixie" in r.stdout, "detail": r.stdout.splitlines()[:16]})
        code = ("import sys, json; sys.path.insert(0, '/work/installer')\n"
                "from task_installer import detect, compat, plan, bundle, preflight\n"
                "f = detect.detect('/'); v = compat.evaluate(f); b = bundle.load('/work/bundle')\n"
                "mods = plan.select(plan.COMPLETE, v)\n"
                "pf = preflight.check(f, plan._packages(mods), b, None)\n"
                "p = plan.install_plan(mods, v, plan.SOURCE_OFFLINE, bundle=b, preflight=pf); plan.assert_safe(p)\n"
                "print(json.dumps({'ok': v.ok, 'blockers': v.blockers, 'warnings': v.warnings, "
                "'steps': [s.__dict__ for s in p.steps], 'render': p.render()}))\n")
        r = c.run(["python3", "-I", "-c", code], check=False)
        try:
            data = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            results.append({"check": "installer: plan generated inside arm64", "ok": False, "detail": r.stderr.splitlines()[-5:]})
            return
        results.append({"check": "installer: Complete plan generated inside arm64 (no Pi model -> warning only)",
                        "ok": data["ok"], "detail": data["warnings"]})
        (Path(args.log) / "installer-plan-in-chroot.txt").write_text(data["render"] + "\n")
        install = [s for s in data["steps"] if s["argv"][:2] == ["apt-get", "install"]]
        # pre-fill the apt cache (what Milestone D's offline dependency bundle will provide)
        pre = ["apt-get", "install", "-y", "--download-only"] + [a for a in install[0]["argv"] if a.startswith("/")]
        r = c.run(pre, check=False)
        results.append({"check": "installer: dependencies pre-fetched into the apt cache (stand-in for Milestone D)",
                        "ok": r.returncode == 0, "detail": []})
        for s in data["steps"]:
            argv = s["argv"]
            if argv[0] not in ("sha256sum", "apt-get", "dpkg-query"):
                results.append({"check": f"installer: step not executed by harness: {argv[0]}", "ok": True, "detail": []})
                continue
            if s.get("expect") == "local-uris-only":
                r = c.run(argv, check=False, cwd="/work/bundle")
                remote = [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.strip().startswith("'file:")]
                results.append({"check": f"installer: planned check '{s['description']}' passes (only file: URIs)",
                                "ok": r.returncode == 0 and not remote, "detail": remote[:10]})
                if remote:
                    break   # the planned install would download: stop as the executor must
                continue
            argv = argv[:2] + ["-y"] + argv[2:] if argv[:2] == ["apt-get", "install"] else argv
            r = c.run(argv, check=False, cwd="/work/bundle")
            results.append({"check": f"installer: planned step '{s['description']}' succeeds", "ok": r.returncode == 0,
                            "detail": r.stdout.strip().splitlines()[-2:]})
        r = c.run(["sh", "-c", "dpkg-query -W 'task-*' python3-task-comms"], check=False)
        results.append({"check": "installer: all T.A.S.K. packages installed by the planned argv", "ok": r.returncode == 0,
                        "detail": r.stdout.strip().splitlines()})
        check_policy(c, results, "installer")
    finally:
        c.close()


# The exact commands of docs/VOLUNTEER-TESTING.md (keep in sync; test_volunteer_guide_commands checks it).
VOLUNTEER_INSTALL = ["apt", "install", "-y"]   # the guide uses "sudo apt install" (interactive confirmation)
VOLUNTEER_ORDER = ["python3-task-comms", "task-core", "task-core-compat", "task-launcher", "task-console", "task-mesh",
                   "task-maps", "task-aprs", "task-sdr", "task-resources"]


def scenario_volunteer(args, results):
    """Fresh Debian 13 arm64 system, network on: the volunteer guide's commands, one at a time."""
    c = Chroot(args.base, args.work, "volunteer", args.log)
    try:
        b = "/home/tester/task-volunteer-test"
        for f in sorted(Path(args.debs).glob("*.deb")) + [Path(args.debs) / "SHA256SUMS"]:
            c.put(f, f"{b}/{f.name}")
        before = c.snapshot()
        r = c.run(["sha256sum", "-c", "SHA256SUMS"], check=False, cwd=b)
        results.append({"check": "volunteer: sha256sum -c SHA256SUMS", "ok": r.returncode == 0 and "FAILED" not in r.stdout,
                        "detail": r.stdout.strip().splitlines()[-3:]})
        r = c.run(["apt", "update"], check=False)
        results.append({"check": "volunteer: apt update", "ok": r.returncode == 0, "detail": []})
        files = {p.name.split("_")[0]: "./" + p.name for p in Path(args.debs).glob("*.deb")}
        r = c.run(VOLUNTEER_INSTALL + [files[n] for n in VOLUNTEER_ORDER], check=False, cwd=b)
        results.append({"check": "volunteer: apt install ./<10 debs> (Depends + Recommends from Debian 13 arm64)",
                        "ok": r.returncode == 0, "detail": r.stdout.strip().splitlines()[-2:]})
        r = c.run(["dpkg-query", "-W", "-f", "${Package} ${Version} ${db:Status-Abbrev}\n"] + VOLUNTEER_ORDER, check=False)
        results.append({"check": "volunteer: dpkg-query shows all ten installed (ii)",
                        "ok": r.returncode == 0 and r.stdout.count(" ii") == 10, "detail": r.stdout.strip().splitlines()})
        r = c.run(["dpkg", "--verify"] + VOLUNTEER_ORDER, check=False)
        results.append({"check": "volunteer: dpkg --verify prints nothing", "ok": r.returncode == 0 and not r.stdout.strip(),
                        "detail": r.stdout.strip().splitlines()[:10]})
        r = c.run(["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "task-launcher", "--version"],
                  check=False)   # as an ordinary user (the launcher refuses root)
        results.append({"check": "volunteer: task-launcher --version", "ok": r.stdout.strip() == "task-launcher 0.3.8",
                        "detail": [r.stdout.strip(), r.stderr.strip()[-200:]]})
        r = c.run(["sh", "-c", "ls /etc/systemd/system/*.wants /etc/systemd/user/*.wants /etc/xdg/autostart 2>/dev/null "
                   "| grep -i task || true"], check=False)
        results.append({"check": "volunteer: no T.A.S.K. service enabled, no autostart", "ok": not r.stdout.strip(),
                        "detail": r.stdout.strip().splitlines()})
        smoke(c, results, "volunteer", VOLUNTEER_ORDER)
        r = c.run(["apt", "remove", "-y"] + VOLUNTEER_ORDER, check=False)
        results.append({"check": "volunteer: apt remove <10 packages>", "ok": r.returncode == 0, "detail": []})
        r = c.run(["dpkg-query", "-W", "-f", "${db:Status-Abbrev}\n"] + VOLUNTEER_ORDER, check=False)
        results.append({"check": "volunteer: all ten removed (rc or not installed)", "ok": " ii" not in r.stdout and "ii " not in r.stdout,
                        "detail": r.stdout.split()})
        c.run(["dpkg", "--purge"] + VOLUNTEER_ORDER, check=False)
        mine = sorted(f for f in (c.snapshot() - before) - c.owned()
                      if any(k in f for k in ("task-", "task_", "/task/", "rain-")))
        results.append({"check": "volunteer: after purge no T.A.S.K. files remain outside the test folder",
                        "ok": not [f for f in mine if not f.startswith(b)], "detail": mine[:20]})
    finally:
        c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--debs", required=True)
    ap.add_argument("--reference-debs")
    ap.add_argument("--pi-notifier")
    ap.add_argument("--installer")
    ap.add_argument("--work", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("needs root on the BUILD machine (chroot); never run on a production system")
    if Path(a.work).resolve() == Path("/"):
        sys.exit("refusing: work dir is /")
    Path(a.log).mkdir(parents=True, exist_ok=True)
    Path(a.work).mkdir(parents=True, exist_ok=True)
    results = []
    arch = subprocess.run(["arch-test", "arm64"], capture_output=True, text=True)
    results.append({"check": "build host can execute arm64 binaries (qemu-user binfmt)", "ok": arch.returncode == 0,
                    "detail": [arch.stdout.strip()]})
    for name, fn in (("each", scenario_each), ("all", scenario_all), ("upgrade", scenario_upgrade),
                     ("installer", scenario_installer), ("volunteer", scenario_volunteer)):
        if a.only and name not in a.only:
            continue
        t = time.time()
        try:
            fn(a, results)
        except Exception as e:  # noqa: BLE001 - recorded as a failed check
            results.append({"check": f"{name}: scenario crashed", "ok": False, "detail": [repr(e)]})
        print(f"scenario {name}: {time.time() - t:.0f}s", flush=True)
    (Path(a.log) / "chroot-results.json").write_text(json.dumps(results, indent=2) + "\n")
    passed = sum(r["ok"] for r in results)
    print(f"{passed}/{len(results)} checks passed")
    for r in results:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        if not r["ok"]:
            for d in r["detail"]:
                print("     " + str(d))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
