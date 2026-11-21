# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Notification manager: dedupe + unread state in task_comms.notifications (0.3.1), desktop popups via
org.freedesktop.Notifications.Notify on the session bus (jeepney, typed signature 'susssasa{sv}i', no shell).

* Locked or uncertain sign-in state -> generic "New Mesh Message" (counts kept); never unlocks anything.
* Privacy: preview off by default; sender display configurable; per-protocol and per-conversation mute.
* History-sync items are recorded already-read and never pop up. Duplicates never pop up twice.
* Popups for one conversation replace each other (replaces_id) instead of stacking.
* No notification daemon on the bus -> popups are skipped (badge still works); nothing is installed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from task_mesh.hub.model import LABELS, SYNC, HubMessage

log = logging.getLogger(__name__)


@dataclass
class NotifySettings:
    enabled: bool = True
    show_preview: bool = False
    show_sender: bool = True
    sound: bool = True
    muted_protocols: set = field(default_factory=set)
    muted_conversations: set = field(default_factory=set)   # {"meshcore|ch:0", ...}
    quiet: bool = False                  # quiet mode: no popups and no sound; counts/badge still update
    quiet_hours: str = ""                # optional "22:00-07:00" local time; quiet inside the window
    history_days: int = 365              # hub message history retention (0 = keep forever)

    def is_quiet(self, now=None) -> bool:
        if self.quiet:
            return True
        try:
            a, b = self.quiet_hours.split("-")
            ah, am = map(int, a.split(":"))
            bh, bm = map(int, b.split(":"))
        except (ValueError, AttributeError):
            return False
        import time as _t
        lt = _t.localtime(now)
        cur, start, end = lt.tm_hour * 60 + lt.tm_min, ah * 60 + am, bh * 60 + bm
        return start <= cur < end if start <= end else (cur >= start or cur < end)

    @classmethod
    def from_dict(cls, d: dict) -> "NotifySettings":
        d = d or {}
        return cls(enabled=bool(d.get("enabled", True)), show_preview=bool(d.get("show_preview", False)),
                   show_sender=bool(d.get("show_sender", True)), sound=bool(d.get("sound", True)),
                   muted_protocols=set(d.get("muted_protocols") or ()),
                   muted_conversations=set(d.get("muted_conversations") or ()), quiet=bool(d.get("quiet", False)),
                   quiet_hours=str(d.get("quiet_hours") or ""),
                   history_days=max(0, int(d.get("history_days", 365) or 0)))

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "show_preview": self.show_preview, "show_sender": self.show_sender,
                "sound": self.sound, "muted_protocols": sorted(self.muted_protocols),
                "muted_conversations": sorted(self.muted_conversations), "quiet": self.quiet,
                "quiet_hours": self.quiet_hours, "history_days": self.history_days}


TITLE = "T.A.S.K. — New Mesh Message"
EXPIRE_MS = 5000
NOTIFY_PATH = "/org/freedesktop/Notifications"
NOTIFY_NAME = "org.freedesktop.Notifications"


def session_bus_address(env=None) -> Optional[str]:
    """DBUS_SESSION_BUS_ADDRESS, else the systemd user bus socket ($XDG_RUNTIME_DIR/bus, dbus-user-session).
    A systemd --user service has the latter; an X session started with dbus-launch has its own address."""
    import os
    env = os.environ if env is None else env
    a = env.get("DBUS_SESSION_BUS_ADDRESS")
    if a:
        return a
    rd = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    p = os.path.join(rd, "bus")
    return f"unix:path={p}" if os.path.exists(p) else None


