# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Private IPC: $XDG_RUNTIME_DIR/task/mesh.sock (0600, directory 0700), JSON lines, peer must be the same uid
(SO_PEERCRED). Requests {"id","method","params"} -> {"id","ok","result"|"error"}. method "subscribe" turns the
connection into an event stream. Session tokens passed for "send"/"auth" are never logged."""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Callable, Optional

from task_mesh.hub.locks import runtime_dir

log = logging.getLogger(__name__)
MAX_LINE = 256 * 1024


def socket_path(env=None) -> Path:
    return runtime_dir(env) / "mesh.sock"


def peer_uid(sock: socket.socket) -> int:
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", creds)[1]


class IpcServer:
    def __init__(self, handler: Callable[[str, dict], object], path: Optional[Path] = None,
                 on_close: Optional[Callable[[str], None]] = None) -> None:
        self.handler = handler
        self.on_close = on_close
        self.path = Path(path or socket_path())
        self._sock: Optional[socket.socket] = None
        self._subs: list = []             # [(conn_id, file, write_lock)]
        self._seq = 0
        self._conns: set = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def start(self) -> None:
        if self.path.exists() or self.path.is_symlink():
            self.path.unlink()           # we hold the instance lock, so a leftover socket is stale
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            s.bind(str(self.path))
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        s.listen(8)
        s.settimeout(0.5)
        self._sock = s
        threading.Thread(target=self._accept, name="mesh-ipc", daemon=True).start()

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                c, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if peer_uid(c) != os.getuid():
                log.warning("IPC peer with another uid refused", extra={"event": "mesh.ipc_refused"})
                c.close()
                continue
            threading.Thread(target=self._serve, args=(c,), name="mesh-ipc-conn", daemon=True).start()

    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)

    def _serve(self, c: socket.socket) -> None:
        with self._lock:
            self._conns.add(c)
        f = c.makefile("rwb")
        wl = threading.Lock()
        with self._lock:
            self._seq += 1
            conn_id = f"c{self._seq}"
        entry = (conn_id, f, wl)

        def reply(obj) -> None:
            with wl:
                f.write(json.dumps(obj, default=str).encode() + b"\n")
                f.flush()
        try:
            for line in f:
                if len(line) > MAX_LINE:
                    break
                try:
                    req = json.loads(line)
                    method, params, rid = req["method"], req.get("params") or {}, req.get("id")
                    if not isinstance(params, dict) or not isinstance(method, str):
                        raise TypeError
                except (ValueError, KeyError, TypeError):
                    reply({"ok": False, "error": "bad request"})
                    continue
                params = {k: v for k, v in params.items() if not str(k).startswith("_")}   # server-only keys
                params["_conn"] = conn_id
                if method == "subscribe":
                    with self._lock:
                        if entry not in self._subs:
                            self._subs.append(entry)
                    reply({"id": rid, "ok": True, "result": {"subscribed": True, "conn": conn_id}})
                    continue
                try:
                    out = {"id": rid, "ok": True, "result": self.handler(method, params)}
                except Exception as exc:  # noqa: BLE001
                    out = {"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
                reply(out)
        except OSError:
            pass
        finally:
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)
                self._conns.discard(c)
            try:
                c.close()
            except OSError:
                pass
            if self.on_close is not None:
                try:
                    self.on_close(conn_id)        # e.g. drop this window's focus lease at once
                except Exception:  # noqa: BLE001
                    log.exception("ipc close hook failed")

    def publish(self, kind: str, data: dict) -> None:
        line = json.dumps({"event": kind, "data": data}, default=str).encode() + b"\n"
        with self._lock:
            subs = list(self._subs)
        for entry in subs:
            _cid, f, wl = entry
            try:
                with wl:
                    f.write(line)
                    f.flush()
            except (OSError, ValueError):
                with self._lock:
                    if entry in self._subs:
                        self._subs.remove(entry)

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        with self._lock:
            conns = list(self._conns)
        for c in conns:                      # like a process exit: clients see EOF and reconnect later
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass


class IpcError(Exception):
    pass


class HubClient:
    """Blocking client (GUI worker thread / launcher). One short connection per call."""
    def __init__(self, path: Optional[Path] = None, timeout: float = 2.0) -> None:
        self.path = Path(path) if path else None
        self.timeout = timeout

    def _path(self) -> Path:
        return self.path or socket_path()

    def call(self, method: str, **params):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(str(self._path()))
            s.sendall(json.dumps({"id": 1, "method": method, "params": params}).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    raise IpcError("service closed the connection")
                buf += chunk
                if len(buf) > 8 * MAX_LINE:
                    raise IpcError("reply too large")
        except OSError as exc:
            raise IpcError(f"service unreachable: {exc.strerror or exc}") from None
        finally:
            s.close()
        reply = json.loads(buf.split(b"\n", 1)[0])
        if not reply.get("ok"):
            raise IpcError(reply.get("error", "error"))
        return reply.get("result")

    def available(self) -> bool:
        try:
            return bool(self.call("ping").get("pong"))
        except (IpcError, ValueError, AttributeError):
            return False


class HubSubscriber:
    """Live event stream from the service (GUI side). One persistent connection per window: it carries the
    subscription and this window's focus lease, so closing/crashing the window drops the lease immediately.
    Reconnects with bounded backoff (service restarts). Callback runs on the reader thread."""

    BACKOFF = (0.5, 1, 2, 5, 5)

    def __init__(self, on_event: Callable[[str, dict], None], path: Optional[Path] = None) -> None:
        self.on_event = on_event
        self.path = path
        self._sock: Optional[socket.socket] = None
        self._wlock = threading.Lock()
        self._stop = threading.Event()
        self.connected = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_focus: Optional[dict] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="mesh-ipc-sub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        s = self._sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        if self._thread is not None:
            self._thread.join(3)

    def _send(self, obj: dict) -> bool:
        s = self._sock
        if s is None or not self.connected.is_set():
            return False
        try:
            with self._wlock:
                s.sendall(json.dumps(obj).encode() + b"\n")
            return True
        except OSError:
            return False

    def focus(self, focused: bool, ttl: float = 15.0) -> bool:
        self._last_focus = {"focused": bool(focused), "ttl": float(ttl)}
        return self._send({"id": 0, "method": "focus", "params": self._last_focus})

    def _run(self) -> None:
        tries = 0
        while not self._stop.is_set():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(str(self.path or socket_path()))
                s.sendall(b'{"id": 1, "method": "subscribe", "params": {}}\n')
                self._sock = s
                f = s.makefile("rb")
                self.connected.set()
                tries = 0
                if self._last_focus is not None:
                    self._send({"id": 0, "method": "focus", "params": self._last_focus})
                self.on_event("_connected", {})
                for line in f:
                    if len(line) > MAX_LINE:
                        break
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and "event" in msg:
                        self.on_event(str(msg["event"]), msg.get("data") or {})
            except OSError:
                pass
            finally:
                was = self.connected.is_set()
                self.connected.clear()
                self._sock = None
                s.close()
                if was and not self._stop.is_set():
                    self.on_event("_disconnected", {})
            self._stop.wait(self.BACKOFF[min(tries, len(self.BACKOFF) - 1)])
            tries += 1
