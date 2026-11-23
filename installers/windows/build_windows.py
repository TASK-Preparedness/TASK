#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""EXPERIMENTAL Windows launcher build. Nothing produced here is a supported or tested Windows release.

    python build_windows.py --stage-only OUT          # any OS: stage patched sources, run checks
    python build_windows.py OUT                       # Windows 11 x64 with Python 3.13, PySide6, PyInstaller
    python build_windows.py OUT --nsis                # + per-user NSIS installer (needs makensis on PATH)
    python build_windows.py OUT --use-stage DIR       # reuse a stage (e.g. Windows Python under Wine, no git)

Steps: copy the git-tracked launcher/ (0.3.8+, which contains the Windows portability changes) and
platform/ sources into OUT/stage, run
PyInstaller with task-launcher.spec ("onedir"), optionally wrap the folder with nsis/task-launcher.nsi,
then write SHA256SUMS. argv-only subprocess calls. It never signs, uploads or publishes anything.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def tracked(sub):
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", sub], cwd=REPO, check=True, capture_output=True).stdout
    return [f for f in out.decode().split("\0") if f]


def stage(out: Path) -> Path:
    st = out / "stage"
    if st.exists():
        shutil.rmtree(st)
    for sub in ("launcher", "platform"):
        for f in tracked(sub):
            if "/tests/" in f:
                continue
            dst = st / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, dst)
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(REPO / f, st / f)
    shutil.copy2(HERE / "win_entry.py", st / "win_entry.py")
    if "def is_privileged" not in (st / "launcher/task_launcher/paths.py").read_text():
        raise SystemExit("launcher source lacks the Windows portability changes (needs task-launcher >= 0.3.8)")
    return st


def sha_all(d: Path):
    with open(d / "SHA256SUMS", "w") as fh:
        for p in sorted(d.iterdir()):
            if p.is_file() and p.name != "SHA256SUMS":
                fh.write(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--nsis", action="store_true")
    ap.add_argument("--version", default="0.0.0-experimental")
    ap.add_argument("--use-stage", help="reuse a stage made by --stage-only (for a Windows/Wine Python without git)")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    st = Path(a.use_stage).resolve() if a.use_stage else stage(out)
    print(f"staged patched sources in {st}")
    if a.stage_only:
        return 0
    if sys.platform != "win32":
        print("refusing to run PyInstaller off Windows: PyInstaller does not cross-compile, and a Wine build "
              "would not be a Windows test. Use --stage-only here.", file=sys.stderr)
        return 2
    env = dict(os.environ, TASK_WIN_STAGE=str(st))
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(out / "dist"),
                    "--workpath", str(out / "build"), str(HERE / "task-launcher.spec")], check=True, env=env)
    dist = out / "dist" / "TASK-Launcher"
    shutil.copy2(st / "LICENSE", dist / "LICENSE")
    rel = out / "release"
    rel.mkdir(exist_ok=True)
    shutil.make_archive(str(rel / f"TASK-Launcher-{a.version}-windows-x64-UNTESTED"), "zip", dist)
    if a.nsis:
        subprocess.run(["makensis", f"-DVERSION={a.version}", f"-DSRC={dist}",
                        f"-DOUT={rel / f'TASK-Launcher-{a.version}-experimental-setup.exe'}",
                        str(HERE / "nsis/task-launcher.nsi")], check=True)
    sha_all(rel)
    print(f"artifacts in {rel} (UNVERIFIED — must be tested on Windows 11 x64 before any publication)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
