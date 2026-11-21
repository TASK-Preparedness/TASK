# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Device ownership: who holds a device node; per-device advisory locks between T.A.S.K. modules.

Only same-user processes are visible through /proc/<pid>/fd; others are reported as
"busy (another user/process)" when an open fails with EBUSY/EACCES. Never kills anything.
"""

import errno
import fcntl
import os
import re
from pathlib import Path

from task_comms import paths


def holders(device: str, proc_root: Path = Path("/proc"), self_pid: int = None):
    """[(pid, comm)] of visible processes with device open."""
    self_pid = os.getpid() if self_pid is None else self_pid
    try:
        target = os.path.realpath(device)
    except OSError:
        return []
    found = []
    try:
        procs = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except OSError:
        return []
    for p in procs:
        if int(p.name) == self_pid:
            continue
        try:
            fds = list((p / "fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(fd) == target:
                    try:
                        comm = (p / "comm").read_text().strip()
                    except OSError:
                        comm = "?"
                    found.append((int(p.name), comm))
                    break
            except OSError:
                continue
    return sorted(found)


class DeviceClaim:
    """Advisory flock in $XDG_RUNTIME_DIR/task/locks so two T.A.S.K. modules never share a device."""

    def __init__(self, device_key: str, module: str, directory: Path = None):
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", device_key)[:120]
        self.dir = Path(directory) if directory else paths.runtime_dir() / "task" / "locks"
        self.path = self.dir / f"{safe}.lock"
        self.module = module
        self.fd = None

    def acquire(self) -> bool:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                return False
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{self.module} {os.getpid()}\n".encode())
        self.fd = fd
        return True

    def holder(self):
        try:
            return self.path.read_text().strip() or None
        except OSError:
            return None

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        if not self.acquire():
            raise BlockingIOError(f"device in use by {self.holder() or 'another module'}")
        return self

    def __exit__(self, *a):
        self.release()
