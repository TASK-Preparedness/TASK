# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Minimal blocking task-core v2 client for comms modules: read-only methods + own session.

Allowed methods are an explicit allow-list; device.assign/device.unassign can never be sent.
The session token lives only in memory and is never logged or written.
"""

import itertools
import json
import os
import socket

ALLOWED = frozenset({"core.protocol", "core.health", "capability.list", "device.counts", "device.list",
                     "device.get", "session.login", "session.logout", "session.whoami", "events.subscribe"})
TASK_SOCKET, LEGACY_SOCKET = "/run/task/core.sock", "/run/rain/core.sock"
ROLES = {"public": 0, "operator": 1, "administrator": 2}


def resolve_socket(explicit=None, environ=None, exists=os.path.exists):
    environ = os.environ if environ is None else environ
    if explicit:
        return explicit
    if environ.get("TASK_CORE_SOCKET"):
        return environ["TASK_CORE_SOCKET"]
    for c in (TASK_SOCKET, LEGACY_SOCKET):
        if exists(c):
            return c
    return TASK_SOCKET


class CoreError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class CoreClient:
    def __init__(self, path=None, timeout=3.0):
        self.path = resolve_socket(path)
        self.timeout = timeout
        self._ids = itertools.count(1)
        self.token = None
        self.username = None
        self.role = None

    def __repr__(self):
        return f"<CoreClient {self.path} user={self.username} role={self.role}>"  # never the token

    def call(self, method, params=None, session=True):
        if method not in ALLOWED:
            raise CoreError("not-allowed", f"{method} is not permitted from a comms module")
        body = {"v": 2, "id": f"m{next(self._ids)}", "method": method, "params": dict(params or {})}
        if session and self.token:
            body["session"] = self.token
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.path)
            s.sendall(json.dumps(body).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    raise CoreError("eof", "task-core closed the connection")
                buf += chunk
        except OSError as exc:
            raise CoreError("unreachable", exc.strerror or str(exc)) from None
        finally:
            s.close()
        reply = json.loads(buf.split(b"\n", 1)[0])
        if not reply.get("ok"):
            err = reply.get("error") or {}
            raise CoreError(err.get("code", "error"), err.get("message", ""))
        return reply.get("result")

    def login(self, username, secret):
        res = self.call("session.login", {"username": username, "secret": secret}, session=False)
        self.token, self.username, self.role = res["session"], res["username"], res["role"]
        return {k: v for k, v in res.items() if k != "session"}

    def logout(self):
        if self.token:
            try:
                self.call("session.logout")
            except CoreError:
                pass
        self.token = self.username = self.role = None

    def has_role(self, needed):
        return self.role is not None and ROLES.get(self.role, -1) >= ROLES[needed]

    def assignment(self, role_name):
        """{device_id, alias, connected} assigned to a logical role (e.g. 'mesh.primary'), or None.
        Read-only: device.list result "assignments" (task_core/devices.py list_public)."""
        res = self.call("device.list") or {}
        entry = (res.get("assignments") or {}).get(role_name)
        if not entry:
            return None
        dev = next((d for d in res.get("devices", []) if d.get("id") == entry.get("device_id")), None)
        return dict(entry, device=dev)
