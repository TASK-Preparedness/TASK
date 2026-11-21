# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Bundle r3 end-to-end simulation of preflight / install-0.2.1.sh / healthcheck.sh /
rollback-0.2.0.sh against a stand-in rain-core 0.2.0 install (off-target, no root).

A venv stands in for the system python, a systemctl shim runs a real rain_core Core
(installed from the bundle wheels) with a fake enumerator, on a temp socket.

r3 - realistic authorization (the r1/r2 sims did not have it):
  * auth.toml [peers] does NOT list the uid that runs the scripts (only an unrelated uid
    4242), so the scripts are a *public* peer, exactly like root on the Pi
    (pi-install.sh:66 never authorizes uid 0; auth.py:20-27 -> "public"). The r1/r2 sims
    listed the sim's own uid as administrator, so `rain-smoke devices` succeeded there.
  * operator/administrator work (hooks, assertions, the optional authenticated check)
    goes through the real 0.2.x session path: sessions.toml [clients] + accounts.json
    (dragon=administrator, op=operator; test passwords from tests/p2fixtures.py), v2
    session.login, then device.list/assign/unassign with the session token.
  * the r2 scripts (git show 3b0083b) are run first and must reproduce the Pi incident:
    `rain-smoke devices` -> forbidden, exit 1 -> install stops a healthy 0.2.1.
  * hot-plug state is switchable (run/hotplug.state) to simulate a genuinely unhealthy Core.
Not exercisable here: the root -> `runuser -u $SUDO_USER` hop of --authenticated (needs
root); the same rain-core-admin call is made directly as the (non-root) sim user.

