# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Windows build preparation checks, run on Linux. None of this is a Windows test."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import build_windows  # noqa: E402


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    return build_windows.stage(tmp_path_factory.mktemp("win"))


def test_patch_applies_cleanly_to_current_launcher(staged):
    assert (staged / "launcher/task_launcher/paths.py").read_text().count("def is_privileged") == 1
    assert (staged / "platform/task_platform/discovery.py").exists() and (staged / "LICENSE").exists()


def test_patch_touches_only_portability_points():
    text = build_windows.PATCH.read_text()
    files = sorted({ln.split()[1][2:] for ln in text.splitlines() if ln.startswith("+++ ")})
    assert files == ["launcher/task_launcher/app.py", "launcher/task_launcher/paths.py",
                     "launcher/task_launcher/registry/manifest.py", "launcher/task_launcher/services/meshbadge.py",
                     "launcher/task_launcher/services/statuscards.py"]


def test_simulated_windows_import_and_window(staged):
    pytest.importorskip("PySide6.QtWidgets")
    r = subprocess.run([sys.executable, "-B", str(HERE / "tools/simulate_windows_launcher.py"), str(staged / "launcher")],
                       capture_output=True, text=True, timeout=120)
    data = json.loads(r.stdout)
    assert r.returncode == 0 and data["import_failures"] == [] and data["window"]["class"] == "MainWindow"
    assert "APPDATA" in data["paths"]["config"] and data["paths"]["privileged"] is False


def test_build_refuses_off_windows(tmp_path):
    if sys.platform == "win32":
        pytest.skip("on Windows the real build runs")
    assert build_windows.main([str(tmp_path)]) == 2


def test_nsis_script_is_per_user_and_keeps_data():
    nsi = (HERE / "nsis/task-launcher.nsi").read_text()
    assert "RequestExecutionLevel user" in nsi and "HKLM" not in nsi and "Run\"" not in nsi
    assert "$LOCALAPPDATA\\Programs\\TASK" in nsi and "%APPDATA%\\TASK" in nsi


@pytest.mark.skipif(not shutil.which("makensis"), reason="makensis not installed")
def test_nsis_script_compiles_with_dummy_payload(tmp_path):
    src = tmp_path / "TASK-Launcher"
    src.mkdir()
    (src / "TASK-Launcher.exe").write_bytes(b"MZ dummy, not a program")
    (src / "LICENSE").write_text("license text")
    out = tmp_path / "setup.exe"
    r = subprocess.run(["makensis", "-V2", f"-DSRC={src}", f"-DOUT={out}", str(HERE / "nsis/task-launcher.nsi")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists() and out.read_bytes()[:2] == b"MZ"


@pytest.mark.skipif(not shutil.which("wixl"), reason="msitools (wixl) not installed")
def test_wix_skeleton_builds_with_dummy_component(tmp_path):
    frag = tmp_path / "files.wxs"
    (tmp_path / "TASK-Launcher.exe").write_bytes(b"MZ dummy")
    frag.write_text(f"""<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi"><Fragment>
<ComponentGroup Id="LauncherFiles"><Component Id="Exe" Directory="INSTALLDIR" Guid="*">
<File Id="ExeFile" Source="{tmp_path / 'TASK-Launcher.exe'}" KeyPath="yes"/></Component></ComponentGroup>
</Fragment></Wix>""")
    out = tmp_path / "t.msi"
    r = subprocess.run(["wixl", "-D", "Version=0.0.1", "-o", str(out), str(HERE / "wix/task-launcher.wxs"), str(frag)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.exists()
