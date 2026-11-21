# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Test 52: licensing (D7, D13; PHASE-2.md sections 14 item 7 and 15)."""

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FSF_GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"  # gnu.org gpl-3.0.txt
SPDX = ["# SPDX-License-Identifier: GPL-3.0-or-later", "# SPDX-FileCopyrightText: 2026 Joshua Sturtz"]


def test_52_license_files_are_the_verbatim_gpl3_text():
    for tree in (ROOT, ROOT / "console"):
        assert hashlib.sha256((tree / "LICENSE").read_bytes()).hexdigest() == FSF_GPL3_SHA256, tree


PHASE1_FILES = ROOT / "tests" / "golden" / "phase1_files.txt"  # git ls-tree -r --name-only phase1-accepted
SKIP_DIRS = {".git", "__pycache__", "build", "dist", ".pytest_cache"}


def git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return out.stdout if out.returncode == 0 else None


def phase1_files():
    """Phase 1 paths, mapped through the Phase 4C rename (tests/rebrand_map.py: rain_core/ -> task_core/)."""
    from rebrand_map import rebrand_path

    listed = set(PHASE1_FILES.read_text().split())
    from_git = git("ls-tree", "-r", "--name-only", "phase1-accepted")
    if from_git is not None:
        assert set(from_git.split()) == listed, "tests/golden/phase1_files.txt does not match the phase1-accepted tag"
    return {rebrand_path(n) for n in listed}


def tree_files():
    tracked = git("ls-files")
    if tracked is not None:
        untracked = git("ls-files", "--others", "--exclude-standard") or ""
        return set(tracked.split()) | set(untracked.split())
    # source tarball without .git: every file in the tree
    return {str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
            if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts) and ".egg-info" not in str(p)}


def new_files():
    return sorted(tree_files() - phase1_files())


def test_52_every_new_py_and_sh_file_has_the_spdx_lines():
    checked = 0
    for name in new_files():
        path = ROOT / name
        if path.suffix not in (".py", ".sh") or not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].startswith("#!"):
            lines = lines[1:]
        assert lines[:2] == SPDX, name
        checked += 1
    assert checked >= 40


def test_52_other_new_files_carry_the_lines_in_their_syntax():
    for name in ("console/share/task-console.desktop", "console/pyproject.toml", "deploy/sessions.toml.example"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert text.splitlines()[:2] == SPDX, name
    svg = (ROOT / "console/share/icons/hicolor/scalable/apps/task-console.svg").read_text()
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in svg and "SPDX-FileCopyrightText: 2026 Joshua Sturtz" in svg


def build_wheel(project: Path, out: Path) -> Path:
    src = out / "src"
    shutil.copytree(project, src, ignore=shutil.ignore_patterns("__pycache__", "build", "*.egg-info", ".git",
                                                                "console", "tests", "dist"))
    result = subprocess.run([sys.executable, "-c", "import sys; from setuptools import build_meta as b; "
                             "print(b.build_wheel(sys.argv[1]))", str(out)], cwd=src, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return out / result.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("project,dist", [(".", "task_core-0.2.1"), ("console", "task_console-0.2.0")])
def test_52_built_wheels_carry_gpl_metadata_and_license(tmp_path, project, dist):
    wheel = build_wheel(ROOT / project, tmp_path)
    assert wheel.name == f"{dist}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata = Parser().parsestr(archive.read(f"{dist}.dist-info/METADATA").decode())
        license_entries = [n for n in names if n.startswith(f"{dist}.dist-info/") and n.endswith("LICENSE")]
        assert license_entries, names
        assert hashlib.sha256(archive.read(license_entries[0])).hexdigest() == FSF_GPL3_SHA256
    assert metadata["License-Expression"] == "GPL-3.0-or-later"
    assert "LICENSE" in (metadata.get_all("License-File") or [])


def test_52_phase1_files_untouched_except_the_version_literal():
    """Every Phase 1 test file is byte-identical to the accepted tree except test_not_root.py (test 1 covers
    the hashes too; this checks the git history when a checkout is available)."""
    from rebrand_map import rebrand_text

    out = git("diff", "--name-only", "phase1-accepted", "--", "tests/")
    if out is not None:
        for name in set(out.split()) & phase1_files():
            if name == "tests/test_not_root.py":
                continue
            original = git("show", f"phase1-accepted:{name}")
            assert rebrand_text(original) == (ROOT / name).read_text(), f"{name}: more than the Phase 4C rename"
    # without git (source tarball) and with it: the recorded hashes of the 14 rebranded Phase 1 test files
    manifest = json.loads((ROOT / "tests" / "golden" / "phase4c_rebranded_tests.sha256.json").read_text())
    phase1_tests = {name for name in phase1_files() if name.startswith("tests/")}
    assert {f"tests/{name}" for name in manifest["files"]} == phase1_tests
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / "tests" / name).read_bytes()).hexdigest() == digest, name
