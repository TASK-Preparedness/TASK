# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4C task-core-migrate in an isolated sandbox root (temp tree + fake systemctl).

Isolation: every test works under a pytest tmp_path "root"; systemctl is a stand-in
script recording calls in a JSON state file. Nothing touches /etc, /var or systemd.
Interruption is simulated by killing a child process (os._exit, i.e. no cleanup,
like a power cut) at chosen points, then re-running.
"""

import json
import os
import socket
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import task_core_migrate as migrate
from task_core import exclusion
from task_core.config import load_config

ROOT = Path(__file__).resolve().parents[1]

FAKE_SYSTEMCTL = textwrap.dedent('''\
    #!%(py)s
    import json, sys
    state = %(state)r
    s = json.load(open(state))
    args = [a for a in sys.argv[1:] if a != "--quiet"]
    s["calls"].append(" ".join(args))
    verb, unit = args[0], args[1]
    u = s["units"].setdefault(unit, {"active": False, "enabled": False})
    rc = 0
    if verb == "is-active": rc = 0 if u["active"] else 3
    elif verb == "is-enabled": rc = 0 if u["enabled"] else 1
    elif verb == "stop": u["active"] = False
    elif verb == "start":
        if unit == "task-core.service" and s["units"].get("rain-core.service", {}).get("active"):
            rc = 1  # Conflicts= stand-in
        else: u["active"] = True
    elif verb == "enable": u["enabled"] = True
    elif verb == "disable": u["enabled"] = False
    json.dump(s, open(state, "w"))
    sys.exit(rc)
''')


class Sandbox:
    def __init__(self, tmp: Path):
        self.root = tmp / "root"
        self.state = tmp / "systemctl.json"
        self.sc_path = tmp / "systemctl"
        self.state.write_text(json.dumps({"calls": [], "units": {
            "rain-core.service": {"active": True, "enabled": True},
            "task-core.service": {"active": False, "enabled": False}}}))
        self.sc_path.write_text(FAKE_SYSTEMCTL % {"py": sys.executable, "state": str(self.state)})
        self.sc_path.chmod(0o755)
        etc, var = self.root / "etc/rain", self.root / "var/lib/rain"
        (etc / "devices").mkdir(parents=True)
        var.mkdir(parents=True)
        (etc / "core.toml").write_text((ROOT / "deploy/core.toml").read_text())
        (etc / "auth.toml").write_text((ROOT / "deploy/auth.toml").read_text())
        (etc / "auth.toml").chmod(0o640)
        (etc / "sessions.toml").write_text('# login clients\n[clients]\n"kado" = true\n')
        (etc / "devices/rules.yaml").write_text("rules: []\n")
        (var / "accounts.json").write_text(json.dumps({"version": 1, "accounts": {"kado": {"uid": 1000}}}))
        (var / "accounts.json").chmod(0o600)
        (var / "devices.json").write_text(json.dumps({"version": 1, "devices": {}, "assignments":
                                                      {"mesh.primary": "dev-1"}}))
        for i in range(40):  # enough files that interruption points land mid-copy
            (var / f"blob{i:02d}.bin").write_bytes(os.urandom(2048))
        (var / "current").symlink_to("devices.json")
        var.chmod(0o750)

    def units(self):
        return json.loads(self.state.read_text())["units"]

    def calls(self):
        return json.loads(self.state.read_text())["calls"]

    def migrator(self, **kw):
        return migrate.Migrator(str(self.root), migrate.Systemctl(str(self.sc_path)), **kw)

    def snapshot(self, rel):
        return migrate.manifest(self.root / rel)

    def run_cli(self, *args, crash=None):
        """Run the CLI in a child; crash=(method, n) kills it (os._exit) on the n-th call."""
        code = ["import os, sys", "import task_core_migrate as migrate"]
        if crash:
            meth, n = crash
            code += [f"orig = migrate.Migrator.{meth}", "count = [0]",
                     "def hook(self, *a, **k):",
                     f"    count[0] += 1",
                     f"    if count[0] == {n}: os._exit(137)",
                     "    return orig(self, *a, **k)",
                     f"migrate.Migrator.{meth} = hook"]
        code += [f"sys.exit(migrate.main({['--root', str(self.root), '--systemctl', str(self.sc_path), *args]!r}))"]
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.run([sys.executable, "-c", "\n".join(code)], env=env, capture_output=True, text=True)


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def _all(sb):
    return migrate.manifest(sb.root)


def test_m01_dry_run_changes_nothing(sb):
    before = _all(sb)
    r = sb.run_cli("--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would copy /var/lib/rain" in r.stdout and '"/var/lib/task"' in r.stdout
    assert _all(sb) == before
    assert all(c.startswith("is-") for c in sb.calls())


def test_m02_migrate_copies_verifies_rewrites(sb):
    legacy_etc, legacy_var = sb.snapshot("etc/rain"), sb.snapshot("var/lib/rain")
    r = sb.run_cli()
    assert r.returncode == 0, r.stdout + r.stderr
    assert sb.snapshot("etc/rain") == legacy_etc  # /etc/rain never written
    var_now = sb.snapshot("var/lib/rain")
    assert set(var_now) - set(legacy_var) == {"MIGRATED-TO-TASK"}
    assert {k: v for k, v in var_now.items() if k != "MIGRATED-TO-TASK"} == legacy_var
    assert stat.S_IMODE((sb.root / "var/lib/rain").stat().st_mode) == 0o550
    new_var = sb.snapshot("var/lib/task")
    for rel, e in legacy_var.items():
        assert new_var[rel]["mode"] == e["mode"] and new_var[rel].get("sha256") == e.get("sha256")
    cfg_path = sb.root / "etc/task/core.toml"
    text = cfg_path.read_text()
    assert "/var/lib/task" in text and "/run/task/core.sock" in text and "rain" not in text
    load_config(cfg_path)
    assert (sb.root / "etc/task/MIGRATED").is_file()
    assert (sb.root / "etc/task/auth.toml").read_bytes() == (sb.root / "etc/rain/auth.toml").read_bytes()
    assert stat.S_IMODE((sb.root / "etc/task/auth.toml").stat().st_mode) == 0o640
    assert json.loads((sb.root / "var/lib/task/devices.json").read_text())["assignments"] == {"mesh.primary": "dev-1"}
    assert os.readlink(sb.root / "var/lib/task/current") == "devices.json"
    assert sb.units()["rain-core.service"] == {"active": False, "enabled": False}
    assert not sb.units()["task-core.service"]["active"]  # never started by the tool
    backups = list((sb.root / "var/backups").glob("task-core-migrate-*.tar.gz"))
    assert len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert not list((sb.root / "var/lib/task").glob(".staging*"))


@pytest.mark.parametrize("crash", [("_copy_file", 1), ("_copy_file", 23), ("_copy_file", 44),
                                   ("verify", 1), ("rewrite", 1), ("promote", 1), ("save_journal", 2),
                                   ("save_journal", 5), ("save_journal", 9)])
def test_m03_power_cut_then_resume(sb, crash):
    legacy_etc = sb.snapshot("etc/rain")
    legacy_var = sb.snapshot("var/lib/rain")
    r = sb.run_cli(crash=crash)
    assert r.returncode == 137
    assert sb.snapshot("etc/rain") == legacy_etc  # legacy intact after the cut
    assert {k: v for k, v in sb.snapshot("var/lib/rain").items() if k != "MIGRATED-TO-TASK"} == legacy_var
    assert not (sb.root / "etc/task/MIGRATED").exists()
    r = sb.run_cli()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "resuming" in r.stdout or crash == ("save_journal", 2)
    new = sb.snapshot("var/lib/task")
    assert {k: v["sha256"] for k, v in new.items() if v["type"] == "file"} == \
        {k: v["sha256"] for k, v in legacy_var.items() if v["type"] == "file"}
    assert (sb.root / "etc/task/MIGRATED").is_file()
    assert "rain" not in (sb.root / "etc/task/core.toml").read_text()


def test_m04_power_cut_then_rollback_restores_legacy(sb):
    legacy_var = sb.snapshot("var/lib/rain")
    assert sb.run_cli(crash=("_copy_file", 10)).returncode == 137
    r = sb.run_cli("--rollback")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sb.snapshot("var/lib/rain") == legacy_var
    assert sb.units()["rain-core.service"] == {"active": True, "enabled": True}


def test_m05_migration_and_core_exclude_each_other(sb):
    held = exclusion.StateLock(sb.root / "var/lib/task").acquire()  # a running task-core
    try:
        r = sb.run_cli()
        assert r.returncode == 1 and "locked" in r.stderr
        assert sb.units()["rain-core.service"]["active"]  # refused before touching anything
    finally:
        held.release()
    m = sb.migrator(out=open(os.devnull, "w"))
    m.lock()
    try:
        with pytest.raises(exclusion.ExclusionError):
            exclusion.guard(sb.root / "var/lib/task", "/nonexistent/core.sock", proc_root=sb.root / "noproc")
    finally:
        m.unlock()
    exclusion.guard(sb.root / "var/lib/task", "/nonexistent/core.sock", proc_root=sb.root / "noproc",
                    legacy_socket=str(sb.root / "nosock")).release()


def test_m06_guard_detects_legacy_process_and_socket(tmp_path):
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242/cmdline").write_bytes(b"/usr/bin/python3\0/usr/local/bin/rain-core\0")
    (proc / "4243").mkdir()
    (proc / "4243/cmdline").write_bytes(b"/usr/local/bin/rain-core-admin\0accounts\0")
    (proc / "4244").mkdir()
    (proc / "4244/cmdline").write_bytes(b"/usr/bin/python3\0-m\0rain_core\0--config\0/etc/rain/core.toml\0")
    assert exclusion.legacy_processes(proc, self_pid=1) == [4242, 4244]
    (proc / "4244/cmdline").write_bytes(b"/usr/bin/python3\0-m\0task_core\0")
    with pytest.raises(exclusion.ExclusionError, match="4242"):
        exclusion.guard(tmp_path / "state", "/x/core.sock", proc_root=proc, legacy_socket=str(tmp_path / "none"))
    (proc / "4242/cmdline").write_bytes(b"/usr/bin/task-core\0")
    sock_path = str(tmp_path / "legacy.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    try:
        with pytest.raises(exclusion.ExclusionError, match="live Core"):
            exclusion.guard(tmp_path / "state", "/x/core.sock", proc_root=proc, legacy_socket=sock_path)
        compat = tmp_path / "compat.sock"
        compat.symlink_to(sock_path)  # compat symlink pointing at our own socket is fine
        exclusion.guard(tmp_path / "state", sock_path, proc_root=proc, legacy_socket=str(compat)).release()
    finally:
        srv.close()


def test_m07_rollback_after_success_and_remigrate(sb):
    legacy_var = sb.snapshot("var/lib/rain")
    assert sb.run_cli().returncode == 0
    (sb.root / "var/lib/task/accounts.json").write_text('{"newer": true}')  # task-core ran afterwards
    r = sb.run_cli("--rollback")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sb.snapshot("var/lib/rain") == legacy_var
    assert not (sb.root / "etc/task/MIGRATED").exists()
    kept = list((sb.root / "var/lib").glob("task.rolled-back-*"))
    assert len(kept) == 1 and json.loads((kept[0] / "accounts.json").read_text()) == {"newer": True}
    assert sb.units()["rain-core.service"] == {"active": True, "enabled": True}
    r = sb.run_cli()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sb.root / "etc/task/MIGRATED").is_file()


def test_m08_refusals(sb):
    st = json.loads(sb.state.read_text())
    st["units"]["task-core.service"]["active"] = True
    sb.state.write_text(json.dumps(st))
    r = sb.run_cli()
    assert r.returncode == 1 and "task-core.service is active" in r.stdout
    st["units"]["task-core.service"]["active"] = False
    sb.state.write_text(json.dumps(st))
    assert sb.run_cli().returncode == 0
    r = sb.run_cli()
    assert r.returncode == 1  # already migrated
    assert sb.run_cli("--rollback").returncode == 0
    assert sb.run_cli("--rollback").returncode == 1  # nothing left to roll back


def test_m09_cli_safety():
    with pytest.raises(SystemExit):
        migrate.main(["--systemctl", "/tmp/fake"])  # fake systemctl never allowed on the real root
    with pytest.raises(SystemExit):
        migrate.main(["--root", "relative", "--dry-run"])
    src = (ROOT / "task_core_migrate/__init__.py").read_text()
    assert "shell=True" not in src and "os.system" not in src and "rmtree(self.p(old" not in src


def test_m10_legacy_change_during_migration_aborts(sb):
    m = sb.migrator(out=open(os.devnull, "w"))
    orig = m.copy

    def copy_then_tamper():
        orig()
        (sb.root / "var/lib/rain/devices.json").write_text("{}")  # a still-running legacy writer
    m.copy = copy_then_tamper
    with pytest.raises(migrate.MigrateError, match="changed during migration"):
        m.migrate()
    assert not (sb.root / "etc/task/MIGRATED").exists()
    assert not (sb.root / "var/lib/task/devices.json").exists()  # nothing promoted
