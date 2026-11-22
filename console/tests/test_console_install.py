# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Test 75 (installer footprint) against a temporary root and HOME with an apt shim.

Milestone B fix: the test used to pass ``--prefix /usr/local`` to pip. Debian 13's python3 uses the
``posix_local`` sysconfig scheme, which already maps the default prefix to /usr/local and appends
``/local`` to an explicit /usr/local prefix, so files landed in usr/local/local/... and the footprint
check failed. The install script itself (no --prefix) was always correct; only the test assumption
was wrong. The test now uses ``--root`` alone, exactly like a real ``sudo ./install-console.sh``.
The supported install path is the Debian package (/usr/bin/task-console, /usr/lib/task-console).
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[1]
PACKAGES = ["python3-pyside6.qtcore", "python3-pyside6.qtgui", "python3-pyside6.qtwidgets",
            "python3-pyside6.qtnetwork", "qt6-wayland"]


def build_wheel(out: Path) -> Path:
    src = out / "src"
    shutil.copytree(CONSOLE, src, ignore=shutil.ignore_patterns("__pycache__", "build", "*.egg-info", "tests"))
    subprocess.run([sys.executable, "-c", "import sys; from setuptools import build_meta as b; "
                    "print(b.build_wheel(sys.argv[1]))", str(out)], cwd=src, check=True, capture_output=True)
    return out / "task_console-0.2.0-py3-none-any.whl"


def files_under(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink())


def test_75_installer_footprint(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    wheel = build_wheel(tmp_path / "wheel")
    shutil.copy(wheel, bundle / wheel.name)
    shutil.copytree(CONSOLE / "share", bundle / "share")
    for script in ("install-console.sh", "uninstall-console.sh"):
        shutil.copy(CONSOLE / "deploy" / script, bundle / script)
    digest = hashlib.sha256((bundle / wheel.name).read_bytes()).hexdigest()
    (bundle / "SHA256SUMS").write_text(f"{digest}  {wheel.name}\n")
    root = tmp_path / "root"
    home = tmp_path / "install-home"
    root.mkdir()
    home.mkdir()
    apt_log = tmp_path / "apt.log"
    shim = tmp_path / "apt-get"
    shim.write_text(f"#!/bin/sh\necho \"$@\" >> {apt_log}\n")
    shim.chmod(0o755)
    dpkg = tmp_path / "dpkg-query"
    dpkg.write_text("#!/bin/sh\nexit 1\n")  # task-console .deb not installed
    dpkg.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PYTHON": sys.executable, "APT_GET": str(shim),
           "DPKG_QUERY": str(dpkg), "RAIN_ROOT": str(root), "RAIN_ALLOW_NONROOT": "1",
           "RAIN_PIP_ARGS": f"--root {root} --no-warn-script-location"}
    result = subprocess.run(["bash", str(bundle / "install-console.sh")], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert apt_log.read_text().split() == ["install", "-y"] + PACKAGES
    files = files_under(root)
    allowed_prefixes = ("usr/local/lib/", "usr/local/bin/task-console", "usr/local/share/applications/task-console.desktop",
                        "usr/local/share/icons/hicolor/scalable/apps/task-console.svg")
    assert all(f.startswith(allowed_prefixes) for f in files), files
    assert "usr/local/share/applications/task-console.desktop" in files
    assert "usr/local/share/icons/hicolor/scalable/apps/task-console.svg" in files
    assert "usr/local/bin/task-console" in files
    libs = [f for f in files if f.startswith("usr/local/lib/")]
    assert libs and all("/task_console/" in f or "/task_console-0.2.0.dist-info/" in f for f in libs), libs
    for forbidden in ("autostart", "systemd", "labwc", "lightdm", "gdm", "sddm", "xdg/"):
        assert not any(forbidden in f for f in files), forbidden
    assert files_under(home) == []  # nothing in any HOME: no autostart, no user unit, no labwc file
    desktop = (root / "usr/local/share/applications/task-console.desktop").read_text()
    assert "Exec=task-console\n" in desktop and "Autostart" not in desktop and "X-GNOME-Autostart" not in desktop
    # a corrupt wheel is refused before anything is installed
    (bundle / wheel.name).write_bytes(b"corrupt")
    fresh = tmp_path / "root2"
    env2 = dict(env, RAIN_ROOT=str(fresh), RAIN_PIP_ARGS=f"--root {fresh}")
    apt_log.unlink()
    result = subprocess.run(["bash", str(bundle / "install-console.sh")], env=env2, capture_output=True, text=True)
    assert result.returncode != 0 and "does not match SHA256SUMS" in result.stderr
    assert not apt_log.exists() and not fresh.exists()
    # uninstall removes the menu entry and icon; pip is called to remove the package (shimmed python here)
    pip_log = tmp_path / "pip.log"
    fake_python = tmp_path / "python3"
    fake_python.write_text(f"#!/bin/sh\necho \"$@\" >> {pip_log}\n")
    fake_python.chmod(0o755)
    result = subprocess.run(["bash", str(bundle / "uninstall-console.sh")],
                            env=dict(env, PYTHON=str(fake_python)), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "-m pip uninstall -y" in pip_log.read_text() and "task-console" in pip_log.read_text()
    assert not (root / "usr/local/share/applications/task-console.desktop").exists()
    assert not (root / "usr/local/share/icons/hicolor/scalable/apps/task-console.svg").exists()
    assert files_under(home) == []


def test_75b_refuses_to_shadow_installed_deb(tmp_path):
    """With the task-console .deb installed the legacy pip installer changes nothing."""
    bundle = tmp_path / "bundle"
    shutil.copytree(CONSOLE / "deploy", bundle)
    apt_log = tmp_path / "apt.log"
    shim = tmp_path / "apt-get"
    shim.write_text(f"#!/bin/sh\necho \"$@\" >> {apt_log}\n")
    shim.chmod(0o755)
    dpkg = tmp_path / "dpkg-query"
    dpkg.write_text("#!/bin/sh\nprintf 'install ok installed'\n")
    dpkg.chmod(0o755)
    root = tmp_path / "root"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PYTHON": sys.executable, "APT_GET": str(shim),
           "DPKG_QUERY": str(dpkg), "RAIN_ROOT": str(root), "RAIN_ALLOW_NONROOT": "1"}
    result = subprocess.run(["bash", str(bundle / "install-console.sh")], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "would shadow it" in result.stderr
    assert not apt_log.exists() and not root.exists()


def test_75c_debian_scheme_paths_documented():
    """The pip path under /usr/local must never be combined with an explicit --prefix (Debian posix_local)."""
    text = (CONSOLE / "deploy/install-console.sh").read_text()
    assert "--prefix" not in "".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
