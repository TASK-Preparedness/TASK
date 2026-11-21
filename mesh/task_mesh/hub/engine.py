# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""The hub: adapters -> normalise -> priority -> store (dedupe) -> notifications -> listeners/IPC.

Sending exists only as send(), which requires explicit_user_action=True and a verified operator session.
There is no relay, auto-reply, beacon or forwarding path (see bridge.py)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from task_mesh import __version__
from task_mesh.hub.devices import Assignments, DeviceManager
from task_mesh.hub.model import LABELS, LIVE, PROTOCOLS, HubMessage, HubNode, check_protocol, dedupe_key
from task_mesh.hub.notifier import NotificationManager, NotifySettings

log = logging.getLogger(__name__)
MAX_TEXT = {"meshtastic": 200, "meshcore": 150}   # bytes; conservative (MeshCore firmware MAX_TEXT_LEN is 160)


class SendRefused(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    """Explicit user priority rule, always scoped to one protocol (identities are never merged)."""
    name: str
    protocol: str
    senders: tuple = ()
    conversations: tuple = ()


def load_rules(path: Path) -> tuple[list[Rule], dict]:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return [], {}
    rules = []
    for r in data.get("rules") or ():
        try:
            rules.append(Rule(str(r["name"])[:40], check_protocol(r["protocol"]), tuple(r.get("senders") or ()),
                              tuple(r.get("conversations") or ())))
        except (KeyError, ValueError, TypeError):
            continue
    return rules, data.get("settings") or {}


def save_notify_config(path: Path, rules: list, settings: NotifySettings) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"schema": 1, "settings": settings.to_dict(),
                   "rules": [{"name": r.name, "protocol": r.protocol, "senders": list(r.senders),
                              "conversations": list(r.conversations)} for r in rules]}, fh, indent=2)
    os.replace(tmp, path)


def core_session_role(session: str) -> Optional[str]:
    """Verify a task-core session token -> role, via session.whoami. The token is never logged or stored."""
    from task_comms.core import CoreClient, CoreError
    c = CoreClient()
    c.token = session
    try:
        return (c.call("session.whoami") or {}).get("role")
    except CoreError:
        return None


