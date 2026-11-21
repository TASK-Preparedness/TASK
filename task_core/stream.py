# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""v2 event streams (PHASE-2.md section 5.8).

Bus.publish only enqueues (never blocks on a socket). Each stream has a bounded
queue and its own sender thread.
"""

import json
import logging
import socket
import threading
import time
from collections import deque
from datetime import datetime, timezone

from task_core.public_view import event_allowed

logger = logging.getLogger("task_core")

MAX_STREAMS = 4
QUEUE_LIMIT = 256
HEARTBEAT_INTERVAL = 10.0
WRITE_TIMEOUT = 5.0
CHECK_INTERVAL = 1.0


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode(frame: dict) -> bytes:
    return json.dumps(frame, separators=(",", ":")).encode("utf-8") + b"\n"


class Subscriber:
    def __init__(self, hub, role, topics, session) -> None:
        self.hub = hub
        self.role = role
        self.topics = list(topics)
        self.session = session
        self.conn = None
        self._cond = threading.Condition()
        self._queue: deque = deque()
        self._overflow = False
        self._end_reason = None
        self._closed = False
        self.seen_seq = 0
        self.sent_frames = 0
        self._thread = None

    # called by Bus.publish under the bus lock: must not block
    def offer(self, event: dict) -> None:
        with self._cond:
            if self._closed or self._overflow or self._end_reason is not None:
                return
            self.seen_seq = event["seq"]
            if not event_allowed(self.role, event["topic"]):
                return
            if self.topics and not any(event["topic"].startswith(prefix) for prefix in self.topics):
                return
            if len(self._queue) >= QUEUE_LIMIT:
                self._overflow = True
            else:
                self._queue.append(event)
            self._cond.notify()

    def end(self, reason: str) -> None:
        with self._cond:
            if self._end_reason is None:
                self._end_reason = reason
            self._cond.notify()

    def on_session_end(self, _why: str) -> None:
        self.end("session-ended")

    def start(self, conn: socket.socket) -> None:
        self.conn = conn
        thread = threading.Thread(target=self._sender, name="task-stream", daemon=True)
        thread.start()
        self._thread = thread

    def _sender(self) -> None:
        last_frame = time.monotonic()
        last_check = time.monotonic()
        try:
            while True:
                final = None
                with self._cond:
                    while not self._queue and not self._overflow and self._end_reason is None and not self._closed:
                        now = time.monotonic()
                        wait = min(
                            self.hub.heartbeat_interval - (now - last_frame),
                            self.hub.check_interval - (now - last_check),
                        )
                        if wait <= 0:
                            break
                        self._cond.wait(timeout=wait)
                    if self._closed:
                        return
                    if self._overflow or self._end_reason == "session-ended":
                        reason = "overflow" if self._overflow else "session-ended"
                        self._queue.clear()
                        batch = []
                        final = {"v": 2, "stream_end": {"reason": reason, "seq": self.seen_seq}}
                    else:
                        batch = list(self._queue)
                        self._queue.clear()
                        if self._end_reason is not None:
                            final = {"v": 2, "stream_end": {"reason": self._end_reason, "seq": self.seen_seq}}
                    seen = self.seen_seq
                # writes happen outside the lock, so publish never waits on a socket
                if batch:
                    # one write per batch keeps GIL and syscall churn low during bursts
                    if not self._write_many([{"v": 2, "event": event} for event in batch]):
                        return
                    last_frame = time.monotonic()
                if final is not None:
                    self._write(final)
                    return
                now = time.monotonic()
                if now - last_check >= self.hub.check_interval:
                    last_check = now
                    if self.session is not None and not self.hub.sessions.check(self.session):
                        self.end("session-ended")
                        continue
                if not batch and now - last_frame >= self.hub.heartbeat_interval:
                    if not self._write({"v": 2, "heartbeat": {"seq": seen, "time": _now_text()}}):
                        return
                    last_frame = time.monotonic()
        except Exception:
            logger.error("internal error source=stream")
        finally:
            self.close()

    def _write(self, frame: dict) -> bool:
        return self._write_many([frame])

    def _write_many(self, frames: list) -> bool:
        try:
            self.conn.sendall(b"".join(_encode(frame) for frame in frames))
            self.sent_frames += len(frames)
            return True
        except socket.timeout:
            logger.warning("stream closed: blocked write")
            return False
        except OSError:
            return False

    def close(self) -> None:
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._cond.notify()
        self.hub.release(self)
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass

    @property
    def closed(self) -> bool:
        return self._closed

    def join(self, timeout: float) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)


class StreamHub:
    def __init__(self, bus, sessions, heartbeat_interval=None, write_timeout=None, check_interval=None,
                 max_streams=MAX_STREAMS) -> None:
        self.bus = bus
        self.sessions = sessions
        self.heartbeat_interval = heartbeat_interval or HEARTBEAT_INTERVAL
        self.write_timeout = write_timeout or WRITE_TIMEOUT
        self.check_interval = check_interval or CHECK_INTERVAL
        self.max_streams = max_streams
        self._lock = threading.Lock()
        self._streams: list = []
        self._stopping = False

    def open(self, role, topics, session):
        """Reserve a slot and attach to the bus. Returns (subscriber, seq) or None if busy."""
        with self._lock:
            if self._stopping or len(self._streams) >= self.max_streams:
                return None
            subscriber = Subscriber(self, role, topics, session)
            self._streams.append(subscriber)
        seq = self.bus.snapshot_and_listen(subscriber.offer)
        subscriber.seen_seq = seq
        if session is not None:
            self.sessions.add_end_hook(session, subscriber.on_session_end)
        return subscriber, seq

    def release(self, subscriber) -> None:
        self.bus.remove_listener(subscriber.offer)
        if subscriber.session is not None:
            self.sessions.remove_end_hook(subscriber.session, subscriber.on_session_end)
        with self._lock:
            if subscriber in self._streams:
                self._streams.remove(subscriber)

    def active(self) -> int:
        with self._lock:
            return len(self._streams)

    def shutdown(self) -> None:
        with self._lock:
            self._stopping = True
            streams = list(self._streams)
        for subscriber in streams:
            subscriber.end("core-stopping")
        for subscriber in streams:
            subscriber.join(timeout=2)