class JeepneySender:
    """Notify on the session bus via one jeepney router (thread-safe). Returns the server id, or None if no
    daemon / no bus. ActionInvoked / NotificationClosed for our ids are delivered to on_action / on_closed.
    Reconnects lazily after a bus or daemon restart."""

    def __init__(self, on_action: Optional[Callable[[int, str], None]] = None,
                 on_closed: Optional[Callable[[int], None]] = None, address: Optional[str] = None) -> None:
        self.on_action, self.on_closed, self.address = on_action, on_closed, address
        self._router = None
        self._cm = None
        self._lock = threading.Lock()
        self._listener: Optional[threading.Thread] = None

    def _open(self):
        if self._router is not None:
            return self._router
        from jeepney.io.threading import open_dbus_router
        addr = self.address or session_bus_address()
        if not addr:
            raise ConnectionError("no session bus")
        self._cm = open_dbus_router(bus=addr)
        self._router = self._cm.__enter__()
        if self.on_action is not None or self.on_closed is not None:
            self._start_listener(self._router)
        return self._router

    def _reset(self) -> None:
        cm, self._cm, self._router = self._cm, None, None
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass

    def _start_listener(self, router) -> None:
        import queue as _q

        from jeepney import MatchRule, message_bus
        q: _q.Queue = _q.Queue(maxsize=256)
        rules = [MatchRule(type="signal", interface=NOTIFY_NAME, path=NOTIFY_PATH, member=m)
                 for m in ("ActionInvoked", "NotificationClosed")]
        for r in rules:
            router.filter(r, queue=q, bufsize=256)
            try:
                router.send_and_get_reply(message_bus.AddMatch(r), timeout=3)
            except Exception:  # noqa: BLE001
                pass

        def loop():
            while self._router is router:
                try:
                    m = q.get(timeout=0.5)
                except _q.Empty:
                    continue
                try:
                    member = m.header.fields.get(3) if hasattr(m.header, "fields") else None
                    from jeepney.low_level import HeaderFields
                    member = m.header.fields.get(HeaderFields.member, member)
                    if member == "ActionInvoked" and self.on_action:
                        self.on_action(int(m.body[0]), str(m.body[1]))
                    elif member == "NotificationClosed" and self.on_closed:
                        self.on_closed(int(m.body[0]))
                except Exception:  # noqa: BLE001
                    log.exception("notification signal handling failed")
        self._listener = threading.Thread(target=loop, name="mesh-notify-signals", daemon=True)
        self._listener.start()

    def _call(self, member: str, sig: Optional[str] = None, body: tuple = (), dest=NOTIFY_NAME, path=NOTIFY_PATH,
              iface=NOTIFY_NAME):
        from jeepney import DBusAddress, new_method_call
        addr = DBusAddress(path, bus_name=dest, interface=iface)
        msg = new_method_call(addr, member, sig, body) if sig else new_method_call(addr, member)
        with self._lock:
            try:
                return self._open().send_and_get_reply(msg, timeout=3)
            except Exception:
                self._reset()
                raise

    def available(self) -> bool:
        try:
            r = self._call("NameHasOwner", "s", (NOTIFY_NAME,), dest="org.freedesktop.DBus",
                           path="/org/freedesktop/DBus", iface="org.freedesktop.DBus")
            return bool(r.body[0])
        except Exception:  # noqa: BLE001
            return False

    def server_information(self) -> Optional[tuple]:
        try:
            return tuple(self._call("GetServerInformation").body)
        except Exception:  # noqa: BLE001
            return None

    def capabilities(self) -> list:
        try:
            return list(self._call("GetCapabilities").body[0])
        except Exception:  # noqa: BLE001
            return []

    def __call__(self, args: dict, replaces_id: int = 0) -> Optional[int]:
        try:
            hints = {}
            for k, v in args["hints"].items():
                if k == "urgency":
                    hints[k] = ("y", int(v))
                elif isinstance(v, bool):
                    hints[k] = ("b", v)
                elif isinstance(v, int):
                    hints[k] = ("i", v)
                else:
                    hints[k] = ("s", str(v))
            actions = [str(a) for a in args.get("actions", [])]
            r = self._call("Notify", "susssasa{sv}i",
                           (args["app_name"], int(replaces_id) & 0xFFFFFFFF, "task-mesh", args["summary"],
                            args["body"], actions, hints, int(args.get("expire_timeout", EXPIRE_MS))))
            if r.header.message_type.name == "error":
                raise ConnectionError("Notify error")
            return int(r.body[0])
        except Exception as exc:  # noqa: BLE001 - no daemon / no bus: badge still works
            log.info("desktop notification not shown (%s)", type(exc).__name__, extra={"event": "mesh.notify_skip"})
            return None

    def close(self) -> None:
        with self._lock:
            self._reset()


