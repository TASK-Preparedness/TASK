# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Console state machine: link, reconnect, resync, role, lock (PHASE-2.md sections 6.4, 8.7, 9).

Every value held here came from task-core in the current boot (boot_id) or is
local state (clock, link). Nothing is written to disk.
"""

import logging
import math
import random
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from task_console import session as S

logger = logging.getLogger("task_console")

BACKOFF = (0.5, 1.0, 2.0, 4.0, 8.0)
STEADY_RETRY = 10.0
JITTER = 0.2
TOO_OLD_PROBE = 60.0
NO_ACCESS_RETRY = 10.0
PROTOCOL_TIMEOUT_MS = 5000
DEVICE_LIST_MIN_INTERVAL = 0.2
NO_ACCESS_TEXT = ("No access to {path} \u2014 your account must be in group rain-core "
                  "(log out and in after adding it).")
TOO_OLD_TEXT = "task-core 0.2.0 or later is required."


def backoff_delay(failures: int, rng=random.random) -> float:
    base = BACKOFF[failures] if failures < len(BACKOFF) else STEADY_RETRY
    return base * (1.0 + (rng() * 2.0 - 1.0) * JITTER)


def _wall_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Controller(QObject):
    changed = Signal(str)  # link | health | modules | caps | counts | devices | role | seq
    lockChanged = Signal(bool)
    notice = Signal(str, str)  # severity, text

    def __init__(self, client, *, clock=time.monotonic, rng=random.random, wall_hms=_wall_hms,
                 debounce_ms: int = 200, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.clock = clock
        self.rng = rng
        self.wall_hms = wall_hms
        self.link = "connecting"
        self.restarted = False
        self.protocol = None
        self.boot_id = None
        self.health = None
        self.health_at = None
        self.modules = None
        self.capabilities = None
        self.counts = None
        self.devices = None
        self.last_seq = None
        self.role = "public"
        self.username = None
        self.locked = False
        self.stale_since = None
        self.retry_at = None
        self.retry_delays = []  # observed by tests (54); also drives the countdown
        self._failures = 0
        self._attempt_seq = 0
        self._expect_seq = None
        self._devices_inflight = False
        self._devices_dirty = False
        self._devices_sent_at = -1.0
        self.device_list_requests = 0
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._attempt)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce_ms = debounce_ms
        self._debounce.timeout.connect(self._refresh_devices)
        client.streamOpened.connect(self._on_stream_opened)
        client.streamEvent.connect(self._on_stream_event)
        client.streamHeartbeat.connect(self._on_heartbeat)
        client.streamEnded.connect(self._on_stream_ended)

    # ---------------------------------------------------------------- queries

    @property
    def live(self) -> bool:
        return self.link == "connected"

    @property
    def signed_in(self) -> bool:
        return S.at_least(self.role, "operator")

    def retry_in(self) -> int:
        if self.retry_at is None:
            return 0
        return max(0, math.ceil(self.retry_at - self.clock()))

    def link_text(self) -> str:
        if self.link == "connected":
            if self.restarted:
                return "Core restarted"
            return f"Core connected \u00b7 {(self.protocol or {}).get('core') or chr(0x2014)}"
        if self.link == "connecting":
            return "Connecting\u2026"
        if self.link == "too-old":
            return "Core too old (0.1.x)"
        return f"Core offline \u2014 retry in {self.retry_in()} s"

    # ---------------------------------------------------------------- link

    def start(self) -> None:
        self._attempt()

    def retry_now(self) -> None:
        """F5 while not connected; also used by tests instead of waiting for the backoff."""
        if not self.live:
            self._attempt()

    def reload(self) -> None:
        """F5: reload the current state from task-core (or retry immediately when offline)."""
        if self.live:
            self._full_reload()
            if self.signed_in:
                self._refresh_devices()
        else:
            self._attempt()

    def _schedule(self, delay: float) -> None:
        self.retry_delays.append(delay)
        self.retry_at = self.clock() + delay
        self._retry.start(max(1, int(delay * 1000)))

    def _attempt(self) -> None:
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
                            callback=lambda reply: self._on_protocol(reply) if attempt == self._attempt_seq else None)

    def _set_offline(self, link: str) -> None:
        previous = self.link
        self.link = link
        if self.devices is not None and self.stale_since is None:
            self.stale_since = self.wall_hms()
        if link == "no-access":
            self._schedule(NO_ACCESS_RETRY)
            if previous != "no-access":
                self.notice.emit("error", NO_ACCESS_TEXT.format(path=self.client.socket_path))
        elif link == "too-old":
            self._schedule(TOO_OLD_PROBE)
            if previous != "too-old":
                self.notice.emit("error", "Core too old (0.1.x): " + TOO_OLD_TEXT)
        else:
            self._schedule(backoff_delay(self._failures, self.rng))
            self._failures += 1
        self.changed.emit("link")

    def _on_loss(self, reason: str) -> None:
        if self.link != "connected":
            return
        logger.info("task-core connection lost (%s)", reason)
        self.link = "lost"  # re-entrant calls from failing callbacks return early
        self._debounce.stop()
        self.client.close_stream()
        self.client.reset_rpc()
        self._failures = 0
        self._set_offline("offline")

    def _on_protocol(self, reply: dict) -> None:
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
            self.boot_id = new_boot
            self._core_restarted()
        elif self.boot_id is not None and self.last_seq is not None:
            self._resync(after_loss=True)
        else:
            self.boot_id = new_boot
            self.link = "connected"
            self.changed.emit("link")
            self._subscribe()
            self._full_reload()

    def _core_restarted(self) -> None:
        had_session = self.client.take_token() is not None or self.signed_in
        self.role, self.username = "public", None
        self._drop_operator_data()
        self.last_seq = None
        self.restarted = True
        self.link = "connected"
        if had_session:
            self.notice.emit("warning", S.MSG_RESTARTED)
        self.changed.emit("role")
        self.changed.emit("link")
        self._subscribe()
        self._full_reload()

    def _resync(self, after_loss: bool) -> None:
        params = {"seq": int(self.last_seq or 0), "boot_id": self.boot_id or ""}

        def done(reply):
            if reply.get("transport"):
                if after_loss:
                    self._set_offline("offline")
                else:
                    self._on_loss("since")
                return
            if self._consumed(reply):
                if after_loss:
                    self.link = "connected"
                    self.changed.emit("link")
                    self._subscribe()
                    self._full_reload()
                return
            if reply.get("ok") is not True:
                self._full_reload()
            else:
                result = reply["result"]
                if result.get("gap"):
                    self._full_reload()
                else:
                    for event in result.get("events") or []:
                        self._apply_event(event)
                    if isinstance(result.get("seq"), int):
                        self.last_seq = result["seq"]
                    self._expect_seq = self.last_seq
                    self._request("core.health", self._set_health)
            if after_loss:
                self.link = "connected"
                self.stale_since = None
                self.changed.emit("link")
            self._subscribe()

        self.client.request("events.since", params, done)

    # ---------------------------------------------------------------- requests

    def _consumed(self, reply: dict) -> bool:
        """Handle the role-affecting errors common to every request. True if handled here."""
        if reply.get("ok") is True:
            return False
        code = (reply.get("error") or {}).get("code")
        if code == "unauthenticated" and (reply.get("error") or {}).get("message") == "session invalid":
            self._session_expired()
            return True
        if code == "forbidden":
            self._forbidden((reply.get("error") or {}).get("message", ""))
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

    def _full_reload(self) -> None:
        remaining = {"n": 4}

        def step(setter):
            def apply(result):
                setter(result)
                remaining["n"] -= 1
                if remaining["n"] == 0 and self.restarted:
                    self.restarted = False
                    self.changed.emit("link")
            return apply

        self._request("core.health", step(self._set_health))
        self._request("module.list", step(self._set_modules))
        self._request("capability.list", step(self._set_caps))
        self._request("device.counts", step(self._set_counts))
        if self.signed_in:
            self._refresh_devices()

    def _set_health(self, result):
        self.health = result
        self.health_at = self.wall_hms()
        self.changed.emit("health")

    def _set_modules(self, result):
        modules = result.get("modules")
        self.modules = sorted(modules, key=lambda m: (m.get("id") != "system", str(m.get("id")))) \
            if isinstance(modules, list) else None
        self.changed.emit("modules")

    def _set_caps(self, result):
        caps = result.get("capabilities")
        self.capabilities = caps if isinstance(caps, list) else None
        self.changed.emit("caps")

    def _set_counts(self, result):
        self.counts = result if isinstance(result, dict) and "total" in result else None
        self.changed.emit("counts")

    def _set_devices(self, result):
        if not self.signed_in:
            return
        self.devices = result if isinstance(result.get("devices"), list) else None
        self.stale_since = None
        self.changed.emit("devices")

    def _schedule_devices(self) -> None:
        if self.signed_in and not self._debounce.isActive():
            self._debounce.start(self._debounce_ms)

    def _refresh_devices(self) -> None:
        if not self.signed_in or not self.live:
            return
        if self._devices_inflight:
            self._devices_dirty = True
            return
        since = time.monotonic() - self._devices_sent_at
        if since < DEVICE_LIST_MIN_INTERVAL:
            # at most one device.list per 200 ms, whatever triggered it (8.7, test 74)
            if not self._debounce.isActive():
                self._debounce.start(max(1, int((DEVICE_LIST_MIN_INTERVAL - since) * 1000) + 1))
            return
        self._devices_sent_at = time.monotonic()
        self._devices_inflight = True
        self.device_list_requests += 1
        def done(reply):
            self._devices_inflight = False
            if reply.get("transport"):
                self._on_loss("device.list")
                return
            if self._consumed(reply):
                return
            if reply.get("ok") is True:
                self._set_devices(reply.get("result") or {})
            if self._devices_dirty:
                self._devices_dirty = False
                self._schedule_devices()

        self.client.request("device.list", None, done)

    def fetch_devices(self, callback) -> None:
        """A fresh device.list for building a confirmation (8.5). callback(result or None, reply)."""

        def done(reply):
            if reply.get("transport"):
                self._on_loss("device.list")
                callback(None, reply)
                return
            if self._consumed(reply):
                callback(None, reply)
                return
            if reply.get("ok") is True:
                self._set_devices(reply.get("result") or {})
                callback(reply.get("result"), reply)
            else:
                callback(None, reply)

        self.device_list_requests += 1
        self.client.request("device.list", None, done)

    def assign(self, logical, device_id, alias, confirm_displace, callback) -> None:
        params = {"logical": logical, "device_id": device_id}
        if alias:
            params["alias"] = alias
        if confirm_displace:
            params["confirm_displace"] = True
        self._mutation("device.assign", params, callback)

    def unassign(self, logical, callback) -> None:
        self._mutation("device.unassign", {"logical": logical}, callback)

    def _mutation(self, method, params, callback) -> None:
        def done(reply):
            if reply.get("transport"):
                self._on_loss(method)
                callback(reply)
                return
            code = (reply.get("error") or {}).get("code")
            if code in ("unauthenticated", "forbidden"):
                callback(reply)
                self._consumed(reply)
                return
            callback(reply)
            if reply.get("ok") is True:
                self._schedule_devices()

        self.client.request(method, params, done)

    # ---------------------------------------------------------------- stream

    def _subscribe(self) -> None:
        self.client.open_stream([])

    def _on_stream_opened(self, result: dict) -> None:
        seq = result.get("seq")
        if isinstance(seq, int):
            if self._expect_seq is not None and seq > self._expect_seq:
                self._full_reload()  # events between events.since and the subscription
            self.last_seq = seq if self.last_seq is None else max(self.last_seq, seq)
            self.changed.emit("seq")
        self._expect_seq = None

    def _on_heartbeat(self, heartbeat: dict) -> None:
        seq = heartbeat.get("seq")
        if isinstance(seq, int) and (self.last_seq is None or seq > self.last_seq):
            self.last_seq = seq
            self.changed.emit("seq")

    def _on_stream_event(self, event: dict) -> None:
        seq = event.get("seq")
        if isinstance(seq, int):
            if self.last_seq is not None and seq <= self.last_seq:
                return
            self.last_seq = seq
        self._apply_event(event)
        self.changed.emit("seq")

    def _apply_event(self, event: dict) -> None:
        topic = str(event.get("topic", ""))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if topic == "device.counts":
            self._set_counts(data)
        elif topic == "capability.changed":
            if self.capabilities is not None and data.get("name"):
                for entry in self.capabilities:
                    if entry.get("name") == data["name"]:
                        entry.update({k: data[k] for k in ("kind", "status") if k in data})
                        break
                else:
                    self.capabilities.append(dict(data))
                self.changed.emit("caps")
            self._schedule_devices()
        elif topic in ("module.state", "module.rejected"):
            if self.modules is not None:
                for entry in self.modules:
                    if entry.get("id") == data.get("id"):
                        if topic == "module.rejected":
                            entry.update(state="rejected", reason=data.get("reason"))
                        else:
                            entry["state"] = data.get("state")
                self.changed.emit("modules")
        elif topic.startswith("device."):
            self._schedule_devices()
        elif topic == "core.stopping":
            self._on_loss("core-stopping")

    def _on_stream_ended(self, reason: str) -> None:
        if reason == "session-ended" or reason == "error:unauthenticated":
            self._session_expired()
        elif reason == "overflow":
            self._resync(after_loss=False)
        else:
            if reason == "error:busy":
                self.notice.emit("warning", "task-core refused the event stream: too many streams")
            self._on_loss(reason)

    # ---------------------------------------------------------------- session

    def _drop_operator_data(self) -> None:
        self.devices = None
        self.stale_since = None
        self._debounce.stop()
        self._devices_dirty = False
        for module in self.modules or []:
            module.pop("logical_devices", None)
        self.changed.emit("devices")
        self.changed.emit("modules")

    def _session_expired(self) -> None:
        token = self.client.take_token()
        if token is None and not self.signed_in:
            return
        self.role, self.username = "public", None
        self._drop_operator_data()
        self.notice.emit("warning", S.MSG_EXPIRED)
        self.changed.emit("role")
        if self.live:
            self._subscribe()
            self._full_reload()

    def _forbidden(self, message: str) -> None:
        self.notice.emit("error", f"task-core refused: {message}")

        def done(reply):
            if reply.get("transport") or reply.get("ok") is not True:
                if (reply.get("error") or {}).get("code") == "unauthenticated":
                    self._session_expired()
                return
            role = reply["result"].get("role", "public")
            if role != self.role:
                self.role = role if role in S.ROLES else "public"
                self.username = reply["result"].get("username") if self.signed_in else None
                if not self.signed_in:
                    self.client.take_token()
                    self._drop_operator_data()
                self.changed.emit("role")

        self.client.request("session.whoami", None, done)

    def login(self, username: str, password: str, callback, still_wanted=lambda: True) -> None:
        if not self.live:
            callback({"ok": False, "error": {"code": "unavailable", "message": S.MSG_UNAVAILABLE},
                      "transport": "offline"})
            return

        def done(reply):
            if reply.get("ok") is True and not still_wanted():
                # the dialog was cancelled while the login was in flight: revoke, do not adopt
                self.client.request("session.logout", None, None, token=reply["result"]["session"],
                                    timeout_ms=3000)
                callback(reply)
                return
            if reply.get("ok") is True:
                result = reply["result"]
                self.client.set_token(result["session"])
                self.role = result.get("role", "public")
                self.username = result.get("username")
                was_locked, self.locked = self.locked, False
                if was_locked:
                    self.lockChanged.emit(False)
                self.changed.emit("role")
                self._subscribe()
                self._full_reload()
            callback(reply)

        self.client.request("session.login", {"username": username, "secret": password}, done, session=False)

    def lock(self, trigger: str = "user") -> None:
        """D11 lock: synchronous, in the same event-loop turn as the trigger (section 6.4)."""
        if self.locked:
            return
        logger.info("console locked (%s)", trigger)
        self.locked = True
        token = self.client.take_token()
        self.client.invalidate_pending()
        self.role, self.username = "public", None
        self._devices_inflight = False
        self._drop_operator_data()
        self.lockChanged.emit(True)
        self.changed.emit("role")
        self.client.close_stream()
        if token is not None and self.live:
            # the only request that may ever carry the old token; one attempt, 3 s, no retry
            self.client.request("session.logout", None, None, token=token, timeout_ms=3000)
        token = None
        if self.live:
            self._subscribe()
            self._full_reload()
        elif self.link == "connecting":
            self._attempt()

    def continue_public(self) -> None:
        if not self.locked:
            return
        self.locked = False
        self.lockChanged.emit(False)
        self.changed.emit("role")
