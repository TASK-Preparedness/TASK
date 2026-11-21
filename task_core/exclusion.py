# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Startup mutual exclusion between task-core and a legacy rain-core (Phase 4C).

Three layers (only the last two live here; the first is the unit's Conflicts=):
1. systemd ``Conflicts=rain-core.service`` in task-core.service.
2. An exclusive, non-blocking flock on ``<state_dir>/.lock`` held for the life of
   the process (also taken by task-core-migrate, so migration and Core never overlap).
3. A legacy check: refuse if a rain-core process is running, or a live listener
   answers on the legacy socket that is not our own socket.
No device I/O, no privileged calls; reads /proc only.
"""

import errno
import fcntl
import os
import socket
from pathlib import Path

LEGACY_SOCKET = "/run/rain/core.sock"
LEGACY_MARKERS = ("rain_core", "rain-core")


class ExclusionError(Exception):
    """Another Core (task-core or legacy rain-core) or the migration tool is active."""


class StateLock:
    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / ".lock"
        self._fd = None

    def acquire(self) -> "StateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise ExclusionError(f"state directory is locked by another process ({self.path})") from None
            raise
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def legacy_processes(proc_root: Path = Path("/proc"), self_pid: int = None) -> list:
    """PIDs whose command line names the legacy rain-core (``rain_core``/``rain-core``)."""
    self_pid = os.getpid() if self_pid is None else self_pid
    found = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == self_pid:
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        words = [a.decode("utf-8", "replace") for a in argv if a]
        # "rain-core-admin" / migration helpers are not a running Core.
        if any(os.path.basename(w) in ("rain-core",) or w in ("rain_core", "rain_core.main")
               or w.endswith("/rain-core") for w in words):
            found.append(int(entry.name))
    return sorted(found)


def legacy_socket_live(own_socket: str, legacy_socket: str = LEGACY_SOCKET) -> bool:
    """True if something answers on the legacy socket and it is not our own socket."""
    legacy = Path(legacy_socket)
    try:
        if not legacy.exists():
            return False
        if legacy.is_symlink() and os.path.realpath(legacy) == os.path.realpath(own_socket):
            return False  # the compat symlink to ourselves
    except OSError:
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(str(legacy))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def guard(state_dir: Path, own_socket: str, *, proc_root: Path = Path("/proc"),
          legacy_socket: str = LEGACY_SOCKET) -> StateLock:
    """Take the state lock and refuse if a legacy rain-core is active. Caller keeps the lock."""
    lock = StateLock(state_dir).acquire()
    try:
        pids = legacy_processes(proc_root)
        if pids:
            raise ExclusionError(f"legacy rain-core is running (pid {', '.join(map(str, pids))}); stop it first")
        if legacy_socket_live(own_socket, legacy_socket):
            raise ExclusionError(f"a live Core answers on {legacy_socket}; refusing to start a second Core")
    except BaseException:
        lock.release()
        raise
    return lock
