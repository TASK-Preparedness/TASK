#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Build task-launcher_<version>_all.deb with dpkg-deb (no debhelper, no maintainer scripts) and
the source tarball. Usage: build_deb.py OUTDIR [--epoch SECONDS]"""

import argparse
import gzip
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE.parent
sys.path.insert(0, str(LAUNCHER))
from task_launcher import __version__ as VERSION  # noqa: E402

PKG = "task-launcher"
# TODO(Joshua Sturtz): maintainer email unknown. Debian requires "Name <address>"; this is an
# explicit placeholder, not an invented address. Replace it here and in changelog.
MAINTAINER = "T.A.S.K. Development Team <TBD-maintainer-email>"  # placeholder, not a real address
DEPENDS = ("python3 (>= 3.13), python3-pyside6.qtcore (>= 6.8), python3-pyside6.qtgui (>= 6.8), "
           "python3-pyside6.qtwidgets (>= 6.8), python3-pyside6.qtnetwork (>= 6.8), python3-pyside6.qtsvg (>= 6.8), "
           "python3-pyside6.qtdbus (>= 6.8)")
RECOMMENDS = "fonts-inter, qt6-wayland, qt6-svg-plugins, xdg-utils"
SUGGESTS = "task-core (>= 0.3.0), task-resources (>= 0.2.4), task-mesh (>= 0.2.0), task-aprs, task-sdr, task-maps (>= 0.1.1), foxtrotgps, gpsd-clients, kiwix-tools, direwolf"
DESCRIPTION = """\
Description: application launcher for the T.A.S.K. platform
 Native Qt (PySide6) launcher for the T.A.S.K. platform: app tiles from
 TOML manifests and installed desktop applications, horizontal paging,
 task-core link status and sign-in, read-only System and Devices views and
 an App Manager. It launches the installed field apps (task-mesh,
 task-aprs, task-sdr, task-maps; SDR++/Gqrx as External) and has native
 read-only windows for the Kiwix library, a receive-only APRS monitor
 fallback, local weather
 data and offline medical references. It is an ordinary desktop window
 (no kiosk, no session replacement), never runs as root, never opens
 hardware itself and never transmits.
"""


def norm(info: tarfile.TarInfo, epoch: int):
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = epoch
    return info


def gzip9n(src: Path, dst: Path):
    """Debian policy: gzip -9n (max compression, no name/timestamp)."""
    with open(dst, "wb") as out:
        subprocess.run(["gzip", "-9nc", str(src)], stdout=out, check=True)


def stage(root: Path):
    share = root / "usr/share/task-launcher"
    src = LAUNCHER / "task_launcher"
    shutil.copytree(src, share / "task_launcher",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "apps.d"))
    shutil.copytree(src / "data/apps.d", share / "apps.d", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "usr/bin").mkdir(parents=True)
    shutil.copy(HERE / "task-launcher", root / "usr/bin/task-launcher")
    (root / "usr/share/applications").mkdir(parents=True)
    shutil.copy(LAUNCHER / "share/applications/task-launcher.desktop", root / "usr/share/applications/")
    icon = root / "usr/share/icons/hicolor/scalable/apps"
    icon.mkdir(parents=True)
    shutil.copy(LAUNCHER / "share/icons/hicolor/scalable/apps/task-launcher.svg", icon)
    doc = root / "usr/share/doc" / PKG
    (doc / "examples").mkdir(parents=True)
    shutil.copy(HERE / "copyright", doc / "copyright")
    shutil.copy(LAUNCHER / "share/examples/branding.toml", doc / "examples/branding.toml")
    for name in ("README.md", "MANIFEST-SPEC.md", "ARCHITECTURE.md"):
        if (LAUNCHER / name).exists():
            shutil.copy(LAUNCHER / name, doc / name)
    (doc / "docs").mkdir()
    for p in sorted((LAUNCHER / "docs").glob("*.md")):
        shutil.copy(p, doc / "docs" / p.name)
    gzip9n(HERE / "changelog", doc / "changelog.gz")     # native package: changelog.gz
    man = root / "usr/share/man/man1"
    man.mkdir(parents=True)
    gzip9n(HERE / "task-launcher.1", man / "task-launcher.1.gz")
    for p in root.rglob("*"):
        if p.is_dir():
            p.chmod(0o755)
        else:
            p.chmod(0o644)
    (root / "usr/bin/task-launcher").chmod(0o755)


def control(root: Path):
    size_kb = sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) // 1024 + 1
    deb = root / "DEBIAN"
    deb.mkdir(mode=0o755)
    (deb / "control").write_text(
        f"Package: {PKG}\nVersion: {VERSION}\nArchitecture: all\n"
        f"Maintainer: {MAINTAINER}\n"
        f"Installed-Size: {size_kb}\nDepends: {DEPENDS}\nRecommends: {RECOMMENDS}\nSuggests: {SUGGESTS}\n"
        "Section: utils\nPriority: optional\n" + DESCRIPTION)
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and "DEBIAN" not in p.parts:
            lines.append(f"{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n")
    (deb / "md5sums").write_text("".join(lines))
    for f in deb.iterdir():
        f.chmod(0o644)


def source_tarball(out: Path, epoch: int):
    name = f"{PKG}-{VERSION}"
    files = subprocess.run(["git", "ls-files", "-z", "launcher"], cwd=LAUNCHER.parent, capture_output=True,
                           check=True).stdout.decode().split("\0")
    path = out / f"{name}.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in sorted(x for x in files if x):
            rel = Path(f).relative_to("launcher")
            ti = tar.gettarinfo(LAUNCHER.parent / f, arcname=f"{name}/{rel}")
            with open(LAUNCHER.parent / f, "rb") as fh:
                tar.addfile(norm(ti, epoch), fh)
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=9, mtime=epoch) as gz:
        gz.write(buf.getvalue())
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "1791633600")))
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "root"
        root.mkdir()
        stage(root)
        control(root)
        for p in root.rglob("*"):
            os.utime(p, (a.epoch, a.epoch), follow_symlinks=False)
        deb = out / f"{PKG}_{VERSION}_all.deb"
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(a.epoch))
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(root), str(deb)], check=True, env=env)
    tarball = source_tarball(out, a.epoch)
    print(deb)
    print(tarball)


if __name__ == "__main__":
    main()
