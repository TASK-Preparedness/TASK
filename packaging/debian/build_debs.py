#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Milestone B: one reproducible builder for every T.A.S.K. Debian package.

    /usr/bin/python3 packaging/debian/build_debs.py OUTDIR [--only NAME ...] [--verify-mesh-031 PRE_AUDIO_NOTIFIER]

* All packages are pure Python and ``Architecture: all`` (no compiled code). "arm64" support therefore
  means "installs and resolves its dependencies on Debian 13 arm64", which is checked separately in an
  emulated arm64 chroot (packaging/debian/chroot-test.sh). It is NOT a Raspberry Pi hardware test.
* Deterministic: fixed SOURCE_DATE_EPOCH per package, root:root, sorted md5sums, xz, gzip -9n.
* Unchanged packages are rebuilt at the version installed on the development Pi and must have the same
  payload (paths, modes, symlinks, file contents) as the .deb delivered earlier
  (packaging/debian/reference/); verify_debs.py checks that.
* task-mesh carries the maintained audible-alert notifier, so it cannot be 0.3.1; it is built as the
  PROPOSED version 0.3.2~alpha1 (needs maintainer approval). ``--verify-mesh-031`` rebuilds 0.3.1 with
  the pre-audio notifier only to prove the builder reproduces the delivered 0.3.1 payload.
* Safety gates (build fails): no systemctl/deb-systemd-helper/apt/usermod/autostart in maintainer
  scripts, no autostart or enabled-unit symlinks in the payload, no files under /home, no private
  hostnames/users, every /etc file is a conffile, units byte-identical to the Pi-installed units.
argv-only subprocess calls, never shell=True.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "release"))
import build_release as br  # noqa: E402  (Pkg helper that produced the delivered Phase 4C debs)

EPOCH_4C = 1791792000   # 2026-10-12 08:00 UTC (Phase 4C/4F/4G builders)
EPOCH_4F3 = 1791633600  # 2026-10-10 12:00 UTC (launcher/resources builders)
MESH_VERSION = "0.3.2~alpha1"   # PROPOSED, needs approval (see docs/APPROVALS-NEEDED.md)
# PROPOSED, needs approval: 0.2.0 imports PySide6.QtNetwork (core_client.py) but does not depend on it; found by
# the arm64 chroot "each" scenario (works on the Pi only because task-launcher pulls python3-pyside6.qtnetwork).
CONSOLE_VERSION = "0.2.1~alpha1"
MESH_WHEELS = ("meshtastic-2.7.11", "meshcore-2.3.15", "pycayennelpp-2.4.0", "pyserial_asyncio_fast-0.16")

# name -> (version, epoch). Versions of unchanged packages equal `dpkg-query` on the Pi (2026-11-08).
PACKAGES = {
    "python3-task-comms": ("0.3.1", EPOCH_4C),
    "task-core": ("0.3.0", EPOCH_4C),
    "task-core-compat": ("0.3.0", EPOCH_4C),
    "task-console": (CONSOLE_VERSION, EPOCH_4C),
    "task-aprs": ("0.1.0", EPOCH_4C),
    "task-sdr": ("0.2.4", EPOCH_4C),
    "task-mesh": (MESH_VERSION, EPOCH_4C),
    "task-launcher": ("0.3.7", EPOCH_4F3),
    "task-maps": ("0.1.1", EPOCH_4C),
    "task-resources": ("0.2.4", EPOCH_4F3),
}

UNITS = {  # unit file in the payload -> source; must equal the unit installed on the Pi
    "task-core": ("usr/lib/systemd/system/task-core.service", REPO / "packaging/task-core/task-core.service"),
    "task-mesh": ("usr/lib/systemd/user/task-mesh-service.service",
                  REPO / "mesh/packaging/systemd/task-mesh-service.service"),
}

FORBIDDEN_SCRIPT = re.compile(r"\b(systemctl|deb-systemd-helper|deb-systemd-invoke|apt-get|apt|autoremove|"
                              r"usermod|useradd|groupadd|adduser|update-rc\.d|invoke-rc\.d|rfkill|bluetoothctl)\b")
