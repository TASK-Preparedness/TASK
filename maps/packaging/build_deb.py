#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Build task-maps_<version>_all.deb with dpkg-deb (no debhelper, no maintainer scripts) and
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
MAPS = HERE.parent
sys.path.insert(0, str(MAPS))
from task_maps import __version__ as VERSION  # noqa: E402

PKG = "task-maps"
# TODO(Joshua Sturtz): maintainer email unknown. Debian requires "Name <address>"; this is an
# explicit placeholder, not an invented address. Replace it here and in changelog.
MAINTAINER = "T.A.S.K. Development Team <TBD-maintainer-email>"  # placeholder, not a real address
# Only modules actually imported: QtCore, QtGui, QtWidgets (+ stdlib sqlite3/tomllib/urllib/xml).
DEPENDS = "python3 (>= 3.13), python3-pyside6.qtcore (>= 6.8), python3-pyside6.qtgui (>= 6.8), " \
          "python3-pyside6.qtwidgets (>= 6.8)"
RECOMMENDS = "gpsd"
SUGGESTS = "gpsd-clients, task-launcher (>= 0.2.0)"
DESCRIPTION = """\
Description: offline maps and GPS for the T.A.S.K. platform
 T.A.S.K. Maps & GPS is a native Qt (PySide6) map application: its own
 renderer shows raster MBTiles maps offline, a Download Maps mode fetches
 an area from tile sources whose terms permit offline use (rate-limited,
 resumable, live progress), MBTiles files can be imported without
 network, and the GPS position comes read-only from gpsd. Waypoints and
 recorded tracks are kept locally with GPX 1.1 import and export.
 .
 Bulk downloading from tile.openstreetmap.org is refused. Maps and
 waypoints are user data in ~/.local/share/task-maps and are kept on
 upgrade and removal. It never runs as root and never opens the GPS
 serial device.
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
    share = root / "usr/share/task-maps"
    src = MAPS / "task_maps"
    shutil.copytree(src, share / "task_maps", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data"))
    shutil.copytree(src / "data/sources.d", share / "sources.d", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "usr/bin").mkdir(parents=True)
    shutil.copy(HERE / "task-maps", root / "usr/bin/task-maps")
    (root / "usr/share/applications").mkdir(parents=True)
    shutil.copy(MAPS / "share/applications/task-maps.desktop", root / "usr/share/applications/")
    icon = root / "usr/share/icons/hicolor/scalable/apps"
    icon.mkdir(parents=True)
    shutil.copy(MAPS / "share/icons/hicolor/scalable/apps/task-maps.svg", icon)
    doc = root / "usr/share/doc" / PKG
    (doc / "examples").mkdir(parents=True)
    shutil.copy(HERE / "copyright", doc / "copyright")
    shutil.copy(MAPS / "share/examples/local-tile-server.toml", doc / "examples/local-tile-server.toml")
    for name in ("README.md", "ARCHITECTURE.md", "SOURCES-POLICY.md"):
        shutil.copy(MAPS / name, doc / name)
    (doc / "docs").mkdir()
    for p in sorted((MAPS / "docs").glob("*.md")):
        shutil.copy(p, doc / "docs" / p.name)
    gzip9n(HERE / "changelog", doc / "changelog.gz")     # native package: changelog.gz
    man = root / "usr/share/man/man1"
    man.mkdir(parents=True)
    gzip9n(HERE / "task-maps.1", man / "task-maps.1.gz")
    for p in root.rglob("*"):
        if p.is_dir():
            p.chmod(0o755)
        else:
            p.chmod(0o644)
    (root / "usr/bin/task-maps").chmod(0o755)


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
    files = subprocess.run(["git", "ls-files", "-z", "maps"], cwd=MAPS.parent, capture_output=True,
                           check=True).stdout.decode().split("\0")
    path = out / f"{name}.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in sorted(x for x in files if x):
            rel = Path(f).relative_to("maps")
            ti = tar.gettarinfo(MAPS.parent / f, arcname=f"{name}/{rel}")
            with open(MAPS.parent / f, "rb") as fh:
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
