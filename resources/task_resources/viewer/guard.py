# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""WebEngine crash guard (task-resources 0.2.4).

A persistent marker is written before the WebEngine reader's first page load in a process and cleared after the
first successful load (or on a clean shutdown before any load finished). If a host process dies while the marker
is armed (segfault, abort), the next start finds a stale marker whose owner process is gone: that configuration
is recorded as *known to crash* and the automatic viewer choice uses the lightweight reader instead, with a
notice and a manual "Try enhanced reader" action. A known-crashing configuration is never retried automatically.

The configuration fingerprint (host + versions of task-resources, Qt and PySide6 + Qt platform) is part of the
record: after an upgrade the new configuration is not "known to crash" and gets one guarded attempt.

Nothing global is changed: no environment variables, no Qt attributes, no sandbox flags. The marker is a small
private JSON file (0600) in the host's own state directory. Any I/O error makes the guard inert (fail-open for
choosing, never raises into Qt).
"""

import json
import os
import time
from pathlib import Path

ARMED, CRASHED = "armed", "crashed"


def fingerprint(host):
    try:
        from PySide6 import __version__ as pyside
        from PySide6.QtCore import qVersion
        qt = qVersion()
    except Exception:  # noqa: BLE001
        pyside = qt = "?"
    from task_resources import __version__ as res
    plat = os.environ.get("QT_QPA_PLATFORM") or os.environ.get("XDG_SESSION_TYPE") or "default"
    return f"{host}|task-resources {res}|Qt {qt}|PySide6 {pyside}|{plat}"


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, TypeError, OverflowError):
        return pid not in (None, "")
    return True


class CrashGuard:
    def __init__(self, path, host="task-resources", fp=None, pid=None):
        self.path = Path(path)
        self.fp = fp or fingerprint(host)
        self.pid = os.getpid() if pid is None else pid
        self.armed = False
        self.error = ""
        self.record = self._read()
        if self.record.get("state") == ARMED and self.record.get("pid") != self.pid \
                and not _alive(self.record.get("pid")):
            self.record = dict(self.record, state=CRASHED, detected=time.time())
            self._write(self.record)

    # ------------------------------------------------------------------ queries
    def known_crash(self):
        """True if WebEngine is known to have crashed a host with THIS configuration."""
        return self.record.get("state") == CRASHED and self.record.get("fingerprint") == self.fp

    def describe(self):
        r = self.record
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("started", 0))) if r.get("started") else "?"
        return f"the enhanced (WebEngine) reader stopped the application on {when} while opening {r.get('url') or 'a page'}"

    # ------------------------------------------------------------------ transitions
    def arm(self, url=""):
        """Before a WebEngine load while no load has succeeded yet in this process."""
        if self.armed:
            return
        self.armed = True
        prev = self.record if self.record.get("state") == CRASHED else {}
        self.record = {"state": ARMED, "pid": self.pid, "fingerprint": self.fp, "started": time.time(),
                       "url": str(url)[:300], "previous_crash": bool(prev)}
        self._write(self.record)

    def disarm(self):
        """After a successful load: this configuration works; the marker (and any crash record) is removed."""
        if not self.armed:
            return
        self.armed = False
        self.record = {}
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            self.error = str(exc)

    def release(self):
        """Clean shutdown: an armed marker is removed (the process did not crash). A crash record stays."""
        if self.armed:
            self.armed = False
            prev = self.record.get("previous_crash")
            self.record = {}
            try:
                if prev:      # trying again after a known crash and closing before success: keep the crash
                    self.record = {"state": CRASHED, "fingerprint": self.fp, "pid": None, "started": time.time()}
                    self._write(self.record)
                else:
                    self.path.unlink(missing_ok=True)
            except OSError as exc:
                self.error = str(exc)

    # ------------------------------------------------------------------ storage
    def _read(self):
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            self.error = str(exc)