FORBIDDEN_PATHS = ("etc/xdg/autostart/", "home/", "root/", "etc/systemd/", "lib/systemd/system-preset/",
                   "usr/lib/systemd/system-preset/", "usr/lib/systemd/user-preset/")
PRIVATE = re.compile(rb"/home/dragon|\bdragon@")
# MAC-address shapes are checked outside _vendor/ (upstream wheels, pinned by SHA256SUMS, contain doc examples)
MAC = re.compile(rb"(?i)\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b")


class BuildError(Exception):
    pass


def _pkg(name, depends, description, section, extra=None):
    version, epoch = PACKAGES[name]
    br.EPOCH = epoch  # Pkg.build/docs read the module-level epoch
    return br.Pkg(name, version, depends, description, section, extra)


def _desc(name):
    """Description (with continuation lines) exactly as in the delivered package's control file."""
    text = (HERE / "reference/control" / f"{name}.control").read_text()
    m = re.search(r"^Description: (.*?)(?=^\S|\Z)", text, re.S | re.M)
    return m.group(1).rstrip("\n")


def comms(out):
    p = _pkg("python3-task-comms", br.PY, _desc("python3-task-comms"), "python")
    p.tree(REPO / "comms/task_comms", "usr/lib/python3/dist-packages/task_comms")
    p.docs(br.changelog("python3-task-comms", "0.3.1", [
        "Phase 4F: mesh.<protocol> notification sources (Meshtastic, MeshCore), badge_group(),",
        "  generic 'New Mesh Message' when locked, sound/sender options for desktop notifications.",
        "Documents that Meshtastic MeshPacket.priority is not sent over the air (BEL is the alert marker)."]),
        [REPO / "comms/docs/COMMS-STATUS.md", REPO / "comms/docs/GEOFEED.md", REPO / "comms/docs/NOTIFICATIONS.md"])
    return p.build(out)


def core(out):
    p = _pkg("task-core", f"{br.PY}, python3-yaml (>= 6)", _desc("task-core"), "admin",
             {"Recommends": "python3-pyudev", "Suggests": "task-core-compat"})
    p.tree(REPO / "task_core", "usr/lib/python3/dist-packages/task_core")
    p.tree(REPO / "task_core_migrate", "usr/lib/python3/dist-packages/task_core_migrate")
    p.bin("usr/bin/task-core", "task_core.main:main")
    p.bin("usr/bin/task-core-admin", "task_core.admin:main")
    p.bin("usr/sbin/task-core-migrate", "task_core_migrate:main")
    p.tree(REPO / "share/modules", "usr/lib/task-core/modules")
    p.tree(REPO / "share/devices", "usr/lib/task-core/devices")
    p.file(REPO / "packaging/task-core/task-core.service", "usr/lib/systemd/system/task-core.service")
    p.docs(br.changelog("task-core", "0.3.0", ["Phase 4C: rename rain_core -> task_core, socket /run/task with /run/rain "
                                               "fallback, startup mutual exclusion, task-core-migrate."]),
           [REPO / "release/docs/MIGRATION.md"])
    return p.build(out)


def compat(out):
    p = _pkg("task-core-compat", "task-core (= 0.3.0)", _desc("task-core-compat"), "admin")
    p.symlink("usr/bin/rain-core-admin", "task-core-admin")
    p.docs(br.changelog("task-core-compat", "0.3.0", ["Phase 4C: compat symlink."]))
    return p.build(out)


CONSOLE_020_CHANGELOG = br.changelog("task-console", "0.2.0", ["Phase 4C: renamed from rain-console 0.1.0; Core socket fallback."])
CONSOLE_NEW_ENTRY = f"""task-console ({CONSOLE_VERSION}) unstable; urgency=medium

  * PROPOSED (not approved, not Pi-validated). Packaging-only change.
  * Depends: add python3-pyside6.qtnetwork (>= 6.8), imported by
    task_console.core_client. 0.2.0 failed to start when installed
    without task-launcher (found in an emulated arm64 chroot).
  * deploy/install-console.sh is developer-only and refuses to shadow
    an installed package.

 -- {br.MAINT}  Sun, 22 Nov 2026 09:00:00 -0500

"""


