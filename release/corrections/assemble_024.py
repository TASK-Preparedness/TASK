#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Assemble the task-sdr 0.2.4 zip (variant of assemble.py; hand-written docs from docs/phase4g-024).
usage: assemble_024.py POOL SIMDIR TESTDIR OUTDIR
Deterministic: fixed timestamps (2026-10-13), sorted entries. Source = `git archive HEAD` (must be clean)."""
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMON = HERE.parent / "common"

REL = "sdr-0.2.4"
ZIP = "TASK-Phase4G-SDRStudio-0.2.4"
D24 = "docs/phase4g-024/"
SPEC = dict(debs=["task-sdr_0.2.4_all.deb"],
            rollback=["task-sdr_0.2.3_all.deb", "task-sdr_0.2.2_all.deb", "task-sdr_0.2.1_all.deb",
                      "task-sdr_0.2.0_all.deb", "task-sdr_0.1.0_all.deb"],
            docs=[D24 + n for n in ("INSTALL.md", "RELEASE-NOTES.md", "RELEASE-COMPARISON.md", "TEST-REPORT.md",
                                    "UPGRADE-MIGRATION.md", "ROLLBACK.md", "ENGINEERING-REPORT.md",
                                    "AUDIO-PIPELINE.md", "APT-EXPECTED.md")]
            + ["docs/phase4g-m3/OVERLAY-FRAMEWORK.md", "docs/phase4g-m3/FREQUENCY-AUDIT.md",
               "docs/phase4g-022/SMART-SCANNER.md", "docs/phase4g/SDR-STUDIO.md"],
            bench="sdr/bench/measure-0.2.4",
            logs=["sdr.log", "sdr-junit.xml", "installers.log", "launcher.log", "resources.log", "resources-slow.log"])
# sha256 of previously released packages (from the earlier zips' SHA256SUMS); the copies must match exactly
KNOWN = {}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def known_hashes():
    for z in sorted(Path("/workspace").glob("TASK-Phase4*.zip")):
        if "STALE" in z.name:
            continue
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if n.endswith("SHA256SUMS"):
                    for ln in zf.read(n).decode().splitlines():
                        parts = ln.split()
                        if len(parts) == 2 and parts[1].endswith(".deb"):
                            KNOWN.setdefault(Path(parts[1]).name, set()).add(parts[0])


def main():
    rel = REL
    pool, simdir, testdir, outdir = (Path(a) for a in sys.argv[1:5])
    spec = SPEC
    if subprocess.run(["/usr/bin/git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout.strip():
        raise SystemExit("working tree not clean: commit first")
    commit = subprocess.run(["/usr/bin/git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    known_hashes()
    st = outdir / ZIP
    shutil.rmtree(st, ignore_errors=True)
    for d in ("debs", "rollback", "tools", "apt-sim", "test-logs", "source"):
        (st / d).mkdir(parents=True)
    for d in spec["debs"]:
        shutil.copy2(pool / d, st / "debs" / d)
        if d in KNOWN and sha(pool / d) not in KNOWN[d]:
            raise SystemExit(f"{d} differs from the previously released package")
    for d in spec["rollback"]:
        if sha(pool / d) not in KNOWN.get(d, set()):
            raise SystemExit(f"rollback {d} does not match any previously released sha256")
        shutil.copy2(pool / d, st / "rollback" / d)
    for f in ("preflight.sh", "install.sh", "rollback.sh", "task-guard.sh", "INSTALLER.md"):
        shutil.copy2(COMMON / f, st / f)
    shutil.copy2(REPO / "sdr/tools/hw_acceptance.py", st / "tools" / "hw_acceptance.py")
    for f in (COMMON / "tools").glob("*.py"):
        shutil.copy2(f, st / "tools" / f.name)
    shutil.copy2(HERE / rel / "release.conf", st / "release.conf")
    shutil.copy2(REPO / "LICENSE", st / "LICENSE")
    for d in spec["docs"]:
        shutil.copy2(REPO / d, st / Path(d).name)
    if spec["bench"]:
        (st / "bench-x86").mkdir()
        for f in sorted((REPO / spec["bench"]).iterdir()):
            shutil.copy2(f, st / "bench-x86" / f.name)
    for f in sorted((simdir / rel).glob("*.txt")):
        shutil.copy2(f, st / "apt-sim" / f.name)
    shutil.copy2(simdir / f"{rel}.json", st / "apt-sim" / "scenarios.json")
    shutil.copy2(HERE / "aptsim_scenarios.py", st / "apt-sim" / "aptsim_scenarios.py")
    for name in spec["logs"]:
        shutil.copy2(testdir / name, st / "test-logs" / name)
    src = st / "source" / f"task-{commit[:12]}.tar.gz"
    with open(src, "wb") as fh:
        subprocess.run(["/usr/bin/git", "archive", "--format=tar.gz", f"--prefix=task-{commit[:12]}/", "HEAD"],
                       cwd=REPO, stdout=fh, check=True)
    (st / "source" / "COMMIT").write_text(f"{commit}\n")
    for p in [p for p in st.rglob("*") if p.is_file()]:
        p.chmod(0o755 if p.suffix == ".sh" or p.name in ("aptsim_scenarios.py", "sqlite_backup.py", "hw_acceptance.py") else 0o644)
    files = sorted(p for p in st.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (st / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(st)}\n" for p in files))
    zp = outdir / f"{ZIP}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(p for p in st.rglob("*") if p.is_file()):
            zi = zipfile.ZipInfo(f"{ZIP}/{p.relative_to(st)}", (2026, 10, 13, 0, 0, 0))
            zi.external_attr = (p.stat().st_mode & 0o777 | 0o100000) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, p.read_bytes())
    print(f"{zp} {sha(zp)}")


if __name__ == "__main__":
    main()
