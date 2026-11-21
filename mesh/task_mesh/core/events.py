# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Tiny typed, thread-safe, Qt-free in-process event bus.

Handlers are held strongly (unlike pypubsub) and one failing handler never affects others.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, DefaultDict, List, Type

log = logging.getLogger(__name__)
Handler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: DefaultDict[type, List[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[Any], handler: Handler) -> None:
        with self._lock:
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: Type[Any], handler: Handler) -> None:
        with self._lock:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

    def publish(self, event: Any) -> int:
        """Deliver to handlers of the event's type and its base classes. Returns handlers run."""
        with self._lock:
            handlers: list[Handler] = []
            for cls in type(event).__mro__:
                handlers.extend(self._handlers.get(cls, ()))
        count = 0
        for h in handlers:
            try:
                h(event)
                count += 1
            except Exception:  # noqa: BLE001 - isolation is the point
                log.exception("event handler failed", extra={"event": "bus.handler_error"})
        return count