def console(out, version=None):
    version = version or CONSOLE_VERSION
    old = version == "0.2.0"
    qt = br.QT if old else br.QT + ", python3-pyside6.qtnetwork (>= 6.8)"
    br.EPOCH = PACKAGES["task-console"][1]
    p = br.Pkg("task-console", version, f"{br.PY}, {qt}", _desc("task-console"), "admin")
    p.tree(REPO / "console/task_console", "usr/lib/task-console/task_console")
    p.bin("usr/bin/task-console", "task_console.app:main", "/usr/lib/task-console")
    p.file(REPO / "console/share/task-console.desktop", "usr/share/applications/task-console.desktop")
    for icon in sorted((REPO / "console/share/icons").rglob("*")):
        if icon.is_file():
            p.file(icon, "usr/share/icons/" + str(icon.relative_to(REPO / "console/share/icons")))
    p.docs(CONSOLE_020_CHANGELOG if old else CONSOLE_NEW_ENTRY + CONSOLE_020_CHANGELOG)
    return p.build(out)


def aprs(out):
    p = _pkg("task-aprs", f"{br.PY}, {br.QT}, python3-task-comms (>= 0.3.0)", _desc("task-aprs"), "hamradio",
             {"Recommends": "direwolf", "Suggests": "task-launcher (>= 0.3.0)"})
    p.tree(REPO / "aprs/task_aprs", "usr/lib/task-aprs/task_aprs")
    p.bin("usr/bin/task-aprs", "task_aprs.app:main", "/usr/lib/task-aprs")
    p.file(REPO / "aprs/packaging/task-aprs.desktop", "usr/share/applications/task-aprs.desktop")
    p.docs(br.changelog("task-aprs", "0.1.0", ["Phase 4C: first release."]),
           [REPO / "aprs/README.md", REPO / "aprs/docs/GMRS-HARDWARE-RESEARCH.md"])
    return p.build(out)


def sdr(out):
    h = REPO / "docs/engineering-history"
    p = _pkg("task-sdr", f"{br.PY}, {br.QT}, python3-pyside6.qtmultimedia (>= 6.8), python3-numpy, python3-scipy, "
             "librtlsdr0 (>= 2.0.2), python3-task-comms (>= 0.3.0)", _desc("task-sdr"), "hamradio",
             {"Suggests": "python3-soapysdr, soapysdr0.8-module-rtlsdr, rtl-sdr"})
    p.tree(REPO / "sdr/task_sdr", "usr/lib/task-sdr/task_sdr")
    p.bin("usr/bin/task-sdr", "task_sdr.app:main", "/usr/lib/task-sdr")
    p.file(REPO / "sdr/packaging/task-sdr.desktop", "usr/share/applications/task-sdr.desktop")
    p.file(REPO / "sdr/overlays/schema/overlay-v1.schema.json", "usr/share/task-sdr/schema/overlay-v1.schema.json")
    p.docs(br.changelog("task-sdr", "0.2.4", [
        "Audio-pipeline repair (quiet, choppy WFM). IQ reading and DSP now run in separate threads, so the dongle is",
        "read back to back (0.2.3 read and demodulated serially and lost IQ while demodulating). Audio goes through a",
        "bounded, thread-safe ring (150 ms target, 500 ms cap) to a pull-mode QAudioSink that is independent of the",
        "GUI timer; partial writes (push mode) are retried, never discarded; under/overruns are counted. WFM",
        "discriminator scaled to 75 kHz deviation; AGC rewritten (RMS target, attack/release, no per-block gain",
        "steps, peak limiter); overlap-save channel FIR (about 3.5x less DSP time); resampler continuity fixed. Sink",
        "restart after device loss. Optional --diag-log JSON diagnostics. Receive only; hardware UNVERIFIED."]),
        [REPO / "sdr/README.md", h / "phase4g/SDR-STUDIO.md", h / "phase4g-022/SMART-SCANNER.md",
         h / "phase4g-m3/OVERLAY-FRAMEWORK.md", h / "phase4g-m3/FREQUENCY-AUDIT.md", h / "phase4g-024/AUDIO-PIPELINE.md"])
    return p.build(out)


