# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Per-module session gate (r2 §9): the module signs in itself; private views lock when it ends.

Limitations (documented, not hidden): one sign-in per module (no SSO); history files are
protected only by Unix permissions (0600) — same-uid processes can read them. Scoped,
delegated tokens and key release would need a future, separately approved Core feature.
"""

import threading
import time


class SessionGate:
    def __init__(self, client, clock=time.monotonic, idle_lock_s=None):
        self.client = client
        self.clock = clock
        self.idle_lock_s = idle_lock_s
        self._last = None
        self._lock = threading.Lock()
        self.listeners = []

    @property
    def unlocked(self):
        with self._lock:
            if self.client.token is None:
                return False
            if self.idle_lock_s is not None and self._last is not None and self.clock() - self._last > self.idle_lock_s:
                self._end_locked("idle")
                return False
            return True

    def sign_in(self, username, secret):
        info = self.client.login(username, secret)
        self._last = self.clock()
        return info

    def touch(self):
        self._last = self.clock()

    def require(self, role="operator"):
        if not self.unlocked:
            return False, "sign in required"
        if not self.client.has_role(role):
            return False, f"{role} role required"
        self.touch()
        return True, ""

    def session_ended(self, reason="session-ended"):
        with self._lock:
            self._end_locked(reason)

    def _end_locked(self, reason):
        self.client.token = None
        self.client.username = self.client.role = None
        for cb in list(self.listeners):
            cb(reason)

    def sign_out(self):
        self.client.logout()
        for cb in list(self.listeners):
            cb("logout")