class Hub:
    def __init__(self, store, comms_store, assignments: Assignments, factories: dict, role: str,
                 notify_config: Optional[Path] = None, sender=None, scan=None, lock_factory=None,
                 session_role: Callable[[str], Optional[str]] = core_session_role, clock=time.time) -> None:
        self.store = store
        self.role = role
        self.clock = clock
        self.session_role = session_role
        self.notify_config = notify_config
        rules, settings = load_rules(notify_config) if notify_config else ([], {})
        self.rules = rules
        self._auth = "unknown"
        self._auth_session: Optional[str] = None
        self._focus: dict[str, float] = {}       # client/conn id -> lease expiry (monotonic)
        self._focus_lock = threading.Lock()
        self.opener: Optional[Callable[[dict], bool]] = None    # GUI/launcher hook for notification clicks
        self.notifier = NotificationManager(comms_store, sender or (lambda *a, **k: None),
                                            NotifySettings.from_dict(settings), auth_state=lambda: self._auth,
                                            focus_state=self.gui_focused)
        kw = {}
        if scan is not None:
            kw["scan"] = scan
        if lock_factory is not None:
            kw["lock_factory"] = lock_factory
        try:
            self.store.prune(self.notifier.settings.history_days)
        except Exception:  # noqa: BLE001
            log.exception("history prune failed")
        self.devices = DeviceManager(assignments, factories, self, role, clock=clock, **kw)
        self.assignments = assignments
        self.listeners: list[Callable[[str, dict], None]] = []
        self._lock = threading.Lock()

    # --- events from adapters (any thread) --------------------------------------------------------
    def _emit(self, kind: str, data: dict) -> None:
        for cb in list(self.listeners):
            try:
                cb(kind, data)
            except Exception:  # noqa: BLE001
                log.exception("hub listener failed")

    def apply_rules(self, m: HubMessage) -> None:
        if m.priority is not None:
            return                                  # protocol metadata already set it (labelled)
        for r in self.rules:
            if r.protocol == m.protocol and ((m.sender and m.sender in r.senders) or m.conversation in r.conversations):
                m.priority, m.priority_source = "alert", f"user-rule:{r.name}"
                return

    def on_message(self, m: HubMessage) -> Optional[int]:
        self.apply_rules(m)
        with self._lock:
            rid = self.store.add(m)
        if rid is None:
            return None
        if m.direction == "in":
            try:
                self.notifier.handle(m)
            except Exception:  # noqa: BLE001
                log.exception("notification failed")
        self._emit("message", {"id": rid, "protocol": m.protocol, "conversation": m.conversation,
                               "origin": m.origin, "direction": m.direction, "unread": self.store.unread()})
        return rid

    def on_node(self, n: HubNode) -> None:
        self.store.upsert_node(n)
        self._emit("node", {"protocol": n.protocol, "key": n.key})

    def on_device(self, st) -> None:
        self._emit("device", st.to_dict())

    # --- operations --------------------------------------------------------------------------------
    def set_auth(self, session: Optional[str]) -> str:
        """The GUI reports its sign-in. Verified with task-core; a failed check means locked. Never unlocks
        anything by itself and is forgotten on service restart."""
        if not session:
            self._auth, self._auth_session = "locked", None
        else:
            role = self.session_role(session)
            self._auth = "unlocked" if role in ("operator", "administrator") else "locked"
            self._auth_session = session if self._auth == "unlocked" else None
        return self._auth

    def recheck_auth(self) -> None:
        if self._auth_session and self.session_role(self._auth_session) is None:
            self._auth, self._auth_session = "locked", None

    def mark_read(self, protocol: str, conversation: str) -> int:
        n = self.store.mark_read(check_protocol(protocol), conversation)
        self.notifier.mark_read(protocol, conversation)
        self._emit("read", {"protocol": protocol, "conversation": conversation, "unread": self.store.unread()})
        return n

    def send(self, protocol: str, conversation: str, text: str, *, explicit_user_action: bool,
             session: Optional[str], device: Optional[str] = None) -> int:
        if explicit_user_action is not True:
            raise SendRefused("sending needs an explicit user action")
        role = self.session_role(session) if session else None
        if role not in ("operator", "administrator"):
            raise SendRefused("sign in as operator to send")
        check_protocol(protocol)
        if not isinstance(text, str) or not text.strip():
            raise SendRefused("message is empty")
        n = len(text.encode("utf-8"))
        if n > MAX_TEXT[protocol]:
            raise SendRefused(f"message is {n} bytes (max {MAX_TEXT[protocol]} for {LABELS[protocol]})")
        adapter = self.devices.adapter_for(protocol, device)
        if adapter is None:
            raise SendRefused(f"no {LABELS[protocol]} radio connected")
        ts = self.clock()
        m = HubMessage(protocol=protocol, device=adapter.key, key=dedupe_key("out", protocol, conversation, ts, text),
                       direction="out", kind="dm" if conversation.startswith("dm:") else "channel",
                       conversation=conversation, sender="local", sender_label="me", text=text, ts=ts, origin=LIVE,
                       state="queued", read=True)
        rid = self.on_message(m)
        try:
            state = adapter.send_text(conversation, text)
        except Exception as exc:  # noqa: BLE001
            state = "failed"
            log.warning("send failed (%s)", type(exc).__name__, extra={"event": "mesh.send_failed"})
        self.store.update_state(rid, state or "sent")
        self._emit("message", {"id": rid, "protocol": protocol, "conversation": conversation, "origin": LIVE,
                               "direction": "out", "unread": self.store.unread()})
        return rid

    def identify(self, key: str, opener=None) -> dict:
        """Explicit user click: read-only probe of one device (see probe.py). Takes the device lock for the
        duration; refuses if this or another process owns the device. Does not assign anything."""
        from task_mesh.hub import probe
        from task_mesh.hub.locks import Busy
        path = (self.devices.scan() or {}).get(key)
        if path is None:
            raise SendRefused("device not present")
        if key in self.devices.adapters:
            return {"key": key, "protocol": self.devices.adapters[key].protocol, "how": "connected"}
        hint = probe.usb_hint(None, None, key)
        lock = self.devices.lock_factory(path, self.role)
        try:
            lock.acquire()
        except Busy as b:
            raise SendRefused(f"device in use by {b.owner}") from None
        try:
            if opener is None:
                import serial

                def opener():
                    return serial.Serial(path, 115200, timeout=0.1, exclusive=True)
            proto, how = probe.probe_port(opener)
        finally:
            lock.release()
        return {"key": key, "protocol": proto, "how": how, "usb_hint": hint}

    def set_assignment(self, key: str, protocol: Optional[str]) -> None:
        self.assignments.set(key, protocol)
        self.devices.poll()

    # --- focus leases (FOCUS RULE) ----------------------------------------------------------------
    FOCUS_TTL_MAX = 30.0

    def set_focus(self, client: str, focused: bool, ttl: float = 15.0) -> bool:
        import time as _t
        ttl = max(1.0, min(float(ttl), self.FOCUS_TTL_MAX))
        with self._focus_lock:
            if focused:
                self._focus[client] = _t.monotonic() + ttl
            else:
                self._focus.pop(client, None)
        return self.gui_focused()

    def drop_client(self, client: str) -> None:
        with self._focus_lock:
            self._focus.pop(client, None)

    def gui_focused(self) -> bool:
        import time as _t
        now = _t.monotonic()
        with self._focus_lock:
            for k in [k for k, exp in self._focus.items() if exp <= now]:
                del self._focus[k]
            return bool(self._focus)

    # --- notification click → open conversation by internal row id only -----------------------------------
    def message_ref(self, row_id: int) -> Optional[dict]:
        r = self.store.get(int(row_id))
        return None if r is None else {"id": int(r["id"]), "protocol": r["protocol"], "conversation": r["conversation"]}

    def on_notification_action(self, nid: int, action: str) -> None:
        rid = self.notifier.refs.get(int(nid))
        if rid is None or action not in ("default", "Open"):
            return
        ref = self.message_ref(rid)
        if ref is None:
            return
        self._emit("open", ref)
        if self.opener is not None:
            try:
                self.opener(ref)
            except Exception:  # noqa: BLE001
                log.exception("open hook failed")

    def status(self) -> dict:
        import os as _os
        return {"version": __version__, "role": self.role, "pid": _os.getpid(), "auth": self._auth,
                "focused": self.gui_focused(),
                "devices": [s.to_dict() for s in self.devices.status.values()], "unread": self.store.unread(),
                "notifications": self.notifier.settings.to_dict()}

    def api(self, method: str, params: dict) -> object:
        p = params or {}
        if method == "ping":
            return {"pong": True, "role": self.role, "version": __version__}
        if method == "status":
            return self.status()
        if method == "unread":
            return self.store.unread()
        if method == "conversations":
            return self.store.conversations(p.get("protocol"))
        if method == "messages":
            return self.store.messages(p.get("protocol"), p.get("conversation"), int(p.get("limit", 500)))
        if method == "nodes":
            return self.store.nodes(p.get("protocol"))
        if method == "mark_read":
            return self.mark_read(p["protocol"], p["conversation"])
        if method == "auth":
            return self.set_auth(p.get("session"))
        if method == "set_assignment":
            if p.get("explicit_user_action") is not True:
                raise SendRefused("assignment needs an explicit user action")
            self.set_assignment(str(p["key"]), p.get("protocol"))
            return True
        if method == "send":
            return self.send(p["protocol"], p["conversation"], p["text"],
                             explicit_user_action=p.get("explicit_user_action") is True, session=p.get("session"),
                             device=p.get("device"))
        if method == "identify":
            if p.get("explicit_user_action") is not True:
                raise SendRefused("identify needs an explicit user action")
            return self.identify(str(p["key"]))
        if method == "focus":
            return {"focused": self.set_focus(str(p.get("_conn") or p.get("client") or "local"),
                                              p.get("focused") is True, float(p.get("ttl", 15.0)))}
        if method == "message_ref":
            return self.message_ref(int(p["id"]))
        if method == "set_notify":
            s = NotifySettings.from_dict({**self.notifier.settings.to_dict(), **(p.get("settings") or {})})
            self.notifier.settings = s
            if self.notify_config:
                save_notify_config(self.notify_config, self.rules, s)
            return s.to_dict()
        raise KeyError(f"unknown method {method}")

    def shutdown(self) -> None:
        self.devices.shutdown()