MESH_COPYRIGHT_EXTRA = """
Files: usr/lib/task-mesh/task_mesh/_vendor/meshtastic/*
Copyright: Meshtastic contributors
License: GPL-3.0

Files: usr/lib/task-mesh/task_mesh/_vendor/meshcore/*
Copyright: 2025 Florent de Lamotte
License: MIT

Files: usr/lib/task-mesh/task_mesh/_vendor/cayennelpp/*
Copyright: pycayennelpp contributors
License: MIT

Files: usr/lib/task-mesh/task_mesh/_vendor/serial_asyncio_fast/*
Copyright: pyserial-asyncio-fast contributors
License: BSD-3-Clause

License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
 associated documentation files (the "Software"), to deal in the Software without restriction ... (full
 text in each bundled *.dist-info/LICENSE file under /usr/lib/task-mesh/task_mesh/_vendor).
"""


def mesh(out, version=None, notifier=None, changelog_text=None):
    """Mirrors release/phase4f/build_phase4f.py:mesh() (which produced the delivered 0.3.1)."""
    m = REPO / "mesh"
    version = version or MESH_VERSION
    br.run(["sha256sum", "-c", "SHA256SUMS"], cwd=m / "packaging/vendor", stdout=subprocess.DEVNULL)
    deps = [ln.strip().rstrip(",") for ln in (m / "packaging/debian/control").read_text().split("\nDepends:", 1)[1]
            .split("Recommends:")[0].splitlines() if ln.strip() and "${" not in ln]
    br.EPOCH = PACKAGES["task-mesh"][1]
    p = br.Pkg("task-mesh", version, ", ".join(deps + ["python3-task-comms (>= 0.3.1)"]), _desc("task-mesh"),
               "hamradio", {"Recommends": "qt6-qpa-plugins, fonts-dejavu-core",
                            "Suggests": "notification-daemon | xfce4-notifyd | dunst",
                            "Provides": "rain-mesh", "Replaces": "rain-mesh (<< 0.2.0~)",
                            "Breaks": "rain-mesh (<< 0.2.0~)"})
    lib = "usr/lib/task-mesh"
    p.tree(m / "task_mesh", f"{lib}/task_mesh")
    if notifier is not None:  # verification build only
        shutil.copy(notifier, p.path(f"{lib}/task_mesh/hub/notifier.py"))
    vend = p.path(f"{lib}/task_mesh/_vendor")
    for w in MESH_WHEELS:
        with zipfile.ZipFile(m / f"packaging/vendor/{w}-py3-none-any.whl") as z:
            z.extractall(vend)
    for junk in ("meshtastic/tests", "meshtastic/analysis", "meshtastic/.gitignore"):
        t = vend / junk
        if t.is_dir():
            shutil.rmtree(t)
        elif t.exists():
            t.unlink()
    for b in ("task-mesh", "task-mesh-service", "task-mesh-notify-setup"):
        p.file(m / f"packaging/launcher/{b}", f"usr/bin/{b}", 0o755)
    # user unit, shipped but NOT enabled: no preset, no maintainer-script systemctl call
    p.file(m / "packaging/systemd/task-mesh-service.service", "usr/lib/systemd/user/task-mesh-service.service")
    p.file(m / "packaging/debian/task-mesh.desktop", "usr/share/applications/task-mesh.desktop")
    p.file(m / "packaging/debian/task-mesh.metainfo.xml", "usr/share/metainfo/task-mesh.metainfo.xml")
    p.file(m / "assets/icons/task-mesh.svg", "usr/share/icons/hicolor/scalable/apps/task-mesh.svg")
    for s in (48, 64, 128, 256):
        p.file(m / f"assets/icons/task-mesh-{s}.png", f"usr/share/icons/hicolor/{s}x{s}/apps/task-mesh.png")
    for s in ("postinst", "prerm"):
        p.scripts[s] = (m / f"packaging/debian/task-mesh.{s}").read_text().replace("#DEBHELPER#\n", "")
    docs = [m / "README.md"] + [f for d in ("docs/phase4f", "docs/phase4f1") for f in sorted((m / d).glob("*.md"))]
    p.docs(changelog_text or (m / "packaging/debian/changelog").read_text(), docs)
    p.text("usr/share/doc/task-mesh/copyright", br.COPYRIGHT.format(pkg="task-mesh") + MESH_COPYRIGHT_EXTRA)
    return p.build(out)


