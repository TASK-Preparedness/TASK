# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Test 77: update-0.2.0.sh and rollback-0.1.1.sh against a simulated 0.1.1 install (PHASE-2.md 17.7).

Stand-ins (off-target): a venv for the system python3 (pip and PyYAML from the running interpreter,
a stub pyudev because only the update script's import check needs it), a systemctl shim that runs
the real rain_core Core of whatever version is installed in that venv with a fake enumerator carrying
the three golden devices, rain-smoke pointed at a temporary socket, and the invoking user standing in
for the rain-core service account. The accepted 0.1.1 wheel is the Pi-accepted artifact
(sha256 b1935dd7...a26a); it is looked up next to the source tree (see ACCEPTED_011_CANDIDATES).
"""

import dataclasses
import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from p2fixtures import golden_devices, write_accounts, default_accounts

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_011_SHA256 = "b1935dd774fc5929e2cdf1ef677005a7b83e4eaa137a0ab829721bfc4815a26a"
WHEEL_011 = "rain_core-0.1.1-py3-none-any.whl"
WHEEL_020 = "rain_core-0.2.0-py3-none-any.whl"
UBLOX = "dev_74a462923d20f21e"
ACCEPTED_011_CANDIDATES = [
    Path(os.environ["RAIN_011_WHEEL"]) if os.environ.get("RAIN_011_WHEEL") else None,
    ROOT.parent / WHEEL_011,                                  # bundle layout: source tree next to the wheels
    ROOT.parent / "rain-phase2-dist" / WHEEL_011,
    ROOT.parent / "rain-core-0.1.1-dist" / WHEEL_011,          # the 0.1.1 release bundle
]

RUNNER = r'''
import sys
from pathlib import Path
from rain_core.config import load_config
from rain_core.devices import RawDevice
from rain_core.main import Core

DEVICES = %(devices)r

class Fake:
    def start(self, on_appear, on_disappear, on_change):
        return [RawDevice(**fields) for fields in DEVICES]
    def stop(self):
        return None

core = Core(load_config(Path(sys.argv[1])), enumerator_factory=Fake)
core.open()
try:
    core.wait()
finally:
    core.close()
'''

SYSTEMCTL = r'''#!/bin/bash
# systemctl stand-in: one background "rain-core" started the way the unit's ExecStart would be.
U=%(u)s; PIDF=$U/run/rain-core.pid; LOG=$U/run/rain-core.log
running() { [[ -f $PIDF ]] && kill -0 "$(cat $PIDF)" 2>/dev/null; }
echo "$*" >> $U/run/systemctl.calls
q=0; [[ "$1" == "is-active" && "$2" == "--quiet" ]] && { q=1; set -- is-active "$3"; }
case "$1" in
  start) running || { (cd $U/state && exec $U/py/bin/python $U/service.py $U/etc/core.toml >>$LOG 2>&1 </dev/null) & echo $! > $PIDF;
         for i in $(seq 200); do
           $U/py/bin/python -c "import socket,sys; socket.socket(socket.AF_UNIX).connect(sys.argv[1])" $U/run/core.sock 2>/dev/null && break
           sleep 0.05
         done; } ;;
  stop) if running; then kill "$(cat $PIDF)"; for i in $(seq 100); do running || break; sleep 0.05; done; fi; rm -f $PIDF ;;
  is-active) if running; then [[ $q == 1 ]] || echo active; exit 0; else [[ $q == 1 ]] || echo inactive; exit 3; fi ;;
  *) echo "shim: unsupported $*" >&2; exit 1 ;;
esac
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_011_wheel() -> Path:
    for candidate in ACCEPTED_011_CANDIDATES:
        if candidate and candidate.is_file() and sha(candidate) == ACCEPTED_011_SHA256:
            return candidate
    pytest.fail("the Pi-accepted rain_core-0.1.1 wheel was not found; set RAIN_011_WHEEL=<path> "
                f"(expected sha256 {ACCEPTED_011_SHA256})")


def delivered_020_wheel() -> Path:
    """The Phase 2 delivered 0.2.0 wheel (sha256 253572c5…); not rebuilt from this tree (now 0.2.1)."""
    candidates = [
        Path(os.environ["RAIN_020_WHEEL"]) if os.environ.get("RAIN_020_WHEEL") else None,
        ROOT.parent / "rain-phase2-dist" / WHEEL_020,
        ROOT.parent / "rain-h1-dist" / WHEEL_020,
    ]
    want = "253572c5e3f7b09012292b451460f2cae8a97ad529f20780c05174790b892bad"
    for candidate in candidates:
        if candidate and candidate.is_file() and sha(candidate) == want:
            return candidate
    pytest.fail(f"delivered rain_core 0.2.0 wheel not found (expected sha256 {want}); set RAIN_020_WHEEL=<path>")


def build_020_wheel(out: Path) -> Path:
    # Kept for callers; copies the delivered artifact into out.
    dest = out / WHEEL_020
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(delivered_020_wheel(), dest)
    return dest


class Sim:
    def __init__(self, base: Path):
        self.u = base / "u"
        for sub in ("bin", "run", "state", "etc", "deps"):
            (self.u / sub).mkdir(parents=True)
        self.py = self.u / "py" / "bin" / "python"
        self._make_python()
        self.sock = str(self.u / "run" / "core.sock")
        devices = [dataclasses.asdict(raw) for raw in golden_devices()]
        (self.u / "service.py").write_text(RUNNER % {"devices": devices})
        systemctl = self.u / "bin" / "systemctl"
        systemctl.write_text(SYSTEMCTL % {"u": self.u})
        systemctl.chmod(0o755)
        smoke = self.u / "bin" / "rain-smoke"
        text = (ROOT / "deploy" / "rain-smoke.py").read_text()
        smoke.write_text(text.replace("#!/usr/bin/python3", f"#!{self.py}", 1)
                         .replace('SOCKET = "/run/rain/core.sock"', f'SOCKET = "{self.sock}"', 1))
        smoke.chmod(0o755)
        (self.u / "etc" / "core.toml").write_text(
            f'socket = "{self.sock}"\nstate_dir = "{self.u / "state"}"\nshare_dir = "{ROOT / "share"}"\n'
            f'auth_file = "{self.u / "etc" / "auth.toml"}"\n')
        (self.u / "etc" / "auth.toml").write_text(f'[peers]\n{os.getuid()} = "administrator"\n')
        (self.u / "etc" / "rain-core.service").write_text("[Unit]\nDescription=stand-in\n")
        self.env = {
            "PATH": f"{self.u / 'bin'}:{os.environ['PATH']}", "HOME": str(base), "LANG": "C.UTF-8",
            "PYTHON": str(self.py), "RAIN_STATE_DIR": str(self.u / "state"), "RAIN_ETC_DIR": str(self.u / "etc"),
            "RAIN_BACKUP_ROOT": str(self.u / "backups"), "RAIN_UNIT_FILE": str(self.u / "etc" / "rain-core.service"),
            "RAIN_SMOKE": str(smoke), "RAIN_SERVICE_USER": getpass.getuser(),
            "RAIN_LEGACY_USER": "rain-p2-test-no-such-account", "RAIN_ALLOW_NONROOT": "1",
        }

    def _make_python(self):
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.u / "py")], check=True)
        import pip
        import yaml
        deps = self.u / "deps"
        for module in (pip, yaml):
            (deps / module.__name__).symlink_to(Path(module.__file__).parent)
        legacy = Path(yaml.__file__).parent.parent / "_yaml"  # PyYAML's compatibility shim package, if shipped
        if legacy.is_dir():
            (deps / "_yaml").symlink_to(legacy)
        (deps / "pyudev").mkdir()
        (deps / "pyudev" / "__init__.py").write_text("# stand-in: only update-0.2.0.sh's import check uses it\n")
        site = subprocess.run([str(self.py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                              check=True, capture_output=True, text=True).stdout.strip()
        Path(site, "sim-deps.pth").write_text(f"{deps}\n")

    def run(self, *args, env=None, check=False):
        return subprocess.run(list(args), env=dict(self.env, **(env or {})), capture_output=True, text=True,
                              check=check, cwd="/")

    def pip_install(self, wheel):
        self.run(str(self.py), "-m", "pip", "install", "-q", "--no-deps", "--no-index", str(wheel), check=True)

    def version(self):
        return self.run(str(self.py), "-c", "import rain_core; print(rain_core.__version__)").stdout.strip()

    def smoke(self, *args):
        result = self.run(self.env["RAIN_SMOKE"], *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def health_version(self):
        return self.smoke("health")["result"]["version"]

    def assignment(self):
        return self.smoke("devices")["result"]["assignments"].get("gps.primary")

    def systemctl(self, *args):
        return self.run("systemctl", *args)

    def calls(self):
        path = self.u / "run" / "systemctl.calls"
        return path.read_text().splitlines() if path.exists() else []

    def clear_calls(self):
        (self.u / "run" / "systemctl.calls").write_text("")

    def v2_protocol(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(self.sock)
            conn.sendall(b'{"v": 2, "id": "p", "method": "core.protocol", "params": {}}\n')
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.split(b"\n", 1)[0])

    def hashes(self):
        return {name: sha(path) for name, path in (("devices.json", self.u / "state" / "devices.json"),
                                                   ("auth.toml", self.u / "etc" / "auth.toml"),
                                                   ("core.toml", self.u / "etc" / "core.toml"))}

    def processes(self):
        out = subprocess.run(["pgrep", "-fc", f"{self.u}/service.py"], capture_output=True, text=True)
        return int(out.stdout.strip() or 0)

    def backups(self):
        root = self.u / "backups"
        return sorted(root.iterdir()) if root.exists() else []


@pytest.fixture
def sim(tmp_path):
    simulation = Sim(tmp_path)
    yield simulation
    simulation.systemctl("stop", "rain-core")


def make_bundle(tmp_path: Path, wheel_020: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    shutil.copy(wheel_020, bundle / WHEEL_020)
    shutil.copy(accepted_011_wheel(), bundle / WHEEL_011)
    for script in ("update-0.2.0.sh", "rollback-0.1.1.sh"):
        shutil.copy(ROOT / "deploy" / script, bundle / script)
    (bundle / "SHA256SUMS").write_text("".join(f"{sha(bundle / n)}  {n}\n" for n in sorted(os.listdir(bundle))))
    return bundle


def release_bundle(tmp_path: Path, source: Path) -> Path:
    """RAIN_P2_BUNDLE=<dir>: exercise the delivered bundle itself (wheels, scripts and SHA256SUMS as shipped)."""
    bundle = tmp_path / "bundle"
    shutil.copytree(source, bundle)
    assert subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=bundle).returncode == 0
    return bundle


def test_77_update_and_rollback(sim, tmp_path):
    if os.environ.get("RAIN_P2_BUNDLE"):
        bundle = release_bundle(tmp_path, Path(os.environ["RAIN_P2_BUNDLE"]))
    else:
        bundle = make_bundle(tmp_path, build_020_wheel(tmp_path / "wheel"))
    sim.pip_install(bundle / WHEEL_011)
    assert sim.version() == "0.1.1"
    sim.systemctl("start", "rain-core")
    assert sim.health_version() == "0.1.1"
    assigned = sim.smoke("assign", UBLOX)
    assert assigned["ok"] is True, assigned
    a0 = sim.assignment()
    assert a0["device_id"] == UBLOX and a0["alias"] == "smoke"
    before = sim.hashes()
    sim.clear_calls()

    # -- a corrupt wheel is refused before anything is stopped
    bad = tmp_path / "bad"
    shutil.copytree(bundle, bad)
    with open(bad / WHEEL_020, "ab") as handle:
        handle.write(b"x")
    result = sim.run("bash", str(bad / "update-0.2.0.sh"))
    assert result.returncode != 0 and "does not match SHA256SUMS" in result.stderr
    assert "stop rain-core" not in sim.calls() and sim.version() == "0.1.1" and sim.backups() == []
    assert sim.systemctl("is-active", "rain-core").returncode == 0

    # -- K3 pre-flight: a wrongly owned state dir, or an existing "rain" account, stops the update
    result = sim.run("bash", str(bundle / "update-0.2.0.sh"), env={"RAIN_SERVICE_USER": "rain-core-p2-expected"})
    assert result.returncode != 0 and "K3 pre-flight" in result.stderr and "is owned by" in result.stderr
    result = sim.run("bash", str(bundle / "update-0.2.0.sh"), env={"RAIN_LEGACY_USER": getpass.getuser()})
    assert result.returncode != 0 and "K3 pre-flight" in result.stderr and "exists" in result.stderr
    assert "stop rain-core" not in sim.calls() and sim.version() == "0.1.1" and sim.backups() == []

    # -- the update
    sim.clear_calls()
    result = sim.run("bash", str(bundle / "update-0.2.0.sh"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: rain-core 0.2.0 running" in result.stdout
    assert sim.version() == "0.2.0" and sim.health_version() == "0.2.0"
    assert sim.v2_protocol()["result"]["versions"] == [1, 2]
    assert sim.processes() == 1
    assert sim.hashes() == before
    assert sim.assignment() == a0
    assert (sim.u / "py" / "bin" / "rain-core-admin").exists()
    assert not (sim.u / "etc" / "sessions.toml").exists() and not (sim.u / "state" / "accounts.json").exists()
    assert sim.calls() == ["stop rain-core", "start rain-core", "is-active rain-core"]
    (backup,) = sim.backups()
    assert backup.name.endswith("-pre-0.2.0") and (backup.stat().st_mode & 0o777) == 0o700
    assert sorted(p.name for p in backup.iterdir()) == ["INFO", "SHA256SUMS", "auth.toml", "core.toml", "devices.json"]
    assert subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=backup).returncode == 0
    for name in ("devices.json", "auth.toml", "core.toml"):
        assert sha(backup / name) == before[name]
    assert "rain_core_version=0.1.1" in (backup / "INFO").read_text()

    # -- idempotent
    result = sim.run("bash", str(bundle / "update-0.2.0.sh"))
    assert result.returncode == 0 and "nothing to install" in result.stdout
    assert len(sim.backups()) == 1 and sim.hashes() == before

    # -- restart (reboot stand-in)
    sim.systemctl("stop", "rain-core")
    sim.systemctl("start", "rain-core")
    assert sim.health_version() == "0.2.0" and sim.assignment() == a0 and sim.hashes() == before

    # -- 0.2.0-only state exists before the rollback (accounts.json, as rain-core-admin would write it)
    write_accounts(sim.u / "state", default_accounts())
    accounts_sha = sha(sim.u / "state" / "accounts.json")

    # -- rollback to the accepted 0.1.1 wheel, against the 0.2.0-written state
    time.sleep(1.1)  # distinct backup timestamp
    result = sim.run("bash", str(bundle / "rollback-0.1.1.sh"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: rain-core 0.1.1 running" in result.stdout
    assert sim.version() == "0.1.1" and sim.health_version() == "0.1.1"
    assert sim.assignment() == a0 and sim.hashes() == before
    assert sim.processes() == 1
    assert not (sim.u / "py" / "bin" / "rain-core-admin").exists()
    assert sha(sim.u / "state" / "accounts.json") == accounts_sha  # left in place, ignored by 0.1.1
    rollback_backup = sim.backups()[-1]
    assert rollback_backup.name.endswith("-pre-rollback-0.1.1")
    assert sha(rollback_backup / "accounts.json") == accounts_sha
    result = sim.run("bash", str(bundle / "rollback-0.1.1.sh"))
    assert result.returncode == 0 and "nothing to install" in result.stdout

    # -- the rollback refuses a 0.1.1 wheel that is not the Pi-accepted artifact
    other = tmp_path / "other"
    shutil.copytree(bundle, other)
    sim.systemctl("stop", "rain-core")
    sim.pip_install(bundle / WHEEL_020)
    sim.systemctl("start", "rain-core")
    with open(other / WHEEL_011, "ab") as handle:
        handle.write(b"\0")
    sums = [line for line in (other / "SHA256SUMS").read_text().splitlines() if not line.endswith(f"  {WHEEL_011}")]
    (other / "SHA256SUMS").write_text("\n".join(sums + [f"{sha(other / WHEEL_011)}  {WHEEL_011}"]) + "\n")
    sim.clear_calls()
    result = sim.run("bash", str(other / "rollback-0.1.1.sh"))
    assert result.returncode != 0 and "not the Pi-accepted 0.1.1 wheel" in result.stderr
    assert "stop rain-core" not in sim.calls() and sim.version() == "0.2.0"

    # -- back to 0.1.1, then re-apply 0.2.0: hashes still equal the original values
    assert sim.run("bash", str(bundle / "rollback-0.1.1.sh")).returncode == 0
    time.sleep(1.1)
    result = sim.run("bash", str(bundle / "update-0.2.0.sh"))
    assert result.returncode == 0, result.stderr
    assert sim.health_version() == "0.2.0" and sim.assignment() == a0 and sim.hashes() == before
