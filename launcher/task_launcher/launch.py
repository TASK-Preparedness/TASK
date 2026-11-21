# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Starting apps: argv lists only, never a shell (``subprocess.Popen(argv, shell=False)``).

Each tracked app runs in its own session (``start_new_session=True``) so closing the launcher
does not close it. Exit status is collected by polling ``Popen.poll()`` from a Qt timer on the GUI
thread, so no watcher threads exist. Output goes to a per-app log in
``~/.local/state/task-launcher/logs/`` (rotated at 1 MiB). Only processes started by this launcher
instance are known as Running.

Phase 4A: a process that ends with a non-zero status within ``EARLY_EXIT_S`` of its start is an
*early failure*; its outcome carries the time to exit and the tail of the output it wrote since
this start (``Outcome.extra["early"]``, ``["tail"]``), so a tile can say why the app did not open.
"""

import logging
import os
import signal
import subprocess
from dataclasses import dataclass, field

from task_launcher import paths

logger = logging.getLogger("task_launcher")
LOG_MAX = 1 << 20
POLL_MS = 500
EARLY_EXIT_S = 8.0
TAIL_LINES = 6


@dataclass
class Proc:
    key: str
    argv: list
    popen: object
    started: float = 0.0
    helper: bool = False
    log_path: str = ""
    log_offset: int = 0


@dataclass
class Outcome:
    key: str
    status: str            # running | exited | error
    message: str = ""
    code: int = None
    log_path: str = ""
    extra: dict = field(default_factory=dict)


def describe_exit(code: int) -> str:
    if code is None:
        return "running"
    if code == 0:
        return "exited normally"
    if code < 0:
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = f"signal {-code}"
        return f"crashed / killed by {name}"
    return f"exited with code {code}"


def _log_file(key: str):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)[:120]
    d = paths.state_dir() / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        p = d / f"{safe}.log"
        if p.exists() and p.stat().st_size > LOG_MAX:
            os.replace(p, p.with_suffix(".log.1"))
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return fd, str(p)
    except OSError:
        return subprocess.DEVNULL, ""


class ProcessManager:
    """Pure-Python core (testable without Qt). ``poll()`` is driven by a QTimer in the UI."""

    def __init__(self, popen=subprocess.Popen, clock=None):
        import time

        self._popen = popen
        self.clock = clock or time.monotonic
        self.procs = {}          # key -> Proc (main instance)
        self.helpers = []        # relaunch helpers (not tracked as Running)
        self.listeners = []      # callables(Outcome)

    def running(self, key) -> bool:
        p = self.procs.get(key)
        return p is not None and p.popen.poll() is None

    def start(self, key: str, argv: list, cwd: str = None, single_instance: bool = True, helper: bool = False,
              env_extra: dict = None) -> Outcome:
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            return self._emit(Outcome(key, "error", "invalid argv"))
        if not argv[0].startswith("/"):
            return self._emit(Outcome(key, "error", f"refused: program is not an absolute path: {argv[0]}"))
        if single_instance and not helper and self.running(key):
            return Outcome(key, "already-running", "already running — use the desktop's window switcher")
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        fd, log_path = _log_file(key)
        offset = 0
        if log_path:
            try:
                offset = os.path.getsize(log_path)
            except OSError:
                offset = 0
        try:
            popen = self._popen(list(argv), shell=False, cwd=cwd or os.path.expanduser("~"), env=env,
                                stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, close_fds=True,
                                start_new_session=True)
        except OSError as exc:
            return self._emit(Outcome(key, "error", f"could not start: {exc.strerror or exc}", log_path=log_path))
        finally:
            if isinstance(fd, int) and fd >= 0 and fd != subprocess.DEVNULL:
                os.close(fd)
        proc = Proc(key, list(argv), popen, self.clock(), helper, log_path, offset)
        if helper:
            self.helpers.append(proc)
        else:
            self.procs[key] = proc
        logger.info("started %s (pid %s)", key, getattr(popen, "pid", "?"))
        return self._emit(Outcome(key, "running", "", log_path=log_path))

    def poll(self):
        """Collect finished processes; returns the outcomes emitted."""
        out = []
        for key, proc in list(self.procs.items()):
            code = proc.popen.poll()
            if code is None:
                continue
            del self.procs[key]
            status = "exited" if code == 0 else "error"
            logger.info("%s %s", key, describe_exit(code))
            message, extra = describe_exit(code), {}
            elapsed = self.clock() - proc.started
            if code != 0 and elapsed < EARLY_EXIT_S:
                extra["early"] = round(elapsed, 1)
                extra["tail"] = tail_since(proc.log_path, proc.log_offset, TAIL_LINES)
                message = f"{message} {elapsed:.1f} s after start"
                last = next((ln for ln in reversed(extra["tail"].splitlines()) if ln.strip()), "")
                if last:
                    message += f": {last.strip()[:160]}"
            out.append(self._emit(Outcome(key, status, message, code, proc.log_path, extra)))
        for proc in list(self.helpers):
            code = proc.popen.poll()
            if code is not None:
                self.helpers.remove(proc)
                if code != 0:
                    out.append(self._emit(Outcome(proc.key, "error", "re-activation " + describe_exit(code),
                                                  code, proc.log_path)))
        return out

    def _emit(self, outcome):
        for cb in list(self.listeners):
            try:
                cb(outcome)
            except Exception:
                logger.exception("listener failed")
        return outcome

    def shutdown(self):
        """Launcher exit: apps keep running (own session). Reap only what already finished."""
        for proc in list(self.procs.values()) + list(self.helpers):
            proc.popen.poll()
        self.listeners.clear()


def tail_since(path: str, offset: int, max_lines: int = TAIL_LINES, max_bytes: int = 16384) -> str:
    """Last lines written to ``path`` after byte ``offset`` (the output of the current run)."""
    if not path:
        return ""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = offset if 0 <= offset <= size else 0
            fh.seek(max(start, size - max_bytes))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-max_lines:])


def tail(path: str, max_lines: int = 40, max_bytes: int = 16384) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-max_lines:])
