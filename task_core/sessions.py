# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Human sessions for protocol v2 (PHASE-2.md sections 6.2 and 6.3).

Tokens live in memory only, as SHA-256. Nothing here is written to disk.
"""

import hashlib
import logging
import math
import os
import secrets
import threading
import time
from pathlib import Path

from task_core import passwords
from task_core.accounts import AccountStore, valid_username
from task_core.errors import ApiError

logger = logging.getLogger("task_core")

DEFAULT_IDLE = 7200
DEFAULT_ABSOLUTE = 43200
TIMEOUT_MIN = 60
TIMEOUT_MAX = 86400
DEFAULT_SESSIONS_FILE = Path("/etc/task/sessions.toml")

RATE_THRESHOLD = 5
RATE_FIRST_WAIT = 30
RATE_MAX_WAIT = 900

INVALID_CREDENTIALS = "invalid credentials"
SESSION_INVALID = "session invalid"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionsConfig:
    """/etc/task/sessions.toml, re-read when the file changes. Missing or invalid = fail closed."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._key = None
        self.clients: dict = {}
        self.idle = DEFAULT_IDLE
        self.absolute = DEFAULT_ABSOLUTE
        self.reload_if_changed()

    def _stat_key(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return ("missing",)
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def reload_if_changed(self) -> None:
        key = self._stat_key()
        if key == self._key:
            return
        self._key = key
        self.clients, self.idle, self.absolute = {}, DEFAULT_IDLE, DEFAULT_ABSOLUTE
        if key == ("missing",):
            return
        from task_core.config import read_toml

        try:
            document = read_toml(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.error("sessions file rejected; logins disabled")
            return
        clients = document.get("clients", {})
        if not isinstance(clients, dict):
            logger.error("sessions file rejected; logins disabled")
            return
        parsed = {}
        for uid, label in clients.items():
            try:
                number = int(uid)
            except (TypeError, ValueError):
                logger.error("sessions file rejected; logins disabled")
                return
            if number < 0 or not isinstance(label, str):
                logger.error("sessions file rejected; logins disabled")
                return
            parsed[number] = label
        timeouts = document.get("timeouts", {})
        if not isinstance(timeouts, dict):
            timeouts = {}
            logger.warning("sessions timeouts rejected; using defaults")
        idle = self._timeout(timeouts, "idle_seconds", DEFAULT_IDLE)
        absolute = self._timeout(timeouts, "absolute_seconds", DEFAULT_ABSOLUTE)
        self.clients, self.idle, self.absolute = parsed, idle, absolute

    @staticmethod
    def _timeout(table, key, default):
        if key not in table:
            return default
        value = table[key]
        if isinstance(value, bool) or not isinstance(value, int) or not (TIMEOUT_MIN <= value <= TIMEOUT_MAX):
            logger.warning("sessions %s out of range; using default %d", key, default)
            return default
        return value

    def allows(self, uid: int) -> bool:
        return uid in self.clients


class RateLimiter:
    """Consecutive-failure lockout per key: 5 failures -> 30 s, doubling to 900 s."""

    def __init__(self, clock) -> None:
        self.clock = clock
        self._state: dict = {}

    def remaining(self, key) -> float:
        entry = self._state.get(key)
        if entry is None:
            return 0.0
        return max(0.0, entry["until"] - self.clock())

    def failure(self, key) -> None:
        entry = self._state.setdefault(key, {"count": 0, "wait": 0, "until": 0.0})
        entry["count"] += 1
        if entry["count"] >= RATE_THRESHOLD:
            entry["wait"] = RATE_FIRST_WAIT if entry["wait"] == 0 else min(entry["wait"] * 2, RATE_MAX_WAIT)
            entry["until"] = self.clock() + entry["wait"]

    def reset(self, key) -> None:
        self._state.pop(key, None)


class Session:
    __slots__ = ("token_hash", "uid", "username", "role", "created", "last_used", "account_hash", "on_end")

    def __init__(self, token_hash, uid, username, role, now, account_hash):
        self.token_hash = token_hash
        self.uid = uid
        self.username = username
        self.role = role
        self.created = now
        self.last_used = now
        self.account_hash = account_hash
        self.on_end = []


class SessionManager:
    def __init__(self, accounts_path: Path, sessions_path: Path, clock=None) -> None:
        self.clock = clock or time.monotonic
        self.accounts = AccountStore(accounts_path)
        self.config = SessionsConfig(sessions_path)
        self.limiter = RateLimiter(self.clock)
        self._lock = threading.RLock()
        self._login_lock = threading.Lock()
        self._sessions: dict = {}

    # -- login / logout -------------------------------------------------
    def login(self, uid: int, username, secret) -> dict:
        if not isinstance(username, str) or not isinstance(secret, str):
            raise ApiError("bad-request", "invalid params")
        self.config.reload_if_changed()
        if not self.config.allows(uid):
            raise ApiError("forbidden", "session.login not allowed for this client")
        with self._login_lock:
            user_key, uid_key = ("user", username), ("uid", uid)
            wait = max(self.limiter.remaining(user_key), self.limiter.remaining(uid_key))
            if wait > 0:
                logger.warning("login rate-limited")
                raise ApiError("rate-limited", f"too many attempts, retry in {int(math.ceil(wait))} s")
            self.accounts.reload_if_changed()
            account = self.accounts.get(username) if valid_username(username) else None
            if account is None or account["disabled"]:
                ok = passwords.dummy_verify()
            else:
                ok = passwords.verify(secret, account["hash"])
            if not ok:
                self.limiter.failure(user_key)
                self.limiter.failure(uid_key)
                logger.warning("login failed")
                raise ApiError("unauthenticated", INVALID_CREDENTIALS)
            self.limiter.reset(user_key)
            self.limiter.reset(uid_key)
        token = secrets.token_urlsafe(32)
        now = self.clock()
        session = Session(_token_hash(token), uid, username, account["role"], now, account["hash"])
        with self._lock:
            self._sessions[session.token_hash] = session
        logger.info("login ok user=%s role=%s", username, account["role"])
        return {
            "session": token,
            "username": username,
            "role": account["role"],
            "idle_timeout_s": self.config.idle,
            "expires_in_s": self.config.absolute,
        }

    def logout(self, session: Session) -> dict:
        self._end(session, "logout")
        logger.info("logout user=%s", session.username)
        return {}

    # -- validation -----------------------------------------------------
    def resolve(self, token, uid: int, touch: bool = True) -> Session:
        """Return the live session for token+uid or raise unauthenticated."""
        if not isinstance(token, str) or not token:
            raise ApiError("unauthenticated", SESSION_INVALID)
        with self._lock:
            session = self._sessions.get(_token_hash(token))
            if session is None:
                raise ApiError("unauthenticated", SESSION_INVALID)
            if session.uid != uid:
                raise ApiError("unauthenticated", SESSION_INVALID)
            if not self._still_valid(session):
                raise ApiError("unauthenticated", SESSION_INVALID)
            if touch:
                session.last_used = self.clock()
            return session

    def check(self, session: Session) -> bool:
        """Stream-side check; never refreshes the idle timer."""
        with self._lock:
            if self._sessions.get(session.token_hash) is not session:
                return False
            return self._still_valid(session)

    def _still_valid(self, session: Session) -> bool:
        now = self.clock()
        self.config.reload_if_changed()
        if now - session.last_used > self.config.idle or now - session.created > self.config.absolute:
            self._end(session, "expired")
            logger.info("session expired user=%s", session.username)
            return False
        self.accounts.reload_if_changed()
        account = self.accounts.get(session.username)
        if (
            account is None
            or account["disabled"]
            or account["role"] != session.role
            or account["hash"] != session.account_hash
        ):
            self._end(session, "invalidated")
            logger.info("session invalidated user=%s", session.username)
            return False
        return True

    def info(self, session: Session) -> dict:
        now = self.clock()
        return {
            "role": session.role,
            "username": session.username,
            "idle_timeout_s": self.config.idle,
            "expires_in_s": max(0, int(self.config.absolute - (now - session.created))),
        }

    def add_end_hook(self, session: Session, callback) -> None:
        with self._lock:
            session.on_end.append(callback)

    def remove_end_hook(self, session: Session, callback) -> None:
        with self._lock:
            if callback in session.on_end:
                session.on_end.remove(callback)

    def _end(self, session: Session, reason: str) -> None:
        with self._lock:
            if self._sessions.get(session.token_hash) is session:
                del self._sessions[session.token_hash]
            hooks, session.on_end = list(session.on_end), []
        for hook in hooks:
            try:
                hook(reason)
            except Exception:
                logger.error("internal error source=session")

    def sweep(self) -> None:
        """Expire idle/absolute sessions (called periodically by stream senders)."""
        with self._lock:
            for session in list(self._sessions.values()):
                self._still_valid(session)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
