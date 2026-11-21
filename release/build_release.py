#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Build the Phase 4C debs (all Architecture: all) with dpkg-deb. argv only, no shell.
Usage: build_release.py OUTDIR [--mesh-repo /workspace/task-mesh]"""

import argparse
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAINT = "T.A.S.K. Development Team <TBD-maintainer-email>"   # placeholder, not a real address
EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH", "1791792000"))
PY = "python3 (>= 3.11)"
QT = "python3-pyside6.qtcore (>= 6.8), python3-pyside6.qtgui (>= 6.8), python3-pyside6.qtwidgets (>= 6.8)"
COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: {pkg}
Source: T.A.S.K. (Tactical Access Support Kit) — upstream URL TBD

Files: *
Copyright: 2026 Joshua Sturtz
License: GPL-3.0-or-later
 On Debian systems the full text is in /usr/share/common-licenses/GPL-3.
"""
IGN = shutil.ignore_patterns("__pycache__", "*.pyc", "tests")


def run(argv, **kw):
    return subprocess.run(argv, check=True, **kw)


def wrapper(module, private=None):
    lines = ["#!/usr/bin/python3 -I", "# SPDX-License-Identifier: GPL-3.0-or-later",
             "# SPDX-FileCopyrightText: 2026 Joshua Sturtz", "import sys"]
    if private:
        lines.append(f"sys.path.insert(0, {private!r})")
    mod, fn = module.split(":")
    lines += [f"from {mod} import {fn}", f"sys.exit({fn}())", ""]
    return "\n".join(lines)


class Pkg:
    def __init__(self, name, version, depends="", description="", section="misc", extra=None):
        self.name, self.version, self.depends = name, version, depends
        self.description, self.section, self.extra = description, section, extra or {}
        self.tmp = Path(tempfile.mkdtemp(prefix=f"deb-{name}-"))
        self.root = self.tmp / "root"
        self.root.mkdir()
        self.scripts = {}

    def path(self, rel):
        p = self.root / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def tree(self, src, dest):
        shutil.copytree(src, self.path(dest), ignore=IGN)

    def file(self, src, dest, mode=0o644):
        p = self.path(dest)
        shutil.copy(src, p)
        p.chmod(mode)

    def text(self, dest, text, mode=0o644):
        p = self.path(dest)
        p.write_text(text)
        p.chmod(mode)

    def bin(self, dest, module, private=None):
        self.text(dest, wrapper(module, private), 0o755)

    def symlink(self, dest, target):
        p = self.path(dest)
        os.symlink(target, p)

    def docs(self, changelog_text, extra_docs=()):
        d = f"usr/share/doc/{self.name}"
        self.text(f"{d}/copyright", COPYRIGHT.format(pkg=self.name))
        p = self.path(f"{d}/changelog.gz")
        with open(p, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=9, mtime=EPOCH, filename="") as gz:
            gz.write(changelog_text.encode())
        for f in extra_docs:
            self.file(f, f"{d}/{Path(f).name}")

    def build(self, out: Path):
        for p in self.root.rglob("*"):
            if p.is_symlink():
                continue
            if p.is_dir():
                p.chmod(0o755)
            elif not os.access(p, os.X_OK):
                p.chmod(0o644)
        size = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()) // 1024 + 1
        deb = self.root / "DEBIAN"
        deb.mkdir()
        fields = [f"Package: {self.name}", f"Version: {self.version}", "Architecture: all", f"Maintainer: {MAINT}",
                  f"Installed-Size: {size}"]
        if self.depends:
            fields.append(f"Depends: {self.depends}")
        for k, v in self.extra.items():
            fields.append(f"{k}: {v}")
        fields += [f"Section: {self.section}", "Priority: optional", "Description: " + self.description.strip()]
        (deb / "control").write_text("\n".join(fields) + "\n")
        md5 = [f"{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(self.root)}"
               for p in sorted(self.root.rglob("*")) if p.is_file() and not p.is_symlink() and "DEBIAN" not in p.parts]
        (deb / "md5sums").write_text("\n".join(md5) + "\n")
        for name, body in self.scripts.items():
            (deb / name).write_text(body)
            (deb / name).chmod(0o755)
        for f in ("control", "md5sums"):
            (deb / f).chmod(0o644)
        for p in self.root.rglob("*"):
            if not p.is_symlink():
                os.utime(p, (EPOCH, EPOCH))
        target = out / f"{self.name}_{self.version}_all.deb"
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH))
        run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(self.root), str(target)], env=env,
            stdout=subprocess.DEVNULL)
        shutil.rmtree(self.tmp)
        return target


def changelog(pkg, version, lines):
    body = "\n".join("  * " + ln for ln in lines)
    return f"{pkg} ({version}) unstable; urgency=medium\n\n{body}\n\n -- {MAINT}  Mon, 12 Oct 2026 09:00:00 +0000\n"


