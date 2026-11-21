# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Asynchronous task-core client on the GUI event loop (PHASE-2.md sections 3, 5, 9).

QLocalSocket only, never a blocking call. Two connections:

* the RPC connection carries v2 requests (and the session token, held in memory only);
* the stream connection carries one ``events.subscribe`` and then pushed frames.

The client speaks protocol v2 only. A 0.1.x core answers the v2 probe with a v1
``unsupported version`` error, which the controller treats as "core too old".
"""

import itertools
import json
import logging
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

logger = logging.getLogger("task_console")

DEFAULT_SOCKET = "/run/task/core.sock"

def resolve_socket(explicit=None, environ=None, exists=None) -> str:
    """Phase 4C fallback: --socket, $TASK_CORE_SOCKET, /run/task/core.sock, legacy /run/rain/core.sock."""
    import os
    environ = os.environ if environ is None else environ
    exists = os.path.exists if exists is None else exists
    if explicit:
        return explicit
    if environ.get("TASK_CORE_SOCKET"):
        return environ["TASK_CORE_SOCKET"]
    for candidate in ("/run/task/core.sock", "/run/rain/core.sock"):
        if exists(candidate):
            return candidate
    return "/run/task/core.sock"

MAX_LINE = 1 << 20  # task-core's response limit is 262144 bytes; anything far larger is a broken peer
REQUEST_TIMEOUT_MS = 10000
LOGOUT_TIMEOUT_MS = 3000
HEARTBEAT_DEAD_MS = 25000


def transport_error(reason: str) -> dict:
    """A synthesized reply for a request that never got an answer from task-core."""
    return {"ok": False, "error": {"code": "unavailable", "message": "task-core unavailable"}, "transport": reason}


class LineSocket(QObject):
    """One QLocalSocket speaking newline-delimited JSON."""

    opened = Signal()
    line = Signal(object)
    closed = Signal(str)  # eof | not-found | refused | access | error | overlong

    _ERRORS = {
        QLocalSocket.LocalSocketError.ServerNotFoundError: "not-found",
        QLocalSocket.LocalSocketError.ConnectionRefusedError: "refused",
        QLocalSocket.LocalSocketError.SocketAccessError: "access",
        QLocalSocket.LocalSocketError.PeerClosedError: "eof",
    }

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self._sock = QLocalSocket(self)
        self._buf = bytearray()
        self._done = False
        self._open = False
        self._sock.connected.connect(self._on_connected)
        self._sock.readyRead.connect(self._on_ready)
        self._sock.disconnected.connect(self._on_disconnected)
        self._sock.errorOccurred.connect(self._on_error)

    @property
    def is_open(self) -> bool:
        return self._open and not self._done

    def open(self) -> None:
        self._sock.connectToServer(self.path)

    def send(self, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        self._sock.write(data)
        self._sock.flush()

    def abort(self) -> None:
        """Close without emitting ``closed`` (a deliberate, client-side close)."""
        self._done = True
        self._open = False
        try:
            self._sock.abort()
        except RuntimeError:
            pass
        self.deleteLater()

    def _finish(self, reason: str) -> None:
        if self._done:
            return
        self._done = True
        self._open = False
        self.closed.emit(reason)
        try:
            self._sock.abort()
        except RuntimeError:
            pass
        self.deleteLater()

    def _on_connected(self) -> None:
        if self._done:
            return
        self._open = True
        self.opened.emit()

    def _on_ready(self) -> None:
        if self._done:
            return
        self._buf += bytes(self._sock.readAll())
        while not self._done:
            index = self._buf.find(b"\n")
            if index < 0:
                if len(self._buf) > MAX_LINE:
                    self._finish("overlong")
                return
            raw = bytes(self._buf[:index])
            del self._buf[: index + 1]
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                message = None
            self.line.emit(message)

    def _on_disconnected(self) -> None:
        if self._sock.bytesAvailable():
            self._on_ready()
        self._finish("eof")

    def _on_error(self, error) -> None:
        if error == QLocalSocket.LocalSocketError.PeerClosedError and self._sock.bytesAvailable():
            self._on_ready()
        self._finish(self._ERRORS.get(error, "error"))


class _Pending:
    __slots__ = ("method", "callback", "generation", "timer", "durable")

    def __init__(self, method, callback, generation, timer, durable):
        self.method = method
        self.callback = callback
        self.generation = generation
        self.timer = timer
        self.durable = durable


class CoreClient(QObject):
    """v2 requests and the event stream. Holds the session token in memory only."""

    streamOpened = Signal(dict)
    streamEvent = Signal(dict)
    streamHeartbeat = Signal(dict)
    streamEnded = Signal(str)  # overflow | session-ended | core-stopping | eof | heartbeat-timeout | error:<code> | ...

    def __init__(self, socket_path: str = DEFAULT_SOCKET, parent=None, heartbeat_dead_ms: int = HEARTBEAT_DEAD_MS,
                 request_timeout_ms: int = REQUEST_TIMEOUT_MS) -> None:
        super().__init__(parent)
        self.socket_path = socket_path
        self.heartbeat_dead_ms = heartbeat_dead_ms
        self.request_timeout_ms = request_timeout_ms
        self._token = None
        self._generation = 0
        self._ids = itertools.count(1)
        self._rpc = None
        self._queue = []
        self._pending = {}
        self._stream = None
        self._stream_answered = False
        self._stream_end_reason = None
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)
        # (method, carried a session) for diagnostics and tests; never written anywhere
        self.sent = deque(maxlen=4000)

    # ---------------------------------------------------------------- token (memory only)

    @property
    def has_token(self) -> bool:
        return self._token is not None

    def set_token(self, token: str) -> None:
        self._token = token

    def take_token(self):
        """Remove the token so no later request can carry it; return it once."""
        token, self._token = self._token, None
        return token

    def invalidate_pending(self) -> None:
        """Responses to requests sent before this call are discarded without a callback."""
        self._generation += 1

    # ---------------------------------------------------------------- RPC

    def request(self, method: str, params=None, callback=None, *, timeout_ms=None, session=True, token=None,
                durable=False) -> str:
        """Send one v2 request. ``durable`` callbacks survive invalidate_pending (sessionless probes only)."""
        request_id = f"c{next(self._ids)}"
        body = {"v": 2, "id": request_id, "method": method, "params": dict(params or {})}
        carried = token if token is not None else (self._token if session else None)
        if carried is not None:
            body["session"] = carried
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._resolve(request_id, transport_error("timeout")))
        self._pending[request_id] = _Pending(method, callback, self._generation, timer, durable and carried is None)
        timer.start(timeout_ms or self.request_timeout_ms)
        self.sent.append((method, carried is not None))
        if self._rpc is not None and self._rpc.is_open:
            self._rpc.send(body)
        else:
            self._queue.append(body)
            if self._rpc is None:
                self._connect_rpc()
        return request_id

    def reset_rpc(self) -> None:
        """Drop the RPC connection; requests in flight resolve as transport errors."""
        rpc, self._rpc = self._rpc, None
        if rpc is not None:
            rpc.abort()
        self._fail_all("reset")

    def _connect_rpc(self) -> None:
        rpc = LineSocket(self.socket_path, self)
        self._rpc = rpc
        rpc.opened.connect(lambda: self._on_rpc_open(rpc))
        rpc.line.connect(lambda message: self._on_rpc_line(rpc, message))
        rpc.closed.connect(lambda reason: self._on_rpc_closed(rpc, reason))
        rpc.open()

    def _on_rpc_open(self, rpc) -> None:
        if rpc is not self._rpc:
            return
        queue, self._queue = self._queue, []
        for body in queue:
            rpc.send(body)

    def _on_rpc_line(self, rpc, message) -> None:
        if rpc is not self._rpc or not isinstance(message, dict):
            return
        self._resolve(message.get("id"), message)

    def _on_rpc_closed(self, rpc, reason) -> None:
        if rpc is not self._rpc:
            return
        self._rpc = None
        # task-core closes idle RPC connections after 30 s; that is not a core loss
        self._fail_all(reason)

    def _fail_all(self, reason) -> None:
        self._queue = []
        for request_id in list(self._pending):
            self._resolve(request_id, transport_error(reason))

    def _resolve(self, request_id, reply) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.timer.stop()
        pending.timer.deleteLater()
        if pending.callback is None or (pending.generation != self._generation and not pending.durable):
            return
        pending.callback(reply)

    # ---------------------------------------------------------------- stream

    @property
    def stream_active(self) -> bool:
        return self._stream is not None

    def open_stream(self, topics=()) -> None:
        self.close_stream()
        stream = LineSocket(self.socket_path, self)
        self._stream = stream
        self._stream_answered = False
        self._stream_end_reason = None
        body = {"v": 2, "id": "s", "method": "events.subscribe", "params": {"topics": list(topics)}}
        if self._token is not None:
            body["session"] = self._token
        self.sent.append(("events.subscribe", self._token is not None))
        stream.opened.connect(lambda: stream.send(body) if stream is self._stream else None)
        stream.line.connect(lambda message: self._on_stream_line(stream, message))
        stream.closed.connect(lambda reason: self._on_stream_closed(stream, reason))
        self._watchdog.start(self.heartbeat_dead_ms)
        stream.open()

    def close_stream(self) -> None:
        """Client-side close; emits nothing."""
        stream, self._stream = self._stream, None
        self._watchdog.stop()
        if stream is not None:
            stream.abort()

    def _on_stream_line(self, stream, message) -> None:
        if stream is not self._stream:
            return
        self._watchdog.start(self.heartbeat_dead_ms)
        if not isinstance(message, dict):
            return
        if not self._stream_answered:
            self._stream_answered = True
            if message.get("ok") is True and isinstance(message.get("result"), dict):
                self.streamOpened.emit(message["result"])
            else:
                code = (message.get("error") or {}).get("code", "bad-reply")
                self.close_stream()
                self.streamEnded.emit(f"error:{code}")
            return
        if isinstance(message.get("event"), dict):
            self.streamEvent.emit(message["event"])
        elif isinstance(message.get("heartbeat"), dict):
            self.streamHeartbeat.emit(message["heartbeat"])
        elif isinstance(message.get("stream_end"), dict):
            self._stream_end_reason = str(message["stream_end"].get("reason", "eof"))

    def _on_stream_closed(self, stream, reason) -> None:
        if stream is not self._stream:
            return
        self._stream = None
        self._watchdog.stop()
        self.streamEnded.emit(self._stream_end_reason or reason)

    def _on_watchdog(self) -> None:
        if self._stream is None:
            return
        self.close_stream()
        self.streamEnded.emit("heartbeat-timeout")
