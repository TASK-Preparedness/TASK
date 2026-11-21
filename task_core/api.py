# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Newline-delimited JSON over a Unix socket. Not HTTP, TCP, or WebSockets."""

import json
import logging
import os
import socket
import struct
import threading

from task_core.errors import ApiError, PersistError
from task_core.protocol_v2 import is_v2

logger = logging.getLogger("task_core")

MAX_REQUEST = 65536
MAX_RESPONSE = 262144
MAX_CLIENTS = 8
IDLE_TIMEOUT = 30
WRITE_TIMEOUT_JOIN = 6

METHODS = {
    "core.health": "public",
    "module.list": "public",
    "device.list": "operator",
    "device.get": "operator",
    "device.assign": "administrator",
    "device.unassign": "administrator",
    "capability.list": "public",
    "events.recent": "operator",
}


def peer_uid(conn: socket.socket) -> int:
    size = struct.calcsize("3i")
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


def ok(req_id, result: dict) -> dict:
    return {"v": 1, "id": req_id, "ok": True, "result": result}


def fail(req_id, code: str, message: str) -> dict:
    return {
        "v": 1,
        "id": req_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }


class Server:
    def __init__(self, core, idle_timeout: float = IDLE_TIMEOUT, peer_uid_fn=None, extra_methods=None) -> None:
        self.core = core
        self.idle_timeout = idle_timeout
        self.peer_uid_fn = peer_uid_fn or peer_uid
        self.extra_methods = extra_methods or {}
        self._listen = None
        self._thread = None
        self._stopping = False
        self._ready = threading.Event()
        self._client_lock = threading.Lock()
        self._nclients = 0
        self._released: set = set()
        self._client_threads: list[threading.Thread] = []

    def start(self, path: str) -> None:
        parent = os.path.dirname(path)
        os.makedirs(parent, mode=0o755, exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)
        listen = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listen.bind(path)
        os.chmod(path, 0o660)
        _try_group(path)
        listen.listen(16)
        listen.settimeout(0.2)
        self._listen = listen
        self._thread = threading.Thread(target=self._accept_loop, name="task-accept", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=3):
            raise ApiError("internal-error", "internal error")

    def stop(self) -> None:
        self._stopping = True
        listen = self._listen
        if listen is not None:
            try:
                listen.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def handle_line(self, line: bytes, uid: int) -> dict:
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return fail(None, "bad-request", "invalid json")
        if not isinstance(payload, dict):
            return fail(None, "bad-request", "request must be a json object")
        if "id" not in payload or not isinstance(payload.get("id"), str):
            return fail(None, "bad-request", "missing id")
        req_id = payload["id"]
        if payload.get("v") != 1:
            return fail(req_id, "bad-request", "unsupported version")
        method = payload.get("method")
        if not isinstance(method, str):
            return fail(req_id, "bad-request", "missing method")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            return fail(req_id, "bad-request", "invalid params")
        # auth is ignored on purpose. It must not change the role or be logged.
        try:
            result = self._dispatch(method, params, uid)
        except ApiError as exc:
            return fail(req_id, exc.code, exc.message)
        except PersistError:
            logger.error("persist failed")
            return fail(req_id, "internal-error", "internal error")
        except Exception:
            logger.error("internal error method=%s", method)
            return fail(req_id, "internal-error", "internal error")
        if not isinstance(result, dict):
            logger.error("internal error method=%s", method)
            return fail(req_id, "internal-error", "internal error")
        return ok(req_id, result)

    def _dispatch(self, method: str, params: dict, uid: int) -> dict:
        if method.startswith("medical.patients."):
            raise ApiError("not-found", "unknown method")
        if method in METHODS:
            minimum = METHODS[method]
            if not self.core.auth.allows(uid, minimum):
                raise ApiError("forbidden", f"{method} requires {minimum}")
            return self.core.call(method, params)
        extra = self.extra_methods.get(method)
        if extra is not None:
            minimum, function = extra
            if not self.core.auth.allows(uid, minimum):
                raise ApiError("forbidden", f"{method} requires {minimum}")
            return function(params)
        raise ApiError("not-found", "unknown method")

    def _accept_loop(self) -> None:
        self._ready.set()
        while not self._stopping:
            try:
                conn, _addr = self._listen.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._client_lock:
                if self._nclients >= MAX_CLIENTS:
                    try:
                        conn.close()
                    except OSError:
                        pass
                    continue
                self._nclients += 1
            thread = threading.Thread(
                target=self._serve_client, args=(conn,), name="task-client", daemon=True
            )
            self._client_threads.append(thread)
            thread.start()

    def _serve_client(self, conn: socket.socket) -> None:
        try:
            self._client_loop(conn)
        except Exception:
            logger.error("internal error source=client")
        finally:
            try:
                conn.close()
            except OSError:
                pass
            if id(conn) in self._released:
                self._released.discard(id(conn))
            else:
                with self._client_lock:
                    self._nclients -= 1

    def _client_loop(self, conn: socket.socket) -> None:
        try:
            uid = self.peer_uid_fn(conn)
        except Exception:
            logger.warning("peer credential unavailable")
            uid = -1
        conn.settimeout(self.idle_timeout)
        buffer = b""
        while not self._stopping:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                return
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            if len(buffer) > MAX_REQUEST:
                self._send(conn, fail(None, "bad-request", "request too large"))
                return
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if len(line) + 1 > MAX_REQUEST:
                    self._send(conn, fail(None, "bad-request", "request too large"))
                    return
                v2_payload = _v2_payload(line)
                if v2_payload is not None:
                    response, subscriber = self.core.handle_v2(v2_payload, uid)
                    if subscriber is None:
                        self._send(conn, response)
                    else:
                        self._become_stream(conn, response, subscriber, buffer)
                        return
                else:
                    self._send(conn, self.handle_line(line, uid))
                if len(buffer) > MAX_REQUEST:
                    self._send(conn, fail(None, "bad-request", "request too large"))
                    return

    def _send(self, conn: socket.socket, payload: dict) -> bool:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE:
            failure = fail(payload.get("id"), "internal-error", "internal error")
            failure["v"] = payload.get("v", 1)
            encoded = json.dumps(failure, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            conn.sendall(encoded)
        except OSError:
            return False
        return True

    def _become_stream(self, conn: socket.socket, response: dict, subscriber, buffer: bytes) -> None:
        """v2 events.subscribe succeeded: the connection is a stream from now on (section 5.8).

        It releases its RPC slot, is exempt from the idle timeout, and anything the
        client sends afterwards closes it.
        """
        with self._client_lock:
            self._nclients -= 1
        self._released.add(id(conn))
        conn.settimeout(subscriber.hub.write_timeout)
        if not self._send(conn, response) or buffer:
            subscriber.close()
            return
        subscriber.start(conn)
        while not subscriber.closed:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            break  # EOF or any client data ends the stream
        subscriber.close()
        subscriber.join(timeout=WRITE_TIMEOUT_JOIN)


def _v2_payload(line: bytes):
    """Return the parsed request if it is protocol v2 (an int "v" equal to 2), else None.

    Everything else goes to the unchanged v1 path, which parses the line itself.
    """
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return payload if is_v2(payload) else None


def _try_group(path: str) -> None:
    try:
        import grp

        gid = grp.getgrnam("rain-core").gr_gid
        os.chown(path, -1, gid)
    except KeyError:
        logger.warning("group rain-core does not exist; socket group unchanged")
    except OSError:
        logger.warning("could not set socket group rain-core")
