# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Safe launching: argv only, no shell, own session, logs 0600, apps survive the launcher."""

import os
import signal
import time

from conftest import make_exec
from task_launcher.launch import ProcessManager, describe_exit


def wait_poll(pm, key, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        outs = [o for o in pm.poll() if o.key == key]
        if outs:
            return outs[-1]
        time.sleep(0.02)
    raise AssertionError("process did not finish")


def test_popen_arguments_never_use_a_shell():
    calls = []

    class FakePopen:
        pid = 4242

        def __init__(self, argv, **kw):
            calls.append((argv, kw))

        def poll(self):
            return None

    pm = ProcessManager(popen=FakePopen)
    out = pm.start("k", ["/bin/echo", "a; rm -rf ~", "$(id)"])
    assert out.status == "running"
    argv, kw = calls[0]
    assert argv == ["/bin/echo", "a; rm -rf ~", "$(id)"]
    assert kw["shell"] is False and kw["start_new_session"] is True and kw["close_fds"] is True
    assert pm.start("k", ["/bin/echo"]).status == "already-running"


def test_refuses_relative_and_invalid_argv():
    pm = ProcessManager(popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert pm.start("k", ["echo", "x"]).status == "error"
    assert pm.start("k", "/bin/echo x").status == "error"
    assert pm.start("k", []).status == "error"


def test_exit_codes_and_logs(safe_dir, isolated_home):
    ok = make_exec(safe_dir / "bin", "ok", "echo hello; exit 0")
    bad = make_exec(safe_dir / "bin", "bad", "echo oops >&2; exit 3")
    pm = ProcessManager()
    assert pm.start("app:ok", [str(ok)]).status == "running"
    o = wait_poll(pm, "app:ok")
    assert o.status == "exited" and o.message == "exited normally"
    assert pm.start("app:bad", [str(bad)]).status == "running"
    o = wait_poll(pm, "app:bad")
    assert o.status == "error" and o.message.startswith("exited with code 3")
    assert "after start: oops" in o.message and o.extra["tail"].endswith("oops")   # Phase 4A early-failure
    log = isolated_home / ".local/state/task-launcher/logs/app_bad.log"
    assert log.read_text().strip() == "oops"
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_missing_program_is_an_error():
    pm = ProcessManager()
    o = pm.start("x", ["/nonexistent/program"])
    assert o.status == "error" and "could not start" in o.message


def test_describe_exit_signals():
    assert describe_exit(-signal.SIGSEGV) == "crashed / killed by SIGSEGV"
    assert describe_exit(None) == "running"


def test_launched_app_survives_launcher_shutdown(safe_dir):
    sl = make_exec(safe_dir / "bin", "sleeper", "exec sleep 30")
    pm = ProcessManager()
    pm.start("s", [str(sl)])
    pid = pm.procs["s"].popen.pid
    assert os.getsid(pid) == pid            # own session: not killed with the launcher's session
    pm.shutdown()
    assert pm.procs["s"].popen.poll() is None
    os.kill(pid, signal.SIGTERM)
    pm.procs["s"].popen.wait(5)
