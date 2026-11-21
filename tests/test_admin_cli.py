# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 78-89, 91, 92: the D14 terminal recovery CLI (task-core-admin session subcommands).

In-process runs use the real admin.main() entry point with injected getpass / tty / stdin.
Signal, prompt and argv tests run the real CLI as a subprocess on a pseudo-terminal.
A server-side spy records every request the CLI sends.
"""

import builtins
import errno
import json
import os
import pty
import re
import select
import signal
import socket
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path

import pytest

from task_core import admin_client
from task_core.devices import RawDevice

from conftest import LineClient
from p2fixtures import (CP2102_ID, DRAGON_PW, OP_PW, SDR_ID, UBLOX_ID, FakeTTY, V2Client, fixture_devices_json,  # noqa
                        identifying_findings, login, p2env, request_spy, run_admin)

ROOT = Path(__file__).resolve().parents[1]
SESSION_COMMANDS = [["status"], ["devices"], ["devices", "--detail", "gps.primary"], ["assignments"], ["events"],
                    ["events", "--since", "0"], ["report"]]


def cli(core, argv, user="op", password=None, **kwargs):
    password = password if password is not None else (DRAGON_PW if user == "dragon" else OP_PW)
    full = list(argv) + ["--socket", core.config.socket]
    if user is not None:
        full += ["--user", user]
    passwords = kwargs.pop("passwords", [password])
    return run_admin(full, passwords=passwords, **kwargs)


def token_spy(core):
    """Record login tokens issued (to probe them directly afterwards) and requests."""
    tokens, seen = [], []
    original = core.handle_v2

    def spy(payload, uid):
        seen.append((payload.get("method"), "session" in payload, dict(payload.get("params") or {})))
        response, stream = original(payload, uid)
        if payload.get("method") == "session.login" and response.get("ok"):
            tokens.append(response["result"]["session"])
        return response, stream

    core.handle_v2 = spy
    return tokens, seen


def assert_dead(core, token):
    client = V2Client(core.config.socket)
    assert client.call("core.health", session=token)["error"]["code"] == "unauthenticated"
    client.close()


# ------------------------------------------------------------------ pty runner

def pty_cli(argv, steps=(), env=None, timeout=25, on_output=None, stdin_data=None):
    """Run `python -m task_core.admin argv` on a pty. steps: [(expect_regex, action)].

    action is bytes (typed) or a callable(pid). Returns (exit code, output bytes, pid).
    """
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(ROOT),
                   "HOME": env.pop("HOME") if env and "HOME" in env else tempfile.mkdtemp(prefix="rnhome")}
    environment.update(env or {})
    # The child only calls chdir and execve (async-signal-safe, no Python locks taken), so the
    # forkpty-in-a-threaded-process DeprecationWarning does not apply here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(environment["HOME"])
            os.execve(sys.executable, [sys.executable, "-m", "task_core.admin"] + list(argv), environment)
        finally:
            os._exit(127)
    output = b""
    pending = list(steps)
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        if on_output is not None:
            on_output(pid, output)
        ready, _, _ = select.select([fd], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                break
            output += chunk
        while pending and re.search(pending[0][0], output.decode("utf-8", "replace")):
            _pattern, action = pending.pop(0)
            if callable(action):
                action(pid)
            else:
                os.write(fd, action)
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            try:
                while True:
                    ready, _, _ = select.select([fd], [], [], 0.2)
                    if not ready:
                        break
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    output += chunk
            except OSError:
                pass
            os.close(fd)
            return os.waitstatus_to_exitcode(status), output, pid
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _done, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status), output, pid


# ------------------------------------------------------------------ 78-82: unauthorized access refused

def test_78_no_login_no_detail(p2env):
    core = p2env(peers={})
    seen = request_spy(core)
    for argv in (["devices"], ["assignments"], ["events"], ["report"], ["assign", "sdr.primary", SDR_ID],
                 ["unassign", "gps.primary"]):
        code, out, err, ctx = cli(core, argv, user=None)
        assert code == 1 and "--user NAME" in err and out == ""
        assert ctx.prompts == []
    assert seen == []
    # across every subcommand, no device.* or events.* request is ever sent without a session
    for argv in SESSION_COMMANDS:
        assert cli(core, argv)[0] == 0
    assert cli(core, ["assign", "sdr.primary", SDR_ID, "--yes"], user="dragon")[0] == 0
    assert cli(core, ["unassign", "sdr.primary", "--yes"], user="dragon")[0] == 0
    for method, has_session, _params in seen:
        if method.startswith(("device.", "events.")):
            assert has_session, method
    client = V2Client(core.config.socket)
    assert client.call("device.list")["error"]["code"] == "forbidden"
    client.close()
    v1 = LineClient(core.config.socket)  # [peers] is empty: the post-step-18 state
    assert v1.request("device.list")["error"]["code"] == "forbidden"
    v1.close()


def test_79_wrong_password_unknown_user_rate_limit_and_restart(p2env):
    core = p2env()
    wrong = cli(core, ["status"], user="dragon", password="not the password")
    unknown = cli(core, ["status"], user="nobody", password="not the password")
    for code, out, err, _ctx in (wrong, unknown):
        assert code == 3 and err.strip() == "task-core refused: invalid credentials"
        assert identifying_findings(out) == [] and "dev_" not in out
    for _ in range(3):
        cli(core, ["status"], user="dragon", password="still wrong")
    limited = cli(core, ["status"], user="dragon", password=DRAGON_PW)
    assert limited[0] == 3 and "task-core refused: too many attempts, retry in" in limited[2]
    console = V2Client(core.config.socket)  # the console runs as the same uid
    assert console.call("session.login", {"username": "op", "secret": OP_PW})["error"]["code"] == "rate-limited"
    console.close()
    base, state = core._base, core.config.state_dir
    core.close()
    again = p2env(base=base, state_dir=state)  # simulates systemctl restart task-core
    assert cli(again, ["status"], user="dragon", password=DRAGON_PW)[0] == 0


def test_80_public_stays_public(p2env):
    core = p2env()
    code, out, _err, _ = run_admin(["probe", "--public", "--stream", "0.5", "--socket", core.config.socket])
    assert code == 0
    for line in out.splitlines():
        assert identifying_findings(json.loads(line)) == [], line
    from task_core.admin import build_parser

    for command in admin_client.SESSION_COMMANDS:
        with pytest.raises(SystemExit):
            build_parser().parse_args([command, "--public"])
    for name in ("", "Bad User", "x" * 40):
        code, out, err, _ = cli(core, ["status"], user=name, password="whatever pw")
        assert code == 3 and err.strip() == "task-core refused: invalid credentials"


def test_81_operator_cannot_mutate(p2env, monkeypatch):
    core = p2env()
    path = core.config.state_dir / "devices.json"
    original, inode = path.read_bytes(), os.stat(path).st_ino
    seen = request_spy(core)
    code, _out, err, _ = cli(core, ["assign", "sdr.primary", SDR_ID, "--yes"], user="op")
    assert code == 3 and "device.assign requires administrator (signed in as op \u00b7 operator)" in err
    code, _out, err, _ = cli(core, ["unassign", "gps.primary", "--yes"], user="op")
    assert code == 3 and "device.unassign requires administrator (signed in as op \u00b7 operator)" in err
    assert not [m for m, _s, _p in seen if m in ("device.assign", "device.unassign")]
    monkeypatch.setattr(admin_client, "CLIENT_ROLE_CHECK", False)
    code, _out, err, _ = cli(core, ["assign", "sdr.primary", SDR_ID, "--yes"], user="op")
    assert code == 3 and "task-core refused: device.assign requires administrator" in err
    code, _out, err, _ = cli(core, ["unassign", "gps.primary", "--yes"], user="op")
    assert code == 3 and "task-core refused: device.unassign requires administrator" in err
    assert path.read_bytes() == original and os.stat(path).st_ino == inode


def test_82_no_root_bypass(p2env):
    core = p2env()
    opened = []

    def connect_spy(path):
        opened.append(path)
        raise AssertionError("socket opened")

    for argv in SESSION_COMMANDS + [["assign", "sdr.primary", SDR_ID], ["unassign", "gps.primary"]]:
        code, out, err, ctx = run_admin(argv + ["--user", "dragon", "--socket", core.config.socket], euid=0)
        assert code == 2
        assert f"run task-core-admin {argv[0]} as your normal user; root has no session bypass" in err
    from task_core import admin as admin_module

    ctx = admin_module.Context(geteuid=lambda: 0, connect=connect_spy)
    assert admin_module.main(["status", "--user", "dragon"], ctx) == 2 and opened == []
    root_core = p2env(peer_uid_fn=lambda _c: 0, peers={0: "administrator"}, clients=[os.geteuid()])
    client = V2Client(root_core.config.socket)
    assert client.call("device.list")["error"]["code"] == "forbidden"
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == {
        "code": "forbidden", "message": "session.login not allowed for this client"}
    client.close()
    # table-driven: whatever [peers] says, v2 without a session is public
    for peers in ({os.geteuid(): "administrator"}, {os.geteuid(): "operator"}, {0: "administrator"}, {}):
        table_core = p2env(peers=peers)
        client = V2Client(table_core.config.socket)
        assert client.call("session.whoami")["result"] == {"role": "public"}
        assert client.call("device.list")["error"]["code"] == "forbidden"
        client.close()
        table_core.close()


# ------------------------------------------------------------------ 83-86: authorized access works

def test_83_operator_inspection(p2env):
    core = p2env()
    tokens, seen = token_spy(core)
    code, out, err, _ = cli(core, ["status"])
    assert code == 0, err
    assert "version: 0.2.1" in out and f"service uid: {os.geteuid()}" in out
    assert "signed in: op \u00b7 operator" in out and "3 connected \u00b7 0 disconnected \u00b7 3 total" in out
    code, out, _err, _ = cli(core, ["devices"])
    for device_id, devnode in ((UBLOX_ID, "/dev/ttyACM0"), (SDR_ID, "/dev/bus/usb/003/002"),
                               (CP2102_ID, "/dev/ttyUSB0")):
        line = next(item for item in out.splitlines() if item.startswith(device_id))
        assert "connected" in line and f"devnode={devnode}" in line
    code, out, _err, _ = cli(core, ["devices", "--detail", "gps.primary"])
    assert f"id: {UBLOX_ID}" in out and "alias: smoke" in out and "serial: \u2014" in out
    assert "Identical units of this model may share this id" in out
    code, out, _err, _ = cli(core, ["assignments"])
    assert f'gps.primary \u2192 {UBLOX_ID} "smoke" Connected' in out
    assert "mesh.primary \u2192 Unassigned" in out and len([l for l in out.splitlines() if "\u2192" in l]) == 4
    code, out, _err, _ = cli(core, ["events"])
    assert re.search(r"^seq=\d+ \S+Z \S+ ", out, re.M) and "task-core log: journalctl -u task-core -b" in out
    last = core.bus.last_seq()
    core.bus.publish("capability.changed", "caps", {"name": "x", "kind": "y", "status": "z"})
    code, out, _err, _ = cli(core, ["events", "--since", str(last)])
    assert out.count("seq=") == 1 and f"seq={last + 1}" in out
    # --json equals the server results
    code, out, _err, _ = cli(core, ["devices", "--json"])
    client = V2Client(core.config.socket)
    token = login(core, "op")
    assert json.loads(out) == {"device.list": client.call("device.list", session=token)["result"]}
    code, out, _err, _ = cli(core, ["status", "--json"])
    status = json.loads(out)
    assert status["core.health"]["version"] == "0.2.1" and status["session.whoami"]["username"] == "op"
    assert status["device.counts"] == client.call("device.counts")["result"]
    client.close()
    # report: one login, one logout
    seen.clear()
    code, out, _err, _ = cli(core, ["report"])
    assert code == 0 and "== devices ==" in out and "== assignments ==" in out and "== events ==" in out
    methods = [m for m, _s, _p in seen]
    assert methods.count("session.login") == 1 and methods.count("session.logout") == 1


def test_84_administrator_mutation_with_confirmation(p2env):
    core = p2env()
    path = core.config.state_dir / "devices.json"
    seen = request_spy(core)
    code, out, err, _ = cli(core, ["assign", "sdr.primary", SDR_ID, "--alias", "sdr"], user="dragon",
                            tty=FakeTTY(["no"]))
    assert code == 5 and f"sdr.primary \u2192 Blog V4 ({SDR_ID})" in out
    assert "device.assign" not in [m for m, _s, _p in seen]
    tty = FakeTTY(["yes"])
    code, out, err, _ = cli(core, ["assign", "sdr.primary", SDR_ID, "--alias", "sdr"], user="dragon", tty=tty)
    assert code == 0, err
    assert "Type yes to continue" in tty.written and f'assigned: sdr.primary \u2192 {SDR_ID} alias "sdr"' in out
    code, out, err, _ = cli(core, ["unassign", "sdr.primary"], user="dragon", tty=FakeTTY(["nope"]))
    assert code == 5
    code, out, err, _ = cli(core, ["unassign", "sdr.primary"], user="dragon", tty=FakeTTY(["yes"]))
    assert code == 0 and "unassigned: sdr.primary" in out
    assert path.read_bytes() == fixture_devices_json()
    code, out, err, _ = cli(core, ["assign", "sdr.primary", SDR_ID, "--yes"], user="dragon")
    assert code == 0
    code, out, err, _ = cli(core, ["unassign", "sdr.primary", "--yes"], user="dragon")
    assert code == 0
    # --password-stdin and no TTY
    stdin = (DRAGON_PW + "\n").encode()
    argv = ["assign", "sdr.primary", SDR_ID, "--password-stdin"]
    code, out, err, _ = cli(core, argv, user="dragon", passwords=[], stdin=stdin)
    assert code == 1 and "no terminal" in err
    code, out, err, _ = cli(core, argv + ["--yes"], user="dragon", passwords=[], stdin=stdin)
    assert code == 0, err
    code, out, err, _ = cli(core, ["unassign", "sdr.primary", "--password-stdin", "--yes"], user="dragon",
                            passwords=[], stdin=stdin)
    assert code == 0
    assert path.read_bytes() == fixture_devices_json()
    code, out, err, _ = cli(core, ["unassign", "radio.primary", "--yes"], user="dragon")
    assert code == 1 and "radio.primary is not assigned; nothing to do" in err


def test_85_k1_and_warnings(p2env):
    core = p2env()
    path = core.config.state_dir / "devices.json"
    seen = request_spy(core)
    argv = ["assign", "gps.primary", CP2102_ID]
    tty = FakeTTY(["yes"])
    code, out, err, _ = cli(core, argv, user="dragon", tty=tty)
    assert code == 5 and "Type replace to continue" in tty.written
    assert f"gps.primary will be removed from u-blox 7 - GPS/GNSS Receiver ({UBLOX_ID})" in out
    code, out, err, _ = cli(core, argv + ["--yes", "--accept-warnings"], user="dragon")
    assert code == 3 and f"task-core refused: gps.primary is held by {UBLOX_ID}" in err
    assert path.read_bytes() == fixture_devices_json()
    assigns = [p for m, _s, p in seen if m == "device.assign"]
    assert assigns and all("confirm_displace" not in p for p in assigns)
    # --yes --replace without --accept-warnings: the class-mismatch warning blocks it locally
    seen.clear()
    code, out, err, _ = cli(core, argv + ["--yes", "--replace"], user="dragon")
    assert code == 3 and "add --accept-warnings" in err and "device.assign" not in [m for m, _s, _p in seen]
    # interactive: the warning is shown and typing replace confirms the displacement
    tty = FakeTTY(["replace"])
    code, out, err, _ = cli(core, argv, user="dragon", tty=tty)
    assert code == 0, err
    assert "not classified for gps.position" in out and f"gps.primary removed from {UBLOX_ID}" in out
    assert [p for m, _s, p in seen if m == "device.assign"][-1]["confirm_displace"] is True
    # restore with flags: --replace sends confirm_displace
    assert cli(core, ["assign", "gps.primary", UBLOX_ID, "--alias", "smoke", "--yes", "--replace"],
               user="dragon")[0] == 0
    assert [p for m, _s, p in seen if m == "device.assign"][-1]["confirm_displace"] is True
    assert path.read_bytes() == fixture_devices_json()
    code, out, err, _ = cli(core, argv + ["--yes", "--replace", "--accept-warnings"], user="dragon")
    assert code == 0 and f"gps.primary removed from {UBLOX_ID}" in out
    assert cli(core, ["assign", "gps.primary", UBLOX_ID, "--alias", "smoke", "--yes", "--replace"],
               user="dragon")[0] == 0
    assert path.read_bytes() == fixture_devices_json()
    # class mismatch (CP2102 is not classified for mesh.messaging) and an unstable identity
    seen.clear()
    code, out, err, _ = cli(core, ["assign", "mesh.primary", CP2102_ID, "--yes"], user="dragon")
    assert code == 3 and "not classified for mesh.messaging" in out and "--accept-warnings" in err
    assert "device.assign" not in [m for m, _s, _p in seen]
    core._fake.add(RawDevice(devnode="/dev/ttyUSB1", vid="1a86", pid="7523", subsystem="usb-serial",
                             bus_path="platform-xhci-hcd.0-usb-0:2"))
    unstable = next(d for d in core.devices.list_public()["devices"] if not d["identity_stable"])["id"]
    code, out, err, _ = cli(core, ["assign", "radio.primary", unstable, "--yes"], user="dragon")
    assert code == 3 and "no usable serial number" in out
    code, out, err, _ = cli(core, ["assign", "radio.primary", unstable, "--yes", "--accept-warnings"], user="dragon")
    assert code == 0
    assert cli(core, ["unassign", "radio.primary", "--yes"], user="dragon")[0] == 0


def test_86_logout_on_every_in_process_exit_path(p2env, monkeypatch):
    core = p2env()
    tokens, seen = token_spy(core)

    def check_one_logout():
        assert [m for m, _s, _p in seen].count("session.logout") == 1
        assert_dead(core, tokens[-1])
        seen.clear()

    assert cli(core, ["status"])[0] == 0                                   # success
    check_one_logout()
    monkeypatch.setattr(admin_client, "CLIENT_ROLE_CHECK", False)
    assert cli(core, ["unassign", "gps.primary", "--yes"], user="op")[0] == 3  # task-core error (forbidden)
    check_one_logout()
    monkeypatch.setattr(admin_client, "CLIENT_ROLE_CHECK", True)
    original = admin_client.SessionRunner._devices

    def boom(self):
        original(self)
        raise RuntimeError("injected between requests")

    monkeypatch.setattr(admin_client.SessionRunner, "_devices", boom)
    code, _out, err, _ = cli(core, ["report"])                            # Python exception
    assert code == 1 and "internal error (RuntimeError)" in err and "Traceback" not in err
    check_one_logout()


def _block_method(core, method, delay=3.0):
    arrived = threading.Event()
    original = core.handle_v2

    def slow(payload, uid):
        if payload.get("method") == method:
            arrived.set()
            time.sleep(delay)
        return original(payload, uid)

    core.handle_v2 = slow
    return arrived


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_86_signal_between_requests_logs_out_once(p2env, signum):
    core = p2env()
    tokens, seen = token_spy(core)
    arrived = _block_method(core, "device.list")
    sent = []

    def on_output(pid, _output):
        if arrived.is_set() and not sent:
            sent.append(signum)
            os.kill(pid, signum)

    code, output, _pid = pty_cli(["report", "--user", "op", "--socket", core.config.socket],
                                 steps=[(r"Password for op: ", (OP_PW + "\n").encode())], on_output=on_output)
    assert sent == [signum]
    assert code == 5 and f"cancelled ({signal.Signals(signum).name})".encode() in output
    time.sleep(0.2)
    assert [m for m, _s, _p in seen].count("session.logout") == 1
    assert_dead(core, tokens[-1])


def test_86_sigint_at_confirmation_prompt(p2env):
    core = p2env()
    tokens, seen = token_spy(core)
    code, output, _pid = pty_cli(
        ["assign", "sdr.primary", SDR_ID, "--user", "dragon", "--socket", core.config.socket],
        steps=[(r"Password for dragon: ", (DRAGON_PW + "\n").encode()),
               (r"Type yes to continue: ", lambda pid: os.kill(pid, signal.SIGINT))])
    assert code == 5 and b"cancelled (SIGINT)" in output
    methods = [m for m, _s, _p in seen]
    assert "device.assign" not in methods and methods.count("session.logout") == 1
    assert_dead(core, tokens[-1])


def test_86_sigkill_is_the_documented_exception(p2env):
    core = p2env()
    tokens, seen = token_spy(core)
    code, _output, _pid = pty_cli(
        ["assign", "sdr.primary", SDR_ID, "--user", "dragon", "--socket", core.config.socket],
        steps=[(r"Password for dragon: ", (DRAGON_PW + "\n").encode()),
               (r"Type yes to continue: ", lambda pid: os.kill(pid, signal.SIGKILL))])
    assert code == -signal.SIGKILL
    assert "session.logout" not in [m for m, _s, _p in seen]
    client = V2Client(core.config.socket)
    assert client.call("session.whoami", session=tokens[-1])["ok"] is True  # still alive (same uid only)
    core._clock.advance(7201)
    assert client.call("session.whoami", session=tokens[-1])["error"]["code"] == "unauthenticated"
    client.close()


# ------------------------------------------------------------------ 87-89

def test_87_core_down_no_prompt_no_fallback(p2env, monkeypatch, tmp_path):
    missing = str(tmp_path / "nope.sock")
    code, out, err, ctx = run_admin(["status", "--user", "op", "--socket", missing], passwords=[OP_PW])
    assert code == 4 and ctx.prompts == []
    assert err.strip() == (f"task-core is not reachable at {missing} (No such file or directory). "
                           "Check: systemctl status task-core; journalctl -u task-core -b")
    refused_path = str(tmp_path / "refused.sock")
    bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound.bind(refused_path)  # bound, never listening: ECONNREFUSED
    code, out, err, ctx = run_admin(["report", "--user", "op", "--socket", refused_path], passwords=[OP_PW])
    assert code == 4 and ctx.prompts == [] and "(Connection refused)" in err
    bound.close()
    core = p2env()
    os.chmod(core.config.socket, 0)
    code, out, err, ctx = run_admin(["devices", "--user", "op", "--socket", core.config.socket], passwords=[OP_PW])
    os.chmod(core.config.socket, 0o660)
    if os.geteuid() != 0:
        assert code == 4 and ctx.prompts == []
        assert err.strip() == (f"No access to {core.config.socket} \u2014 your account must be in group rain-core "
                               "(log out and in after adding it).")
    # a real pty receives no password prompt when the core is down
    code, output, _pid = pty_cli(["status", "--user", "op", "--socket", missing])
    assert code == 4 and b"Password" not in output and b"is not reachable" in output
    # a 0.1.1 core (replaying the recorded 0.1.1 answers) is too old
    old = _fake_011_core(tmp_path / "old.sock")
    code, out, err, ctx = run_admin(["status", "--user", "op", "--socket", str(tmp_path / "old.sock")],
                                    passwords=[OP_PW])
    assert code == 4 and ctx.prompts == []
    assert err.strip() == "task-core 0.1.1 has no v2 sessions; 0.2.0 or later is required"
    old.close()
    # open()/os.stat spy: no state, device, sysfs or udev access when the core is down
    touched = []
    real_open, real_stat = builtins.open, os.stat
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: touched.append(str(f)) or real_open(f, *a, **k))
    monkeypatch.setattr(os, "stat", lambda f, *a, **k: touched.append(str(f)) or real_stat(f, *a, **k))
    for argv in (["status"], ["report"], ["assign", "sdr.primary", SDR_ID, "--yes"]):
        assert run_admin(argv + ["--user", "op", "--socket", missing], passwords=[OP_PW])[0] == 4
    monkeypatch.undo()
    for path in touched:
        assert not path.startswith(("/var/lib/task", "/dev", "/sys", "/run/udev")), path


def _fake_011_core(path):
    """Answers exactly as task-core 0.1.1 does (taken from the recorded golden transcript)."""
    golden = json.loads((ROOT / "tests" / "golden" / "v1_transcript_0.1.1.json").read_text())["transcript"]
    unsupported = next(e["reply"] for e in golden if e.get("send", "").startswith('{"v":3'))
    health = next(e["reply"] for e in golden if e.get("send") == "core.health sync")
    health = json.loads(json.dumps(health).replace('"<uptime>"', "5"))
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(4)

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            buf = b""
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        request = json.loads(line)
                        if request.get("v") == 1 and request.get("method") == "core.health":
                            reply = dict(health, id=request["id"])
                        else:
                            reply = dict(unsupported, id=request.get("id"))
                        conn.sendall(json.dumps(reply).encode() + b"\n")
            except OSError:
                pass
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return server


SESSION_SOURCE_FILES = [ROOT / "task_core" / "admin_client.py", ROOT / "task_core" / "admin.py"]


def test_88_no_hardware_access(p2env, monkeypatch):
    client_source = (ROOT / "task_core" / "admin_client.py").read_text()
    admin_source = (ROOT / "task_core" / "admin.py").read_text()
    for source in (client_source, admin_source):
        assert not re.search(r"^\s*(import|from)\s+(pyudev|serial)\b", source, re.M)
        assert "PySide6" not in source and "pyudev" not in source
    for literal in re.findall(r"[\"'](/[^\"']*)[\"']", client_source):
        assert not literal.startswith(("/dev", "/sys", "/run/udev", "/var/lib/task")), literal
    allowed = {"/var/lib/task": "account commands: accounts.json location (allow-listed)",
               "/dev/tty": "the controlling terminal for prompts, not a device"}
    for literal in re.findall(r"[\"'](/[^\"']*)[\"']", admin_source):
        if literal.startswith(("/dev", "/sys", "/run/udev", "/var/lib/task")):
            assert literal in allowed, literal
    core = p2env()
    touched = []
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: touched.append(str(f)) or real_open(f, *a, **k))
    assert cli(core, ["report"])[0] == 0
    assert cli(core, ["assign", "sdr.primary", SDR_ID], user="dragon", tty=FakeTTY(["yes"]))[0] == 0
    assert cli(core, ["unassign", "sdr.primary"], user="dragon", tty=FakeTTY(["yes"]))[0] == 0
    monkeypatch.undo()
    assert touched == []  # only the socket (not an open()) and the injected tty were used


def test_89_password_never_in_argv_env_logs_or_files(p2env, monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    core = p2env()
    tokens, seen = token_spy(core)
    for option in ("--password", "-p"):
        code, _out, err, _ = run_admin(["status", "--user", "op", option, OP_PW, "--socket", core.config.socket])
        assert code == 1 and "unrecognized arguments" in err
    monkeypatch.setenv("RAIN_PASSWORD", OP_PW)
    monkeypatch.setenv("PASSWORD", OP_PW)
    code, _out, _err, ctx = cli(core, ["status"])
    assert code == 0 and ctx.prompts == ["Password for op: "]
    monkeypatch.delenv("RAIN_PASSWORD")
    monkeypatch.delenv("PASSWORD")
    # --password-stdin keeps spaces and Unicode, strips one \n or \r\n, refuses > 4096 bytes
    special = "  p\u00e4ss w\u00f6rd \U0001F511  "
    for suffix in (b"\n", b"\r\n", b""):
        seen.clear()
        run_admin(["status", "--user", "op", "--password-stdin", "--socket", core.config.socket],
                  stdin=special.encode() + suffix)
        assert [p for m, _s, p in seen if m == "session.login"][0]["secret"] == special
    seen.clear()
    run_admin(["status", "--user", "op", "--password-stdin", "--socket", core.config.socket], stdin=b"pw-pw-pw\n\n")
    assert [p for m, _s, p in seen if m == "session.login"][0]["secret"] == "pw-pw-pw\n"
    code, _out, err, _ = run_admin(["status", "--user", "op", "--password-stdin", "--socket", core.config.socket],
                                   stdin=b"x" * 4097)
    assert code == 1 and "over 4096 bytes" in err
    # argv (/proc/<pid>/cmdline), stdout/stderr, task-core log, HOME, cwd and state dir hold no secret
    home = tempfile.mkdtemp(prefix="rnhome")
    cmdlines = []

    def read_cmdline(pid):
        cmdlines.append(Path(f"/proc/{pid}/cmdline").read_bytes())
        return None

    code, output, _pid = pty_cli(["status", "--user", "op", "--socket", core.config.socket],
                                 steps=[(r"Password for op: ", lambda pid: read_cmdline(pid)),
                                        (r"Password for op: ", (OP_PW + "\n").encode())], env={"HOME": home})
    assert code == 0 and cmdlines
    token = tokens[-1]
    blobs = [cmdlines[0], output, caplog.text.encode()]
    for directory in (Path(home), core.config.state_dir):
        for item in directory.rglob("*"):
            if item.is_file() and item.name != "accounts.json":
                blobs.append(item.read_bytes())
    for blob in blobs:
        assert OP_PW.encode() not in blob and token.encode() not in blob


def test_91_no_display_needed(p2env, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setitem(sys.modules, "PySide6", None)  # import PySide6 now raises ImportError
    with pytest.raises(ImportError):
        __import__("PySide6")
    core = p2env()
    assert cli(core, ["report"])[0] == 0
    assert cli(core, ["assign", "sdr.primary", SDR_ID, "--yes"], user="dragon")[0] == 0
    assert cli(core, ["unassign", "sdr.primary", "--yes"], user="dragon")[0] == 0
    assert (core.config.state_dir / "devices.json").read_bytes() == fixture_devices_json()


def test_92_no_token_caching(p2env):
    core = p2env()
    tokens, seen = token_spy(core)
    outputs = []
    for _ in range(2):
        code, out, err, _ = cli(core, ["status", "--json"])
        assert code == 0
        outputs.append(out + err)
    methods = [m for m, _s, _p in seen]
    assert methods.count("session.login") == 2 and methods.count("session.logout") == 2
    assert len(set(tokens)) == 2

    def has_session_key(value):
        if isinstance(value, dict):
            return "session" in value or any(has_session_key(v) for v in value.values())
        if isinstance(value, list):
            return any(has_session_key(v) for v in value)
        return False

    for out in outputs:
        assert not has_session_key(json.loads(out))
        for token in tokens:
            assert token not in out
    for token in tokens:
        assert token not in json.dumps(dict(os.environ))
        assert_dead(core, token)