def _module_builder(sub, name, out):
    """launcher/maps/resources keep their own tested builders (they produced the delivered debs)."""
    version, epoch = PACKAGES[name]
    with tempfile.TemporaryDirectory() as tmp:
        br.run([sys.executable, str(REPO / sub / "packaging/build_deb.py"), tmp, "--epoch", str(epoch)],
               stdout=subprocess.DEVNULL)
        deb = Path(tmp) / f"{name}_{version}_all.deb"
        if not deb.exists():
            raise BuildError(f"{sub} builder did not produce {deb.name} (source __version__ changed?)")
        target = out / deb.name
        shutil.copy(deb, target)
        src_dir = out / "source"
        src_dir.mkdir(exist_ok=True)
        for t in Path(tmp).glob("*.tar.gz"):
            shutil.copy(t, src_dir / t.name)
    return target


BUILDERS = {
    "python3-task-comms": comms, "task-core": core, "task-core-compat": compat, "task-console": console,
    "task-aprs": aprs, "task-sdr": sdr, "task-mesh": mesh,
    "task-launcher": lambda o: _module_builder("launcher", "task-launcher", o),
    "task-maps": lambda o: _module_builder("maps", "task-maps", o),
    "task-resources": lambda o: _module_builder("resources", "task-resources", o),
}


# ----------------------------------------------------------------------------- safety gates
def extract(deb: Path, dest: Path):
    br.run(["dpkg-deb", "-R", str(deb), str(dest)])
    return dest


