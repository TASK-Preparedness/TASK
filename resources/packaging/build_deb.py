#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Build task-resources_<version>_all.deb with dpkg-deb (no debhelper, no maintainer scripts) and
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
RES = HERE.parent
sys.path.insert(0, str(RES))
from task_resources import __version__ as VERSION  # noqa: E402

PKG = "task-resources"
# TODO(Joshua Sturtz): maintainer email unknown. Debian requires "Name <address>"; this is an
# explicit placeholder, not an invented address. Replace it here and in changelog.
MAINTAINER = "T.A.S.K. Development Team <TBD-maintainer-email>"  # placeholder, not a real address
# Only modules actually imported: QtCore, QtGui, QtWidgets (+ stdlib sqlite3/urllib/xml/http.client/ssl).
# ca-certificates: the system CA store used to verify HTTPS (Phase 4E downloads/catalog).
DEPENDS = "python3 (>= 3.13), python3-pyside6.qtcore (>= 6.8), python3-pyside6.qtgui (>= 6.8), " \
          "python3-pyside6.qtwidgets (>= 6.8), python3-libzim (>= 3.6), ca-certificates"
# Approved by Joshua (2026-10-13): Qt WebEngine as Recommends (optional; ~190 MB installed on arm64);
# without it the lightweight viewer is used automatically. QtPdf (~5 MB) for PDF viewing.
RECOMMENDS = "python3-pyside6.qtwebenginewidgets (>= 6.8), python3-pyside6.qtwebenginecore (>= 6.8), " \
             "python3-pyside6.qtpdf (>= 6.8), python3-pyside6.qtpdfwidgets (>= 6.8)"
SUGGESTS = "task-launcher (>= 0.3.2)"
DESCRIPTION = """\
Description: native offline library and reader for the T.A.S.K. platform
 T.A.S.K. Resources is its own ZIM library and reader built on python3-libzim:
 it finds existing ZIM files (and PDF, EPUB, text, Markdown and HTML) where
 they already are and never moves, copies or modifies them; it keeps a
 private index with categories, edited metadata, bookmarks and history;
 it searches titles and, where a ZIM has a full-text index, full text.
 .
 Pages are read straight from the archive. The optional Qt WebEngine viewer
 serves them through a zim:// scheme handler with all network requests
 blocked; without WebEngine a lightweight viewer is used. It does not use
 or reconfigure Kiwix, kiwix-serve or any HTTP server, never runs as root
 and has no service or autostart.
 .
 Since 0.2.0 it can browse the official Kiwix OPDS catalog and download ZIM,
 PDF, EPUB, HTML, text and Markdown files on request: resumable, verified
 (size, published sha-256, file type, libzim integrity check) before they
 appear in the library, through an SSRF-safe HTTPS client. Nothing is
 contacted until the user asks.
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
    share = root / "usr/share/task-resources"
    shutil.copytree(RES / "task_resources", share / "task_resources",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "usr/bin").mkdir(parents=True)
    shutil.copy(HERE / "task-resources", root / "usr/bin/task-resources")
    (root / "usr/share/applications").mkdir(parents=True)
    shutil.copy(RES / "share/applications/task-resources.desktop", root / "usr/share/applications/")
    icon = root / "usr/share/icons/hicolor/scalable/apps"
    icon.mkdir(parents=True)
    shutil.copy(RES / "share/icons/hicolor/scalable/apps/task-resources.svg", icon)
    doc = root / "usr/share/doc" / PKG
    doc.mkdir(parents=True)
    shutil.copy(HERE / "copyright", doc / "copyright")
    shutil.copy(RES / "README.md", doc / "README.md")
    (doc / "docs").mkdir()
    for p in sorted((RES / "docs").glob("*.md")):
        shutil.copy(p, doc / "docs" / p.name)
    gzip9n(HERE / "changelog", doc / "changelog.gz")
    for p in root.rglob("*"):
        p.chmod(0o755 if p.is_dir() else 0o644)
    (root / "usr/bin/task-resources").chmod(0o755)


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
    files = subprocess.run(["git", "ls-files", "-z", "resources"], cwd=RES.parent, capture_output=True,
                           check=True).stdout.decode().split("\0")
    path = out / f"{name}.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in sorted(x for x in files if x):
            rel = Path(f).relative_to("resources")
            ti = tar.gettarinfo(RES.parent / f, arcname=f"{name}/{rel}")
            with open(RES.parent / f, "rb") as fh:
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
