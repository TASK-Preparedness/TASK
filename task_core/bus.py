# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import logging
import os
import random
import secrets
import threading
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger("task_core")

RING_SIZE = 200

# Topics that exist only in protocol v2. They never enter the v1 ring, so they
# can never push Phase 1 events out of the v1 events.recent view.
V2_ONLY_TOPICS = frozenset({"device.displaced", "device.counts"})

# Event ids keep the 0.1.1 shape ("evt_" + 16 lowercase hex characters, random). They are generated from a
# per-process PRNG seeded from os.urandom instead of uuid4(): uuid4() calls os.urandom on every publish, which
# releases the GIL, and a tight publish loop that releases and immediately retakes the GIL starves the RPC
# threads (CPython hands the GIL over on its 1 ms switch interval only when no voluntary switch happened).
# Measured off-target: core.health latency during a 10 000-event burst fell from up to ~135 ms to under 5 ms
# (test 27). Event ids are identifiers, not secrets.
_ID_RNG = random.Random(os.urandom(32))


def _event_id() -> str:
    return "evt_%016x" % _ID_RNG.getrandbits(64)


class Bus:
    """In-process event bus.

    - Synchronous in-process subscribers, exactly as in 0.1.1.
    - v1 ring: the 0.1.1 ring (200 events, no v2-only topics, Phase 1 shape).
    - v2 ring: 200 events of every topic, each with a per-boot ``seq``.
    - Stream listeners: called with the v2 event under the bus lock, so they
      see events in seq order. They must not block (they only enqueue).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list = []
        self._ring: deque = deque(maxlen=RING_SIZE)
        self._ring_v2: deque = deque(maxlen=RING_SIZE)
        self._listeners: list = []
        self._seq = 0
        self.boot_id = secrets.token_hex(16)

    def subscribe(self, callback) -> None:
        with self._lock:
            self._subs.append(callback)

    def add_listener(self, callback) -> None:
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def publish(self, topic: str, source: str, data: dict | None = None) -> dict:
        event = {
            "v": 1,
            "id": _event_id(),
            "topic": topic,
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": source,
            "data": data or {},
        }
        with self._lock:
            if topic not in V2_ONLY_TOPICS:
                self._ring.append(event)
            self._seq += 1
            v2_event = dict(event)
            v2_event["seq"] = self._seq
            self._ring_v2.append(v2_event)
            for listener in list(self._listeners):
                try:
                    listener(v2_event)
                except Exception:
                    logger.error("internal error source=stream")
            subs = list(self._subs)
        for callback in subs:
            try:
                callback(event)
            except Exception:
                logger.error("internal error source=bus")
        return event

    def recent(self) -> list:
        with self._lock:
            return list(self._ring)

    def recent_v2(self) -> list:
        with self._lock:
            return list(self._ring_v2)

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def snapshot_and_listen(self, callback) -> int:
        """Register a stream listener and return the seq it starts after."""
        with self._lock:
            self._listeners.append(callback)
            return self._seq
