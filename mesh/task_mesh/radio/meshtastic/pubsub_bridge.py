# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""pypubsub subscription management for one MeshtasticProvider.

* Listeners are bound methods of this object; the provider holds it strongly (pypubsub keeps only
  weak references and silently drops collected listeners).
* pypubsub is process-global, so every callback is filtered by interface identity: events from an
  old, closing interface are dropped.
* Callbacks run on library threads ('publishing', or 'stream reader' for log.line); they convert to
  domain objects immediately and never raise back into the library.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from task_mesh.domain.models import EventLevel, RadioEvent
from task_mesh.radio.base import RadioEventSink
from task_mesh.messaging.packets import parse_routing, parse_text
from task_mesh.radio.meshtastic.packets import PacketError, parse_nodeinfo, parse_packet

log = logging.getLogger(__name__)

TOPICS = (
    ("meshtastic.connection.established", "_on_established"),
    ("meshtastic.connection.lost", "_on_lost"),
    ("meshtastic.node.updated", "_on_node_updated"),
    ("meshtastic.receive", "_on_receive"),
    ("meshtastic.log.line", "_on_log_line"),
    ("meshtastic.clientNotification", "_on_client_notification"),
)


class PubSubBridge:
    def __init__(self, sink: RadioEventSink, now: Callable[[], int] = lambda: int(time.time())) -> None:
        self._sink = sink
        self._now = now
        self._lock = threading.Lock()
        self._generation: Optional[int] = None
        self._iface: Any = None
        self._pending = False  # accept events before the constructor returns the interface
        self._subscribed = False
        self.counters = {"packets": 0, "bad_packets": 0, "log_lines": 0, "stale_dropped": 0}

    # --- lifecycle -------------------------------------------------------------------------
    def subscribe(self) -> None:
        from pubsub import pub

        if self._subscribed:
            return
        for topic, name in TOPICS:
            pub.subscribe(getattr(self, name), topic)
        self._subscribed = True

    def unsubscribe(self) -> None:
        from pubsub import pub

        if not self._subscribed:
            return
        for topic, name in TOPICS:
            try:
                pub.unsubscribe(getattr(self, name), topic)
            except Exception:  # noqa: BLE001
                pass
        self._subscribed = False

    def begin(self, generation: int) -> None:
        with self._lock:
            self._generation, self._iface, self._pending = generation, None, True

    def attach(self, iface: Any) -> None:
        with self._lock:
            self._iface, self._pending = iface, False

    def detach(self) -> None:
        with self._lock:
            self._generation, self._iface, self._pending = None, None, False

    # --- filtering -------------------------------------------------------------------------
    def _accept(self, interface: Any) -> Optional[int]:
        with self._lock:
            gen = self._generation
            if gen is None:
                ok = False
            elif self._pending:
                ok = True
            else:
                ok = interface is self._iface
        if not ok:
            self.counters["stale_dropped"] += 1
            return None
        return gen

    # --- callbacks (library threads) -------------------------------------------------------
    def _on_established(self, interface: Any = None) -> None:
        gen = self._accept(interface)
        if gen is not None:
            self._sink.on_established(gen)

    def _on_lost(self, interface: Any = None) -> None:
        gen = self._accept(interface)
        if gen is not None:
            self._sink.on_lost(gen)

    def _on_node_updated(self, node: Any = None, interface: Any = None) -> None:
        gen = self._accept(interface)
        if gen is None:
            return
        try:
            info = parse_nodeinfo(dict(node) if isinstance(node, dict) else node)
        except (PacketError, Exception) as exc:  # noqa: BLE001
            self._bad(gen, "nodeinfo", exc)
            return
        self._sink.on_nodeinfo(gen, info)

    def _on_receive(self, packet: Any = None, interface: Any = None) -> None:
        gen = self._accept(interface)
        if gen is None:
            return
        self.counters["packets"] += 1
        try:
            obs = parse_packet(packet, self._now())
        except (PacketError, Exception) as exc:  # noqa: BLE001
            self._bad(gen, "packet", exc)
            return
        self._sink.on_observation(gen, obs)
        try:
            text = parse_text(packet)
            routing = None if text else parse_routing(packet)
        except Exception as exc:  # noqa: BLE001
            self._bad(gen, "message", exc)
            return
        if text is not None and hasattr(self._sink, "on_text"):
            self._sink.on_text(gen, text)
        elif routing is not None and hasattr(self._sink, "on_routing"):
            self._sink.on_routing(gen, routing)

    def _on_log_line(self, line: Any = None, interface: Any = None) -> None:
        # Device log lines are counted but not stored or logged (may contain configuration).
        if self._accept(interface) is not None:
            self.counters["log_lines"] += 1

    def _on_client_notification(self, notification: Any = None, interface: Any = None) -> None:
        gen = self._accept(interface)
        if gen is None:
            return
        msg = getattr(notification, "message", None)
        text = msg if isinstance(msg, str) and msg else "client notification from radio"
        self._sink.on_radio_event(gen, RadioEvent(self._now(), EventLevel.NOTICE, "client_notification", text[:200]))

    def _bad(self, gen: int, what: str, exc: BaseException) -> None:
        self.counters["bad_packets"] += 1
        # Never include packet contents: they may carry key material.
        log.warning("discarded malformed %s (%s)", what, type(exc).__name__,
                    extra={"event": "radio.bad_packet", "err_type": type(exc).__name__})
        self._sink.on_radio_event(
            gen, RadioEvent(self._now(), EventLevel.WARNING, "bad_packet", f"discarded malformed {what}",
                            {"error": type(exc).__name__})
        )
