# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-core link state for the launcher: connect, reconnect with backoff, version, public data,
sign-in/sign-out/lock. Modelled on task-console's Controller (console/task_console/controller.py)
and limited to the verified v2 methods listed in ARCHITECTURE.md.

All values shown come from task-core in the current boot or are local link state. Nothing is
written to disk; the session token lives only in CoreClient memory. task-core enforces the 2 h idle
and 12 h absolute session limits; the launcher adds the Phase 2 in-window idle lock (1-10 min).
"""

import logging
import math
import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("task_launcher")

BACKOFF = (0.5, 1.0, 2.0, 4.0, 8.0)
STEADY_RETRY = 10.0
JITTER = 0.2
TOO_OLD_PROBE = 60.0
NO_ACCESS_RETRY = 10.0
PROTOCOL_TIMEOUT_MS = 5000
HEALTH_REFRESH_MS = 30000
ROLES = ("public", "operator", "administrator")
MSG_EXPIRED = "Session ended — please sign in again"
MSG_RESTARTED = "task-core restarted — please sign in again"


def backoff_delay(failures: int, rng=random.random) -> float:
    base = BACKOFF[failures] if failures < len(BACKOFF) else STEADY_RETRY
    return base * (1.0 + (rng() * 2.0 - 1.0) * JITTER)


def rank(role):
    return ROLES.index(role) if role in ROLES else 0


class CoreLink(QObject):
    changed = Signal(str)        # link | health | counts | caps | role | devices
    notice = Signal(str, str)    # severity, text
    lockChanged = Signal(bool)

    def __init__(self, client, *, clock=time.monotonic, rng=random.random, health_refresh_ms=HEALTH_REFRESH_MS,
                 parent=None):
        super().__init__(parent)
        self.client = client
        self.clock = clock
        self.rng = rng
        self.link = "connecting"
        self.protocol = None
        self.health = None
        self.counts = None
        self.capabilities = None
        self.devices = None
        self.boot_id = None
        self.role = "public"
        self.username = None
        self.locked = False
        self.retry_at = None
        self.retry_delays = []
        self._failures = 0
        self._attempt_seq = 0
        self._stopped = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._attempt)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(health_refresh_ms)
        self._health_timer.timeout.connect(self._refresh_health)
        client.streamOpened.connect(lambda _r: None)
        client.streamEvent.connect(self._on_event)
        client.streamEnded.connect(self._on_stream_ended)

    # ------------------------------------------------------------------ queries
    @property
    def live(self):
        return self.link == "connected"

    @property
    def signed_in(self):
        return rank(self.role) >= rank("operator")

    def at_least(self, role):
        return rank(self.role) >= rank(role)

    def version(self):
        """Core version as reported (core.health.version, else core.protocol.core), or None."""
        if isinstance(self.health, dict) and isinstance(self.health.get("version"), str):
            return self.health["version"]
        if isinstance(self.protocol, dict) and isinstance(self.protocol.get("core"), str):
            return self.protocol["core"]
        return None

    def retry_in(self):
        if self.retry_at is None:
            return 0
        return max(0, math.ceil(self.retry_at - self.clock()))

    def footer_text(self):
        """(text, colour token) for the footer core indicator (02-launcher-ui.md section 11)."""
        if self.link == "connected":
            if isinstance(self.health, dict) and self.health.get("ok") is False:
                return "T.A.S.K. Core · reports not ok", "warn"
            return f"T.A.S.K. Core · connected · {self.version() or '—'}", "ok"
        if self.link == "connecting":
            return "T.A.S.K. Core · connecting…", "text2"
        if self.link == "too-old":
            return "T.A.S.K. Core · too old (0.1.x) — 0.2.0 or later required", "warn"
        if self.link == "no-access":
            return f"T.A.S.K. Core · no access to {self.client.socket_path}", "err"
        return f"T.A.S.K. Core · disconnected — retry in {self.retry_in()} s", "err"

    # ------------------------------------------------------------------ link
    def start(self):
        self._stopped = False
        self._attempt()

    def stop(self):
        """Clean shutdown: stop timers, revoke a held session (one try), close sockets."""
        self._stopped = True
        self._retry.stop()
        self._health_timer.stop()
        token = self.client.take_token()
        self.client.invalidate_pending()
        if token is not None and self.live:
            self.client.request("session.logout", None, None, token=token, timeout_ms=1000)
        self.client.close_stream()

    def retry_now(self):
        if not self.live:
            self._attempt()

    def _schedule(self, delay):
        if self._stopped:
            return
        self.retry_delays.append(delay)
        self.retry_at = self.clock() + delay
        self._retry.start(max(1, int(delay * 1000)))

    def _attempt(self):
        if self._stopped:
            return
        self._retry.stop()
        self.retry_at = None
        if self.link != "too-old":
            self.link = "connecting"
            self.changed.emit("link")
        self._attempt_seq += 1
        attempt = self._attempt_seq
        self.client.close_stream()
        self.client.reset_rpc()
        self.client.request("core.protocol", session=False, timeout_ms=PROTOCOL_TIMEOUT_MS, durable=True,
                            callback=lambda r: self._on_protocol(r) if attempt == self._attempt_seq else None)

    def _set_offline(self, link):
        self.link = link
        self._health_timer.stop()
        if link == "no-access":
            self._schedule(NO_ACCESS_RETRY)
        elif link == "too-old":
            self._schedule(TOO_OLD_PROBE)
        else:
            self._schedule(backoff_delay(self._failures, self.rng))
            self._failures += 1
        self.changed.emit("link")

    def _on_loss(self, reason):
        if self.link != "connected":
            return
        logger.info("task-core connection lost (%s)", reason)
        self.link = "lost"
        self.client.close_stream()
        self.client.reset_rpc()
        self._failures = 0
        self.devices = None
        self.changed.emit("devices")
        self._set_offline("offline")

    def _on_protocol(self, reply):
        transport = reply.get("transport")
        if transport:
            self._set_offline("no-access" if transport == "access" else "offline")
            return
        error = reply.get("error") or {}
        if reply.get("v") == 1 or error.get("message") == "unsupported version":
            self._set_offline("too-old")
            return
        result = reply.get("result")
        if reply.get("ok") is not True or not isinstance(result, dict) or 2 not in (result.get("versions") or []):
            self._set_offline("offline")
            return
        self._failures = 0
        self.protocol = result
        new_boot = result.get("boot_id")
        if self.boot_id is not None and new_boot != self.boot_id:
            had = self.client.take_token() is not None or self.signed_in
            self.role, self.username, self.devices = "public", None, None
            if had:
                self.notice.emit("warning", MSG_RESTARTED)
            self.changed.emit("role")
        self.boot_id = new_boot
        self.link = "connected"
        self.changed.emit("link")
        self._subscribe()
        self._reload()
        self._health_timer.start()

    # ------------------------------------------------------------------ requests
    def _consumed(self, reply):
        if reply.get("ok") is True:
            return False
        err = reply.get("error") or {}
        if err.get("code") == "unauthenticated" and err.get("message") == "session invalid":
            self._session_expired()
            return True
        return False

    def _request(self, method, on_result, params=None):
        def done(reply):
            if reply.get("transport"):
                self._on_loss(method)
                return
            if self._consumed(reply):
                return
            if reply.get("ok") is True:
                on_result(reply.get("result") or {})
        return self.client.request(method, params, done)

    def _reload(self):
        self._request("core.health", self._set_health)
        self._request("device.counts", self._set_counts)
        self._request("capability.list", self._set_caps)

    def _refresh_health(self):
        if self.live:
            self._request("core.health", self._set_health)

    def _set_health(self, result):
        self.health = result
        self.changed.emit("health")
        self.changed.emit("link")

    def _set_counts(self, result):
        self.counts = result if isinstance(result, dict) and isinstance(result.get("total"), int) else None
        self.changed.emit("counts")

    def _set_caps(self, result):
        caps = result.get("capabilities")
        self.capabilities = caps if isinstance(caps, list) else None
        self.changed.emit("caps")

    def capability_status(self, name):
        for c in self.capabilities or []:
            if isinstance(c, dict) and c.get("name") == name:
                return c.get("status")
        return None

    def fetch_devices(self, callback=None):
        """device.list (operator and above). callback(result-or-None, reply)."""
        if not self.signed_in or not self.live:
            if callback:
                callback(None, {"ok": False, "error": {"code": "forbidden", "message": "sign in as operator"}})
            return

        def done(reply):
            if reply.get("transport"):
                self._on_loss("device.list")
            elif not self._consumed(reply) and reply.get("ok") is True and self.signed_in:
                self.devices = reply.get("result")
                self.changed.emit("devices")
            if callback:
                callback(self.devices if reply.get("ok") is True else None, reply)

        self.client.request("device.list", None, done)

    # ------------------------------------------------------------------ stream
    def _subscribe(self):
        self.client.open_stream(["core.", "capability.", "device.counts"])

    def _on_event(self, event):
        topic = str(event.get("topic", ""))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if topic == "device.counts":
            self._set_counts(data)
            if self.signed_in:
                self.fetch_devices()
        elif topic == "capability.changed":
            self._request("capability.list", self._set_caps)
        elif topic == "core.stopping":
            self._on_loss("core-stopping")

    def _on_stream_ended(self, reason):
        if self._stopped:
            return
        if reason in ("session-ended", "error:unauthenticated"):
            self._session_expired()
        elif reason == "overflow":
            if self.live:
                self._subscribe()
                self._reload()
        else:
            self._on_loss(reason)

    # ------------------------------------------------------------------ session
    def _drop_session_state(self):
        self.role, self.username, self.devices = "public", None, None
        self.changed.emit("devices")
        self.changed.emit("role")

    def _session_expired(self):
        token = self.client.take_token()
        if token is None and not self.signed_in:
            return
        self._drop_session_state()
        self.notice.emit("warning", MSG_EXPIRED)
        if self.live:
            self._subscribe()

    def login(self, username, password, callback, still_wanted=lambda: True):
        """session.login. The password is passed straight into the request and not kept."""
        if not self.live:
            callback({"ok": False, "error": {"code": "unavailable", "message": "task-core unavailable"},
                      "transport": "offline"})
            return

        def done(reply):
            if reply.get("ok") is True and not still_wanted():
                self.client.request("session.logout", None, None, token=reply["result"]["session"], timeout_ms=3000)
                callback(reply)
                return
            if reply.get("ok") is True:
                result = reply["result"]
                self.client.set_token(result["session"])
                self.role = result.get("role") if result.get("role") in ROLES else "public"
                self.username = result.get("username")
                if self.locked:
                    self.locked = False
                    self.lockChanged.emit(False)
                self.changed.emit("role")
                self._subscribe()
                if self.signed_in:
                    self.fetch_devices()
            callback(reply)

        self.client.request("session.login", {"username": username, "secret": password}, done, session=False)

    def logout(self, lock=False, trigger="user"):
        """Sign out (or lock): synchronous local drop, then one session.logout with the old token."""
        token = self.client.take_token()
        self.client.invalidate_pending()
        was = self.signed_in
        self._drop_session_state()
        if lock and not self.locked:
            self.locked = True
            logger.info("launcher locked (%s)", trigger)
            self.lockChanged.emit(True)
        self.client.close_stream()
        if token is not None and self.live:
            self.client.request("session.logout", None, None, token=token, timeout_ms=3000)
        token = None
        if self.live:
            self._subscribe()
            self._reload()
        return was

    def lock(self, trigger="user"):
        if self.locked:
            return
        self.logout(lock=True, trigger=trigger)

    def continue_public(self):
        if self.locked:
            self.locked = False
            self.lockChanged.emit(False)