def format_notification(m: HubMessage, settings: "NotifySettings", locked: bool, burst: int = 0) -> dict:
    """Notify arguments. Title is always TITLE. Unlocked: protocol always; sender if show_sender; preview only
    if show_preview. Locked/unknown: generic body. Burst (>1 recent): one grouped notification with a count."""
    from task_comms import notifications as nt
    hints = {"urgency": 2 if m.priority else 1, "category": "im.received", "desktop-entry": "task-mesh"}
    hints["suppress-sound"] = True  # Audio handled directly to avoid duplicate alerts
    summary = TITLE + (" [PRIORITY]" if m.priority else "")
    if burst > 1:
        body = f"{burst} new mesh messages" + ("" if locked else " — open T.A.S.K. Mesh to read")
    elif locked:
        body = "Sign in to T.A.S.K. Mesh to read it."
    else:
        where = "Direct message" if m.kind == "dm" else m.conversation.replace("ch:", "Channel ")
        who = (m.sender_label or m.sender) if settings.show_sender else ""
        head = " · ".join(x for x in (LABELS[m.protocol], who, where) if x)
        if m.priority and m.priority_source:
            head += f" (priority: {m.priority_source})"
        body = head
        if settings.show_preview:
            clean = m.text.replace(nt.BELL, "").strip()
            body += "\n" + clean[:nt.PREVIEW_MAX] + ("…" if len(clean) > nt.PREVIEW_MAX else "")
    return {"app_name": "T.A.S.K. Mesh", "summary": summary, "body": body, "hints": hints,
            "actions": ["default", "Open"], "expire_timeout": EXPIRE_MS}


class NotificationManager:
    BURST_WINDOW_S = 10.0
    BURST_AT = 3                 # from the 3rd pop-up inside the window on, one grouped notification is updated

    def __init__(self, comms_store, sender: Callable[..., Optional[int]], settings: Optional[NotifySettings] = None,
                 auth_state: Callable[[], str] = lambda: "unknown", focus_state: Callable[[], bool] = lambda: False,
                 clock=None) -> None:
        import time as _t
        self.store = comms_store
        self.sender = sender
        self.settings = settings or NotifySettings()
        self.auth_state = auth_state          # "unlocked" | "locked" | "unknown"
        self.focus_state = focus_state        # True while a Mesh window holds a live focus lease
        self.clock = clock or _t.time
        self._replace: dict[str, int] = {}
        self._recent: list[float] = []
        self._burst = 0
        self.refs: dict[int, int] = {}        # notification server id -> hub message row id (internal only)
        self.shown = 0
        self.suppressed_focus = 0

    def handle(self, m: HubMessage) -> Optional[dict]:
        """Record (dedupe) and maybe pop up. -> the Notify args that were sent, or None."""
        from task_comms import notifications as nt
        if m.direction != "in":
            return None
        n = nt.Notification(source=nt.mesh_source(m.protocol), message_id=m.key, conversation=m.conversation,
                            sender=m.sender, sender_label=m.sender_label if self.settings.show_sender else "",
                            channel_label="Direct message" if m.kind == "dm" else m.conversation.replace("ch:", "Channel "),
                            preview=None, received_at=m.ts, origin=nt.HISTORY if m.origin == SYNC else nt.LIVE,
                            priority=m.priority, priority_reason=m.priority_source)
        if not self.store.record(n):
            return None                       # duplicate (also after a reconnect) or history-sync: no popup
        s = self.settings
        if not s.enabled or m.protocol in s.muted_protocols or f"{m.protocol}|{m.conversation}" in s.muted_conversations:
            return None
        if s.is_quiet(m.ts):
            return None
        if self.focus_state():
            self.suppressed_focus += 1        # Mesh window focused: no pop-up, nothing marked read
            return None
        now = self.clock()
        self._recent = [t for t in self._recent if now - t < self.BURST_WINDOW_S] + [now]
        locked = self.auth_state() != "unlocked"
        if len(self._recent) >= self.BURST_AT:
            self._burst = self._burst + 1 if self._burst else len(self._recent)
            args = format_notification(m, s, locked, burst=self._burst)
            rkey = "burst"
        else:
            self._burst = 0
            args = format_notification(m, s, locked)
            rkey = "generic" if locked else f"{m.protocol}|{m.conversation}"
        if s.sound:
            try:
                import subprocess
                from pathlib import Path
                alert = Path.home() / ".local/share/task-mesh/sounds/mesh-alert.wav"
                if alert.is_file():
                    subprocess.Popen(
                        ["/usr/bin/paplay", str(alert)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        close_fds=True,
                    )
            except Exception:
                log.exception("mesh notification audio failed")
        nid = self.sender(args, self._replace.get(rkey, 0))
        if nid:
            self._replace[rkey] = nid
            if m.id is not None:
                self.refs[int(nid)] = int(m.id)
                if len(self.refs) > 500:
                    self.refs.pop(next(iter(self.refs)))
        self.shown += 1
        return args

    def closed(self, nid: int) -> None:
        for k, v in list(self._replace.items()):
            if v == nid:
                del self._replace[k]

    def mark_read(self, protocol: str, conversation: str) -> None:
        from task_comms import notifications as nt
        self.store.mark_read(nt.mesh_source(protocol), conversation)