def gate(deb: Path) -> list:
    """Return a list of problems (empty = OK)."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        root = extract(deb, Path(tmp) / "x")
        name = deb.name.split("_")[0]
        ctrl = root / "DEBIAN"
        for s in ("preinst", "postinst", "prerm", "postrm"):
            f = ctrl / s
            if f.exists():
                body = "\n".join(ln for ln in f.read_text().splitlines() if not ln.lstrip().startswith("#"))
                if FORBIDDEN_SCRIPT.search(body):
                    problems.append(f"{name}: maintainer script {s} contains a forbidden command")
                if "rm -rf /" in body.replace("rm -rf {}", ""):
                    problems.append(f"{name}: maintainer script {s} has a dangerous rm")
        conffiles = set((ctrl / "conffiles").read_text().split()) if (ctrl / "conffiles").exists() else set()
        for p in sorted(root.rglob("*")):
            rel = str(p.relative_to(root))
            if rel.startswith("DEBIAN"):
                continue
            if any(rel.startswith(fp) for fp in FORBIDDEN_PATHS):
                problems.append(f"{name}: forbidden path {rel}")
            if ".wants/" in rel or ".requires/" in rel:
                problems.append(f"{name}: unit enablement symlink {rel}")
            if rel.startswith("etc/") and p.is_file() and "/" + rel not in conffiles:
                problems.append(f"{name}: /{rel} is not a conffile")
            if p.is_file() and not p.is_symlink():
                data = p.read_bytes()
                if PRIVATE.search(data) or ("/_vendor/" not in rel and MAC.search(data)):
                    problems.append(f"{name}: private data pattern in {rel}")
            if p.name.endswith((".pyc", ".wav", ".sqlite", ".sqlite3", ".mbtiles", ".zim")) or p.name == "__pycache__":
                problems.append(f"{name}: generated/private file {rel}")
        if name in UNITS:
            rel, src = UNITS[name]
            if (root / rel).read_bytes() != src.read_bytes():
                problems.append(f"{name}: {rel} differs from {src}")
    return problems


def payload_paths(deb: Path) -> set:
    out = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(deb)], check=True, capture_output=True).stdout
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(out)) as t:
        return {m.name.lstrip(".") for m in t.getmembers() if not m.isdir()}


def overlaps(debs) -> list:
    """Conflict check across the set: no two packages may ship the same non-directory path."""
    seen, problems = {}, []
    for d in debs:
        for f in payload_paths(d):
            if f in seen:
                problems.append(f"file conflict: {f} in {seen[f]} and {d.name}")
            seen[f] = d.name
    return problems


def control_of(deb: Path) -> str:
    return subprocess.run(["dpkg-deb", "-f", str(deb)], check=True, capture_output=True, text=True).stdout


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--verify-mesh-031", metavar="PRE_AUDIO_NOTIFIER",
                    help="also build task-mesh 0.3.1 with this notifier into OUTDIR/verify/ (not for release)")
    ap.add_argument("--verify-console-020", action="store_true",
                    help="also build task-console 0.2.0 into OUTDIR/verify/ (not for release)")
    a = ap.parse_args(argv)
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    names = a.only or list(BUILDERS)
    report = {"builder": "packaging/debian/build_debs.py", "dpkg_deb": subprocess.run(
        ["dpkg-deb", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        "python": sys.version.split()[0], "host_arch": subprocess.run(
        ["dpkg", "--print-architecture"], capture_output=True, text=True).stdout.strip(), "packages": []}
    failed = False
    for n in names:
        deb = BUILDERS[n](out)
        probs = gate(deb)
        sha = hashlib.sha256(deb.read_bytes()).hexdigest()
        fields = dict(ln.split(": ", 1) for ln in control_of(deb).splitlines() if ln and not ln[0].isspace() and ": " in ln)
        report["packages"].append({"name": n, "version": fields["Version"], "file": deb.name, "sha256": sha,
                                   "size": deb.stat().st_size, "epoch": PACKAGES[n][1],
                                   "depends": fields.get("Depends", ""), "gate_problems": probs})
        print(f"{'OK  ' if not probs else 'FAIL'} {deb.name} {sha}")
        for pr in probs:
            print("     " + pr)
        failed |= bool(probs)
    conflicts = overlaps([out / e["file"] for e in report["packages"]])
    report["file_conflicts"] = conflicts
    print("file conflicts between packages: " + (", ".join(conflicts) if conflicts else "none"))
    failed |= bool(conflicts)
    if a.verify_mesh_031:
        vdir = out / "verify"
        vdir.mkdir(exist_ok=True)
        old_changelog = subprocess.run(["git", "show", "d4d10bd:mesh/packaging/debian/changelog"], cwd=REPO,
                                       check=True, capture_output=True, text=True).stdout
        deb = mesh(vdir, "0.3.1", Path(a.verify_mesh_031), old_changelog)
        print(f"VERIFY {deb} {hashlib.sha256(deb.read_bytes()).hexdigest()}")
    if a.verify_console_020:
        vdir = out / "verify"
        vdir.mkdir(exist_ok=True)
        deb = console(vdir, "0.2.0")
        print(f"VERIFY {deb} {hashlib.sha256(deb.read_bytes()).hexdigest()}")
    (out / "BUILD-REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    bundle = {"format": 1, "label": "T.A.S.K. Milestone B package set (UNVALIDATED on Raspberry Pi hardware)",
              "packages": [{k: e[k] for k in ("name", "version", "file", "sha256", "depends")}
                           for e in report["packages"]]}
    (out / "BUNDLE.json").write_text(json.dumps(bundle, indent=2) + "\n")
    with open(out / "SHA256SUMS", "w") as fh:
        for e in report["packages"]:
            fh.write(f"{e['sha256']}  {e['file']}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
