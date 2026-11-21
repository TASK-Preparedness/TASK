# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Ownership locks (flock, released automatically when the process dies).

* Instance lock  $XDG_RUNTIME_DIR/task/mesh-service.lock : at most one task-mesh-service.
* Device locks   $XDG_RUNTIME_DIR/task/mesh-devices/<name>.lock : exactly one owner per radio, whether that is the
  service or the GUI in direct mode. The lock name is the resolved tty (e.g. ttyACM0), so two by-id aliases
  of one device share a lock. The lock file records the owner role ("service"/"gui") and pid for display.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Optional


def runtime_dir(env=None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.path.isdir(base):
        # No user runtime dir (no logind session): a private per-user dir under /tmp, ownership checked.
        base = f"/tmp/task-runtime-{os.getuid()}"
        os.makedirs(base, mode=0o700, exist_ok=True)
        st = os.lstat(base)
        if st.st_uid != os.getuid() or not os.path.isdir(base) or os.path.islink(base):
            raise PermissionError(f"{base} is not a private directory owned by this user")
    d = Path(base) / "task"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    return d


class Busy(Exception):
    def __init__(self, owner: str) -> None:
        super().__init__(f"owned by {owner}")
        self.owner = owner


class FileLock:
    def __init__(self, path: Path, role: str) -> None:
        self.path = Path(path)
        self.role = role
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> "FileLock":
        if self._fd is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise Busy(read_owner(self.path)) from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{self.role} {os.getpid()}\n".encode())
        self._fd = fd
        return self

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.ftruncate(fd, 0)
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def read_owner(path: Path) -> str:
    try:
        text = Path(path).read_text().split()
    except OSError:
        return "another process"
    return f"{text[0]} (pid {text[1]})" if len(text) >= 2 else "another process"


def is_locked(path: Path) -> bool:
    """Non-destructive check (try-lock + immediate unlock)."""
    if not Path(path).exists():
        return False
    fd = os.open(str(path), os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def device_lock_name(path: str) -> str:
    real = os.path.realpath(path)
    name = os.path.basename(real) or "unknown"
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def device_lock(path: str, role: str, env=None) -> FileLock:
    return FileLock(runtime_dir(env) / "mesh-devices" / f"{device_lock_name(path)}.lock", role)


def instance_lock(env=None) -> FileLock:
    return FileLock(runtime_dir(env) / "mesh-service.lock", "service")


def service_running(env=None) -> bool:
    return is_locked(runtime_dir(env) / "mesh-service.lock")