def build_all(out: Path, mesh_repo: Path):
    built = []
    # python3-task-comms
    p = Pkg("python3-task-comms", "0.3.0", PY, "T.A.S.K. shared communications helpers\n"
            " Status cards, task-geofeed/1, hash-chained audit, transmit policy (amateur + GMRS),\n"
            " APRS codec. Pure Python, no hardware access.", "python")
    p.tree(REPO / "comms/task_comms", "usr/lib/python3/dist-packages/task_comms")
    p.docs(changelog("python3-task-comms", "0.3.0", ["Phase 4C: first release."]),
           [REPO / "comms/docs/COMMS-STATUS.md", REPO / "comms/docs/GEOFEED.md"])
    built.append(p.build(out))

    # task-core (+ migrate tool); unit installed, not enabled; no maintainer scripts
    p = Pkg("task-core", "0.3.0", f"{PY}, python3-yaml (>= 6)",
            "T.A.S.K. Core device service (renamed rain-core 0.2.1)\n"
            " Same protocol and runtime code as rain-core 0.2.1 (it reports version 0.2.1), renamed,\n"
            " plus task-core-migrate (staged, reversible migration from rain-core). The systemd unit is\n"
            " installed but neither enabled nor started; it refuses to run before migration.",
            "admin", {"Recommends": "python3-pyudev", "Suggests": "task-core-compat"})
    p.tree(REPO / "task_core", "usr/lib/python3/dist-packages/task_core")
    p.tree(REPO / "task_core_migrate", "usr/lib/python3/dist-packages/task_core_migrate")
    p.bin("usr/bin/task-core", "task_core.main:main")
    p.bin("usr/bin/task-core-admin", "task_core.admin:main")
    p.bin("usr/sbin/task-core-migrate", "task_core_migrate:main")
    p.tree(REPO / "share/modules", "usr/lib/task-core/modules")
    p.tree(REPO / "share/devices", "usr/lib/task-core/devices")
    p.file(REPO / "packaging/task-core/task-core.service", "usr/lib/systemd/system/task-core.service")
    p.docs(changelog("task-core", "0.3.0", ["Phase 4C: rename rain_core -> task_core, socket /run/task with /run/rain "
                                            "fallback, startup mutual exclusion, task-core-migrate."]),
           [Path(__file__).parent / "docs/MIGRATION.md"])
    built.append(p.build(out))

    p = Pkg("task-core-compat", "0.3.0", "task-core (= 0.3.0)", "legacy command names for task-core\n"
            " /usr/bin/rain-core-admin -> task-core-admin for one release. Removable after cleanup stage M5.", "admin")
    p.symlink("usr/bin/rain-core-admin", "task-core-admin")
    p.docs(changelog("task-core-compat", "0.3.0", ["Phase 4C: compat symlink."]))
    built.append(p.build(out))

    # task-console 0.2.0
    p = Pkg("task-console", "0.2.0", f"{PY}, {QT}", "T.A.S.K. Console (renamed rain-console)\n"
            " Desktop console for task-core: status, devices and accounts views.", "admin")
    p.tree(REPO / "console/task_console", "usr/lib/task-console/task_console")
    p.bin("usr/bin/task-console", "task_console.app:main", "/usr/lib/task-console")
    p.file(REPO / "console/share/task-console.desktop", "usr/share/applications/task-console.desktop")
    for icon in (REPO / "console/share/icons").rglob("*"):
        if icon.is_file():
            p.file(icon, "usr/share/icons/" + str(icon.relative_to(REPO / "console/share/icons")))
    p.docs(changelog("task-console", "0.2.0", ["Phase 4C: renamed from rain-console 0.1.0; Core socket fallback."]))
    built.append(p.build(out))

    # task-aprs
    p = Pkg("task-aprs", "0.1.0", f"{PY}, {QT}, python3-task-comms (>= 0.3.0)",
            "T.A.S.K. APRS (amateur via Direwolf) and GMRS data profile\n"
            " Two-way amateur APRS through an already running Direwolf (AGW/KISS on loopback); never\n"
            " starts or configures Direwolf. Every transmission is an explicit user action checked by the\n"
            " transmit policy and audited. GMRS data only through a radio-integration driver; no verified\n"
            " real GMRS driver exists yet (SIMULATION driver only).", "hamradio",
            {"Recommends": "direwolf", "Suggests": "task-launcher (>= 0.3.0)"})
    p.tree(REPO / "aprs/task_aprs", "usr/lib/task-aprs/task_aprs")
    p.bin("usr/bin/task-aprs", "task_aprs.app:main", "/usr/lib/task-aprs")
    p.file(REPO / "aprs/packaging/task-aprs.desktop", "usr/share/applications/task-aprs.desktop")
    p.docs(changelog("task-aprs", "0.1.0", ["Phase 4C: first release."]),
           [REPO / "aprs/README.md", REPO / "aprs/docs/GMRS-HARDWARE-RESEARCH.md"])
    built.append(p.build(out))

    # task-sdr
    p = Pkg("task-sdr", "0.1.0", f"{PY}, {QT}, python3-pyside6.qtmultimedia (>= 6.8), python3-numpy, python3-scipy, "
            "python3-soapysdr, soapysdr0.8-module-rtlsdr, python3-task-comms (>= 0.3.0)",
            "T.A.S.K. SDR receive-only receiver\n"
            " SoapySDR RX (RTL-SDR Blog V4 target), WFM/NFM/AM/USB/LSB via scipy, audio, spectrum and\n"
            " waterfall. No transmit capability.", "hamradio")
    p.tree(REPO / "sdr/task_sdr", "usr/lib/task-sdr/task_sdr")
    p.bin("usr/bin/task-sdr", "task_sdr.app:main", "/usr/lib/task-sdr")
    p.file(REPO / "sdr/packaging/task-sdr.desktop", "usr/share/applications/task-sdr.desktop")
    p.docs(changelog("task-sdr", "0.1.0", ["Phase 4C: first release."]), [REPO / "sdr/README.md"])
    built.append(p.build(out))

    # task-mesh 0.2.0 (mirrors packaging/debian/rules of the task-mesh repo, without debhelper)
    m = mesh_repo
    run(["sha256sum", "-c", "SHA256SUMS"], cwd=m / "packaging/vendor", stdout=subprocess.DEVNULL)
    deps = [ln.strip().rstrip(",") for ln in (m / "packaging/debian/control").read_text().split("\nDepends:", 1)[1]
            .split("Recommends:")[0].splitlines() if ln.strip() and "${" not in ln]
    p = Pkg("task-mesh", "0.2.0", ", ".join(deps + ["python3-task-comms (>= 0.3.0)"]),
            "T.A.S.K. Mesh Operations - native field station for Meshtastic radios\n"
            " Node table, channel messages and DMs with honest delivery states, private history behind a\n"
            " task-core sign-in. Bundles meshtastic 2.7.11 (GPL-3.0-only) under /usr/lib/task-mesh.", "hamradio",
            {"Recommends": "qt6-qpa-plugins, fonts-dejavu-core", "Provides": "rain-mesh",
             "Replaces": "rain-mesh (<< 0.2.0~)", "Breaks": "rain-mesh (<< 0.2.0~)"})
    lib = "usr/lib/task-mesh"
    p.tree(m / "task_mesh", f"{lib}/task_mesh")
    with zipfile.ZipFile(m / "packaging/vendor/meshtastic-2.7.11-py3-none-any.whl") as z:
        z.extractall(p.path(f"{lib}/task_mesh/_vendor"))
    for junk in ("meshtastic/tests", "meshtastic/analysis", "meshtastic/.gitignore"):
        t = p.path(f"{lib}/task_mesh/_vendor/{junk}")
        if t.is_dir():
            shutil.rmtree(t)
        elif t.exists():
            t.unlink()
    p.file(m / "packaging/launcher/task-mesh", "usr/bin/task-mesh", 0o755)
    p.file(m / "packaging/debian/task-mesh.desktop", "usr/share/applications/task-mesh.desktop")
    p.file(m / "packaging/debian/task-mesh.metainfo.xml", "usr/share/metainfo/task-mesh.metainfo.xml")
    p.file(m / "assets/icons/task-mesh.svg", "usr/share/icons/hicolor/scalable/apps/task-mesh.svg")
    for s in (48, 64, 128, 256):
        p.file(m / f"assets/icons/task-mesh-{s}.png", f"usr/share/icons/hicolor/{s}x{s}/apps/task-mesh.png")
    for s in ("postinst", "prerm"):
        p.scripts[s] = (m / f"packaging/debian/task-mesh.{s}").read_text().replace("#DEBHELPER#\n", "")
    p.docs((m / "packaging/debian/changelog").read_text(), [m / "README.md"])
    built.append(p.build(out))

    p = Pkg("rain-mesh", "0.2.0", "task-mesh (>= 0.2.0)", "transitional package: rain-mesh -> task-mesh\n"
            " Pulls in task-mesh. Can be removed safely.", "oldlibs")
    p.docs(changelog("rain-mesh", "0.2.0", ["Transitional package for the rename to task-mesh."]))
    built.append(p.build(out))

    # launcher + maps use their own (existing, tested) builders
    for sub in ("launcher", "maps"):
        run([sys.executable, str(REPO / sub / "packaging/build_deb.py"), str(out), "--epoch", str(EPOCH)],
            stdout=subprocess.DEVNULL)
    return built


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--mesh-repo", default="/workspace/task-mesh")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for d in build_all(out, Path(a.mesh_repo)):
        print(d.name)


if __name__ == "__main__":
    main()