Usage: python3 sim_install.py <bundle-dir> <log-file> [<r1-bundle-dir>]
"""
from __future__ import annotations

import dataclasses
import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def _find_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path("/workspace/rain-h1-wt"), Path.cwd()):
        if (candidate / "tests" / "p2fixtures.py").is_file() and (candidate / "share").is_dir():
            return candidate
    raise SystemExit("cannot locate rain-h1-wt (tests/p2fixtures.py + share/)")


ROOT = _find_root()
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from p2fixtures import (CP2102_ID, DRAGON_PW, OP_PW, SDR_ID, UBLOX_ID, default_accounts,  # noqa: E402
                        golden_devices, write_accounts, write_sessions)

WHEEL_020_SHA = "253572c5e3f7b09012292b451460f2cae8a97ad529f20780c05174790b892bad"
WHEEL_021_SHA = "fd407875504e9a7036f742d583a23680008d802b67a384f09d8289c5de600ee8"
CONSOLE_WHEEL = Path("/workspace/rain-phase2-dist/rain_console-0.1.0-py3-none-any.whl")
SCRIPTS = ("preflight.sh", "backup.sh", "install-0.2.1.sh", "healthcheck.sh", "rollback-0.2.0.sh",
           "_rain_h1_common.sh", "devices_projection.py", "core_checks.py")
R2_SCRIPTS = SCRIPTS[:-1]
R2_COMMIT = "3b0083b"
OTHER_UID = 4242

RUNNER = r'''
import json, sys, threading, time
from pathlib import Path
from rain_core.config import load_config
from rain_core.devices import RawDevice
from rain_core.main import Core
RUN = Path(%(run)r)
class Fake:
    def start(self, on_appear, on_disappear, on_change):
        devices = [RawDevice(**f) for f in json.loads((RUN / "hw.json").read_text())]
        unplug = RUN / "unplug.json"
        if unplug.exists():
            gone = [RawDevice(**f) for f in json.loads(unplug.read_text())]
            unplug.unlink()
            def later():
                time.sleep(0.3)
                for raw in gone:
                    on_disappear(raw)
                (RUN / "unplug.done").write_text("%%d\n" %% len(gone))
            threading.Thread(target=later, daemon=True).start()
        return devices
    def stop(self):
        return None
    def status(self):
        flag = RUN / "hotplug.state"
        state = flag.read_text().strip() if flag.exists() else "running"
        return {"state": state, "restarts": 0, "missed": 0, "events": 0,
                "dispatch_errors": 0, "last_error": None}
core = Core(load_config(Path(sys.argv[1])), enumerator_factory=Fake)
core.open()
try:
    core.wait()
finally:
    core.close()
'''

SYSTEMCTL = r'''#!/bin/bash
U=%(u)s; PIDF=$U/run/rain-core.pid; LOG=$U/run/rain-core.log
running() { [[ -f $PIDF ]] && kill -0 "$(cat $PIDF)" 2>/dev/null; }
echo "$*" >> $U/run/systemctl.calls
q=0; [[ "$1" == "is-active" && "$2" == "--quiet" ]] && { q=1; set -- is-active "$3"; }
case "$1" in
  start) running || { (cd $U/state && exec $U/py/bin/python $U/service.py $U/etc/core.toml >>$LOG 2>&1 </dev/null) & echo $! > $PIDF;
         for i in $(seq 200); do
           $U/py/bin/python -c "import socket,sys; socket.socket(socket.AF_UNIX).connect(sys.argv[1])" $U/run/core.sock 2>/dev/null && break
           sleep 0.05
         done
         if [[ -f $U/run/after-start.py ]]; then
           mv $U/run/after-start.py $U/run/after-start.ran.py
           $U/py/bin/python $U/run/after-start.ran.py $U/run/core.sock >> $U/run/after-start.log 2>&1
         fi; } ;;
  stop) if running; then kill "$(cat $PIDF)"; for i in $(seq 100); do running || break; sleep 0.05; done; fi; rm -f $PIDF ;;
  is-active) if running; then [[ $q == 1 ]] || echo active; exit 0; else [[ $q == 1 ]] || echo inactive; exit 3; fi ;;
  cat) cat "$U/etc/rain-core.service"; exit 0 ;;
  is-enabled) echo enabled; exit 0 ;;
  *) echo "shim: unsupported $*" >&2; exit 1 ;;
esac
'''

HOOK = r'''
import json, socket, sys
SESSION = None
def raw(method, params, session=None):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sys.argv[1])
    body = {"v": 2, "id": "hook", "method": method, "params": params}
    if session:
        body["session"] = session
    s.sendall((json.dumps(body) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        buf += s.recv(65536)
    s.close()
    return json.loads(buf.split(b"\n", 1)[0])
def call(method, params):
    # administrator work through the real 0.2.x session path (never a [peers] uid)
    global SESSION
    if SESSION is None:
        reply = raw("session.login", {"username": "dragon", "secret": %(pw)r})
        assert reply.get("ok"), reply
        SESSION = reply["result"]["session"]
    if method == "device.assign":
        params = dict(params, confirm_displace=True)
    reply = raw(method, params, SESSION)
    print(method, json.dumps(params), "->", json.dumps(reply))
    assert reply.get("ok"), reply
%(body)s
'''


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Sim:
    def __init__(self, base: Path):
        self.u = base / "u"
        for sub in ("bin", "run", "state", "etc", "deps"):
            (self.u / sub).mkdir(parents=True)
        self.run_dir = self.u / "run"
        self.py = self.u / "py" / "bin" / "python"
        self._make_python()
        self.sock = str(self.u / "run" / "core.sock")
        self.golden = [dataclasses.asdict(raw) for raw in golden_devices()]
        self.set_hw(self.golden)
        (self.u / "service.py").write_text(RUNNER % {"run": str(self.run_dir)})
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
            f'auth_file = "{self.u / "etc" / "auth.toml"}"\n'
            f'sessions_file = "{self.u / "etc" / "sessions.toml"}"\n')
        # r3: the scripts' uid is NOT a peer -> public, like root on the Pi (pi-install.sh:66)
        assert os.getuid() != OTHER_UID
        (self.u / "etc" / "auth.toml").write_text(f'[peers]\n{OTHER_UID} = "administrator"\n')
        write_sessions(self.u / "etc" / "sessions.toml", [os.getuid()])
        write_accounts(self.u / "state", default_accounts())
        os.chmod(self.u / "etc" / "auth.toml", 0o640)
        (self.u / "etc" / "rain-core.service").write_text("[Unit]\nDescription=stand-in\n")
        self.devices = self.u / "state" / "devices.json"
        # devices.json as rain-core writes it (persist.py:72-115): indent=2, mode 0600
        self.devices.write_text(json.dumps({"v": 1, "assignments": {"gps.primary": {
            "device_id": UBLOX_ID, "alias": "smoke"}}}, indent=2) + "\n")
        os.chmod(self.devices, 0o600)
        self.env = {
            "PATH": f"{self.u / 'bin'}:{os.environ['PATH']}",
            "HOME": str(base), "LANG": "C.UTF-8",
            "PYTHON": str(self.py),
            "RAIN_STATE_DIR": str(self.u / "state"),
            "RAIN_ETC_DIR": str(self.u / "etc"),
            "RAIN_BACKUP_ROOT": str(self.u / "backups"),
            "RAIN_UNIT_FILE": str(self.u / "etc" / "rain-core.service"),
            "RAIN_SMOKE": str(smoke),
            "RAIN_SERVICE_USER": getpass.getuser(),
            "RAIN_LEGACY_USER": "rain-h1-test-no-such-account",
            "RAIN_ALLOW_NONROOT": "1",
            "RAIN_SKIP_ARCH": "1",
            "RAIN_SKIP_DEBIAN": "1",
            "RAIN_CONSOLE_WHEEL": str(CONSOLE_WHEEL),
            "RAIN_SOCKET": self.sock,
            "RAIN_CORE_ADMIN": str(self.u / "py" / "bin" / "rain-core-admin"),
        }

    def _make_python(self):
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.u / "py")], check=True)
        import pip
        import yaml
        deps = self.u / "deps"
        for module in (pip, yaml):
            (deps / module.__name__).symlink_to(Path(module.__file__).parent)
        legacy = Path(yaml.__file__).parent.parent / "_yaml"
        if legacy.is_dir():
            (deps / "_yaml").symlink_to(legacy)
        (deps / "pyudev").mkdir()
        (deps / "pyudev" / "__init__.py").write_text("# stand-in\n")
        site = subprocess.run([str(self.py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                              check=True, capture_output=True, text=True).stdout.strip()
        Path(site, "sim-deps.pth").write_text(f"{deps}\n")

    def set_hw(self, devices):
        (self.run_dir / "hw.json").write_text(json.dumps(devices))

    def unplug_after_start(self, devices):
        (self.run_dir / "unplug.json").write_text(json.dumps(devices))

    def hook_after_start(self, body):
        (self.run_dir / "after-start.py").write_text(HOOK % {"pw": DRAGON_PW, "body": body})

    def run(self, *args, env=None, check=False, input_text=None):
        # new session: no controlling terminal, like a non-interactive run
        return subprocess.run(list(args), env=dict(self.env, **(env or {})), capture_output=True, text=True,
                              check=check, cwd="/", input=input_text if input_text is not None else "",
                              start_new_session=True)

    def pip_install(self, wheel):
        self.run(str(self.py), "-m", "pip", "install", "-q", "--no-deps", "--no-index", str(wheel), check=True)

    def version(self):
        return self.run(str(self.py), "-c", "import rain_core; print(rain_core.__version__)").stdout.strip()

    def smoke(self, *args):
        result = self.run(self.env["RAIN_SMOKE"], *args)
        assert result.returncode == 0, result.stderr + result.stdout
        return json.loads(result.stdout)

    def hashes(self):
        return {n: sha(p) for n, p in (("devices.json", self.devices),
                                       ("accounts.json", self.u / "state" / "accounts.json"),
                                       ("sessions.toml", self.u / "etc" / "sessions.toml"),
                                       ("auth.toml", self.u / "etc" / "auth.toml"),
                                       ("core.toml", self.u / "etc" / "core.toml"))}

    def stats(self):
        return {n: self.run("stat", "-c", "%U:%G:%a", str(p)).stdout.strip()
                for n, p in (("auth.toml", self.u / "etc" / "auth.toml"),
                             ("core.toml", self.u / "etc" / "core.toml"),
                             ("devices.json", self.devices))}

    def systemctl(self, *args):
        return self.run("systemctl", *args)

    def calls(self):
        p = self.run_dir / "systemctl.calls"
        return p.read_text().splitlines() if p.exists() else []

    def clear_calls(self):
        (self.run_dir / "systemctl.calls").write_text("")

    def v2(self, method, params=None, session=None):
        body = {"v": 2, "id": "1", "method": method, "params": params or {}}
        if session:
            body["session"] = session
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(self.sock)
            conn.sendall(json.dumps(body).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                buf += conn.recv(65536)
        return json.loads(buf.split(b"\n", 1)[0])

    def operator_list(self):
        """device.list the way an operator gets it on 0.2.x: session.login (op), then v2."""
        login = self.v2("session.login", {"username": "op", "secret": OP_PW})
        assert login["ok"], login
        reply = self.v2("device.list", session=login["result"]["session"])
        assert reply["ok"], reply
        self.v2("session.logout", session=login["result"]["session"])
        return reply["result"]

    def record(self, device_id):
        for item in self.operator_list()["devices"]:
            if item["id"] == device_id:
                return item
        return None

    def assigned(self):
        return {d["logical"]: d["id"] for d in self.operator_list()["devices"] if d.get("logical")}

    def hook(self, body):
        return self.run(str(self.py), "-c", HOOK % {"pw": DRAGON_PW, "body": body}, self.sock)

    def active(self):
        return self.systemctl("is-active", "--quiet", "rain-core").returncode == 0

    def stops_after_last_start(self):
        calls = self.calls()
        starts = [i for i, c in enumerate(calls) if c == "start rain-core"]
        return [c for c in calls[(starts[-1] + 1 if starts else 0):] if c.startswith("stop")]

    def latest_backup(self, label):
        return sorted((self.u / "backups").glob(f"*-{label}"))[-1]


def make_bundle(src: Path, tmp: Path, name="bundle", from_commit=None) -> Path:
    bundle = tmp / name
    bundle.mkdir()
    for script in (R2_SCRIPTS if from_commit else SCRIPTS):
        if from_commit:
            data = subprocess.run(["git", "-C", str(ROOT), "show", f"{from_commit}:deploy/h1-0.2.1/{script}"],
                                  check=True, capture_output=True).stdout
            (bundle / script).write_bytes(data)
        else:
            shutil.copy2(src / script, bundle / script)
    for wheel, digest in (("rain_core-0.2.1-py3-none-any.whl", WHEEL_021_SHA),
                          ("rain_core-0.2.0-py3-none-any.whl", WHEEL_020_SHA)):
        shutil.copy2(src / wheel, bundle / wheel)
        assert sha(bundle / wheel) == digest, wheel
    lines = [f"{sha(p)}  {p.name}" for p in sorted(bundle.iterdir()) if p.is_file()]
    (bundle / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return bundle


def main(argv):
    src = Path(argv[1])
    log_path = Path(argv[2])
    r1 = Path(argv[3]) if len(argv) > 3 else None
    log = []

    def step(msg):
        print(msg, flush=True)
        log.append(msg)

    def out_of(r):
        return r.stdout + r.stderr

    base = Path(tempfile.mkdtemp(prefix="h1r3sim", dir="/tmp"))
    sim = None
    try:
        sim = Sim(base)
        bundle = make_bundle(src, base)
        step(f"bundle (scripts+wheels from {src}) wheels verified: 0.2.1 {WHEEL_021_SHA[:12]}…, 0.2.0 {WHEEL_020_SHA[:12]}…")
        step(f"auth model: scripts run as uid {os.getuid()} which is NOT in auth.toml [peers] (only {OTHER_UID}) "
             "-> public peer, like root on the Pi; operator/admin work via v2 session.login (sessions.toml "
             "[clients] + accounts.json dragon/op)")

        sim.pip_install(bundle / "rain_core-0.2.0-py3-none-any.whl")
        assert sim.version() == "0.2.0"
        sim.systemctl("start", "rain-core")
        assert sim.smoke("health")["result"]["version"] == "0.2.0"
        before = sim.hashes()
        before_stats = sim.stats()
        step(f"baseline 0.2.0 running; hashes={before}; owner:group:mode={before_stats}")

        # ------------------------------------------------ the Pi defect, reproduced
        r = sim.run(sim.env["RAIN_SMOKE"], "devices")
        reply = json.loads(r.stdout)
        assert r.returncode == 1 and reply["ok"] is False and reply["error"]["code"] == "forbidden", out_of(r)
        assert reply["error"]["message"] == "device.list requires operator", reply
        step(f"REPRO `rain-smoke devices` as a public peer: exit 1, error={reply['error']} "
             "(matches the Pi; health stays public)")

        r2b = make_bundle(src, base, "r2bundle", from_commit=R2_COMMIT)
        sim.clear_calls()
        r = sim.run("bash", str(r2b / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode != 0, out
        assert sim.version() == "0.2.1" and not sim.active(), out
        assert "healthcheck FAILED; leaving rain-core stopped" in out, out
        assert sim.stops_after_last_start() == ["stop rain-core"], sim.calls()
        step("REPRO r2 install-0.2.1.sh (git show 3b0083b) with realistic auth: 0.2.1 installed, health OK, "
             "then healthcheck died at `rain-smoke devices` (forbidden) and the installer STOPPED the healthy "
             f"Core (exit {r.returncode}; systemctl calls={sim.calls()}) -> the Pi incident")

        # Joshua's recovery on the Pi: start the unit by hand.
        sim.systemctl("start", "rain-core")
        assert sim.active() and sim.hashes() == before and sim.stats() == before_stats

        # ------------------------------------------------ r3 on the already-upgraded system
        sim.clear_calls()
        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1")
        out = out_of(r)
        assert r.returncode == 0 and "RESULT=PASS" in out, out
        assert "SKIPPED  authenticated device.list (requires operator credentials" in out
        assert "v2 device.counts ok (public, redacted) total=" in out and '"state": "running"' in out, out
        assert sim.calls() == ["is-active --quiet rain-core"], sim.calls()
        step("ALREADY-UPGRADED r3 healthcheck.sh 0.2.1 (no flags): PASS, exit 0; only systemctl is-active "
             "called; SKIPPED authenticated device.list")
        step("  output:\n    " + "\n    ".join(r.stdout.strip().splitlines()))

        for user, pw in (("dragon", DRAGON_PW), ("op", OP_PW)):
            r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1", "--authenticated", "--user", user,
                        "--password-stdin", input_text=pw + "\n")
            out = out_of(r)
            assert r.returncode == 0 and "RESULT=PASS" in out, out
            assert f'OK    gps.primary -> {UBLOX_ID} alias="smoke" connected' in out, out
            assert pw not in out
            step(f"ALREADY-UPGRADED --authenticated --user {user} --password-stdin (real rain-core-admin, real "
                 f"session.login): PASS; gps.primary -> {UBLOX_ID} connected")

        sim.set_hw([d for d in sim.golden if d.get("vid") != "1546"])
        sim.systemctl("stop", "rain-core")
        sim.systemctl("start", "rain-core")
        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1", "--authenticated", "--user", "op",
                    "--password-stdin", input_text=OP_PW + "\n")
        out = out_of(r)
        assert r.returncode == 0 and "RESULT=PASS" in out, out
        assert f"WARN  gps.primary -> {UBLOX_ID} alias=\"smoke\" assigned but DISCONNECTED" in out, out
        step("ALREADY-UPGRADED with the assigned GPS unplugged: authenticated check WARN (assigned but "
             "DISCONNECTED), RESULT=PASS")
        sim.set_hw(sim.golden)
        sim.systemctl("stop", "rain-core")
        sim.systemctl("start", "rain-core")

        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1", "--authenticated", "--user", "dragon")
        out = out_of(r)
        assert r.returncode == 2 and "no terminal for the password prompt" in out and "RESULT=INCOMPLETE" in out, out
        step("--authenticated without a terminal and without --password-stdin: SKIPPED, INCOMPLETE exit 2")

        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1", "--authenticated", "--user", "dragon",
                    "--password-stdin", input_text="x\n", env={"RAIN_CORE_ADMIN": str(base / "nope")})
        out = out_of(r)
        assert r.returncode == 2 and "rain-core-admin not found" in out, out
        step("TOOL-MISSING rain-core-admin: INCOMPLETE exit 2, Core untouched")

        os.rename(sim.env["RAIN_SMOKE"], sim.env["RAIN_SMOKE"] + ".gone")
        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1")
        assert r.returncode == 0 and "RESULT=PASS" in out_of(r), out_of(r)
        sim.clear_calls()
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode == 0 and "nothing to install" in out and "RESULT=PASS" in out, out
        os.rename(sim.env["RAIN_SMOKE"] + ".gone", sim.env["RAIN_SMOKE"])
        assert not any(c.startswith("stop") for c in sim.calls())
        step("TOOL-MISSING rain-smoke: healthcheck PASS and install-0.2.1.sh (already 0.2.1) PASS exit 0, "
             "nothing stopped (rain-smoke no longer needed)")

        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1", "--authenticated", "--user", "dragon",
                    "--password-stdin", input_text="wrong password\n")
        out = out_of(r)
        assert r.returncode == 2 and "authentication or authorization refused (exit 3)" in out, out
        assert "RESULT=INCOMPLETE" in out and sim.active()
        step("WRONG PASSWORD: rain-core-admin exit 3 -> INCOMPLETE exit 2, Core still active")

        sim.clear_calls()
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"), env={"RAIN_CORE_ADMIN": str(base / "nope")})
        assert r.returncode == 0 and "nothing to install" in out_of(r), out_of(r)
        assert "rain-core-admin" not in "".join(l for l in out_of(r).splitlines() if "INCOMPLETE" in l)
        step("install-0.2.1.sh never runs the authenticated check (no credentials needed, exit 0)")

        # ------------------------------------------------ rollback, then a fresh r3 install
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"))
        out = out_of(r)
        assert r.returncode == 0 and "OK: rain-core 0.2.0 running" in out, out
        assert sim.version() == "0.2.0" and "hotplug" not in sim.v2("core.health")["result"]
        assert sim.hashes() == before and sim.stats() == before_stats
        step("rollback to 0.2.0 (r3): PASS (0.2.0 health: no hotplug), hashes == baseline")

        r = sim.run("bash", str(bundle / "preflight.sh"))
        assert r.returncode == 0, out_of(r)
        step("preflight pass OK")

        sim.clear_calls()
        no_gps = [d for d in sim.golden if d.get("vid") != "1546"]
        sim.set_hw(no_gps)
        sim.unplug_after_start([d for d in no_gps if d.get("vid") == "0bda"])
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode == 0 and "OK: rain-core 0.2.1 running" in out and "RESULT=PASS" in out, out
        for _ in range(40):
            if (sim.run_dir / "unplug.done").exists():
                break
            time.sleep(0.05)
        gps = sim.record(UBLOX_ID)
        assert gps["connected"] is False and gps["logical"] == "gps.primary" and gps["alias"] == "smoke"
        assert sim.hashes() == before and sim.stats() == before_stats
        assert sim.stops_after_last_start() == [] and sim.active()
        step("FRESH install 0.2.0->0.2.1 with r3 (realistic auth, GPS unplugged across restart, SDR after): "
             "exit 0 RESULT=PASS; gps.primary kept; config/accounts/sessions hashes unchanged; no stop after start")
        step(f"  systemctl calls={sim.calls()}")
        sim.set_hw(sim.golden)

        if CONSOLE_WHEEL.is_file():
            sim.pip_install(CONSOLE_WHEEL)
            ver = sim.run(str(sim.py), "-c", "import rain_console; print(rain_console.__version__)").stdout.strip()
            assert ver == "0.1.0"
            assert sim.v2("device.counts")["ok"] is True
            assert sim.v2("core.protocol")["result"]["versions"] == [1, 2]
            step("rain-console 0.1.0 import + v2 counts/protocol against 0.2.1 OK")

        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        assert r.returncode == 0 and "nothing to install" in out_of(r), out_of(r)
        assert sim.hashes() == before
        step("idempotent install OK")

        # ------------------------------------------------ genuinely unhealthy Core
        (sim.run_dir / "hotplug.state").write_text("stopped\n")
        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1")
        out = out_of(r)
        assert r.returncode == 1 and "hotplug.state='stopped' is not alive" in out and "RESULT=FAIL-CORE" in out, out
        sim.clear_calls()
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode == 1 and "healthcheck FAIL-CORE" in out and "This script did NOT stop it" in out, out
        assert "rollback-0.2.0.sh" in out and sim.active()
        assert not any(c.startswith("stop") for c in sim.calls())
        step("UNHEALTHY hotplug.state=stopped: healthcheck FAIL-CORE exit 1; install-0.2.1.sh (already 0.2.1) "
             "exit 1, rollback command printed, service NOT stopped by the script")
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"))
        assert r.returncode == 0 and sim.version() == "0.2.0", out_of(r)
        sim.clear_calls()
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode == 1 and "healthcheck FAIL-CORE" in out and "Rollback command: re-run or" not in out, out
        assert sim.version() == "0.2.1" and sim.active() and sim.stops_after_last_start() == []
        step("UNHEALTHY during a fresh install (0.2.0->0.2.1, hotplug stopped): exit 1 FAIL-CORE, unit left "
             "running for inspection (decision: never stop after start), rollback command printed")
        (sim.run_dir / "hotplug.state").unlink()
        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1")
        assert r.returncode == 0, out_of(r)

        pid = int((sim.run_dir / "rain-core.pid").read_text())
        os.kill(pid, 15)
        for _ in range(100):
            if not sim.active():
                break
            time.sleep(0.05)
        r = sim.run("bash", str(bundle / "healthcheck.sh"), "0.2.1")
        out = out_of(r)
        assert r.returncode == 1 and "unit rain-core is not active" in out and "RESULT=FAIL-CORE" in out, out
        step("UNHEALTHY process killed: healthcheck FAIL-CORE exit 1 ('unit rain-core is not active')")
        sim.systemctl("start", "rain-core")
        assert sim.active()

        # ------------------------------------------------ legitimate change after snapshot
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"))
        assert r.returncode == 0 and "0 file(s) drifted" in out_of(r), out_of(r)
        time.sleep(1.1)
        sim.hook_after_start(
            f'call("device.assign", {{"logical": "mesh.primary", "device_id": "{CP2102_ID}", "alias": "lora"}})\n')
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode == 0, out
        assert (sim.run_dir / "after-start.ran.py").exists()
        assert f"INFO  new device id {CP2102_ID}" in out and "INFO  new assignment mesh.primary" in out, out
        snap = sim.latest_backup("pre-0.2.1")
        step("LEGIT assign (v2 session, dragon) between start and healthcheck: install PASS, INFO new assignment")
        if r1 is not None:
            old = base / "r1"
            old.mkdir()
            for script in ("healthcheck.sh", "_rain_h1_common.sh"):
                shutil.copy2(r1 / script, old / script)
            r = sim.run("bash", str(old / "healthcheck.sh"), "0.2.1", env={"RAIN_PRE_SNAPSHOT": str(snap)})
            assert r.returncode != 0, out_of(r)
            step(f"  r1 healthcheck.sh on the same state: exit {r.returncode} (fails: byte-hash check documented in r2, and r1 also calls `rain-smoke devices`)")
        r = sim.hook('call("device.unassign", {"logical": "mesh.primary"})')
        assert r.returncode == 0, out_of(r)
        assert sim.hashes() == before and sim.stats() == before_stats
        step("  undo: unassign mesh.primary -> devices.json bytes back to baseline")

        # ------------------------------------------------ assignment lost after snapshot
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"))
        assert r.returncode == 0, out_of(r)
        time.sleep(1.1)
        sim.hook_after_start('call("device.unassign", {"logical": "gps.primary"})\n')
        sim.clear_calls()
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        out = out_of(r)
        assert r.returncode == 3, out
        assert "FAIL  assignment gps.primary MISSING" in out and "healthcheck FAIL-STATE" in out, out
        assert "rain-core was NOT stopped" in out and "rollback-0.2.0.sh" in out
        assert sim.active() and sim.stops_after_last_start() == []
        step("ASSIGNMENT LOST after snapshot: install exit 3 FAIL-STATE ('assignment gps.primary MISSING'), "
             "rain-core left RUNNING (r2 stopped it), rollback command printed")

        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"))
        assert r.returncode == 0 and "1 file(s) drifted (devices.json)" in r.stdout and "NOT restored" in r.stdout, out_of(r)
        step("rollback without --restore-config: drift reported, NOT restored OK")
        time.sleep(1.1)
        sim.pip_install(bundle / "rain_core-0.2.1-py3-none-any.whl")
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"), "--restore-config")
        assert r.returncode == 0 and "restored devices.json" in r.stdout, out_of(r)
        assert sim.hashes() == before and sim.stats() == before_stats
        assert sim.assigned().get("gps.primary") == UBLOX_ID
        step("rollback --restore-config: devices.json restored; gps.primary back; hashes == baseline OK")

        # ------------------------------------------------ restore refuses to drop a newer assignment
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        assert r.returncode == 0, out_of(r)
        r = sim.hook('call("device.unassign", {"logical": "gps.primary"})\n'
                     f'call("device.assign", {{"logical": "sdr.primary", "device_id": "{SDR_ID}", "alias": "sdr"}})')
        assert r.returncode == 0, out_of(r)
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "rollback-0.2.0.sh"), "--restore-config")
        assert r.returncode == 0, out_of(r)
        assert "would drop assignment(s) made after the pre-0.2.1 backup: sdr.primary; NOT restored" in r.stdout
        assigned = sim.assigned()
        assert "sdr.primary" in assigned and "gps.primary" not in assigned
        step("rollback --restore-config refuses to drop a newer assignment (sdr.primary) OK")
        r = sim.hook('call("device.unassign", {"logical": "sdr.primary"})\n'
                     f'call("device.assign", {{"logical": "gps.primary", "device_id": "{UBLOX_ID}", "alias": "smoke"}})')
        assert r.returncode == 0, out_of(r)
        assert sim.hashes() == before and sim.stats() == before_stats
        step("  undo -> devices.json bytes back to baseline")

        # ------------------------------------------------ re-install, idempotency, wrong rollback wheel
        time.sleep(1.1)
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        assert r.returncode == 0 and "RESULT=PASS" in out_of(r), out_of(r)
        assert sim.version() == "0.2.1" and sim.hashes() == before and sim.stats() == before_stats
        r = sim.run("bash", str(bundle / "install-0.2.1.sh"))
        assert r.returncode == 0 and "nothing to install" in out_of(r), out_of(r)
        step("re-install 0.2.1 + idempotent re-run OK")

        other = base / "other"
        shutil.copytree(bundle, other)
        with open(other / "rain_core-0.2.0-py3-none-any.whl", "ab") as f:
            f.write(b"\0")
        sums = [line for line in (other / "SHA256SUMS").read_text().splitlines()
                if not line.endswith("  rain_core-0.2.0-py3-none-any.whl")]
        sums.append(f"{sha(other / 'rain_core-0.2.0-py3-none-any.whl')}  rain_core-0.2.0-py3-none-any.whl")
        (other / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        sim.clear_calls()
        r = sim.run("bash", str(other / "rollback-0.2.0.sh"))
        assert r.returncode != 0 and "not the delivered 0.2.0 wheel" in r.stderr, out_of(r)
        assert "stop rain-core" not in sim.calls() and sim.version() == "0.2.1"
        step("rollback refuses non-delivered 0.2.0 wheel OK")

        bad = base / "badwheel"
        shutil.copytree(bundle, bad)
        with open(bad / "rain_core-0.2.1-py3-none-any.whl", "ab") as f:
            f.write(b"y")
        r = sim.run("bash", str(bad / "preflight.sh"))
        assert r.returncode != 0 and "does not match SHA256SUMS" in r.stderr, out_of(r)
        badscript = base / "badscript"
        shutil.copytree(bundle, badscript)
        with open(badscript / "core_checks.py", "a") as f:
            f.write("\n# tampered\n")
        r = sim.run("bash", str(badscript / "preflight.sh"))
        assert r.returncode != 0 and "core_checks.py does not match SHA256SUMS" in r.stderr, out_of(r)
        step("preflight refuses corrupt 0.2.1 wheel and tampered core_checks.py OK")

        assert sim.hashes() == before and sim.stats() == before_stats
        step("final: devices.json/auth.toml/core.toml/accounts.json/sessions.toml hashes and owner:group:mode == baseline")
        step("ALL r3 SIMULATION CHECKS PASSED")
        return 0
    finally:
        if sim is not None:
            sim.systemctl("stop", "rain-core")
            hook_log = sim.run_dir / "after-start.log"
            if hook_log.exists():
                log.append("--- after-start hook log ---")
                log.extend(hook_log.read_text().splitlines())
        log_path.write_text("\n".join(log) + "\n")
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
