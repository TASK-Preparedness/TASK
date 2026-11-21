# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Protocol v2 request path (PHASE-2.md section 5). The v1 path in api.py is untouched.

Role resolution: no session -> public; a valid session -> its role; anything
else -> unauthenticated. [peers] is never consulted here (section 5.4).
"""

import logging

from task_core import __version__
from task_core.devices import LOGICAL
from task_core.errors import ApiError, PersistError
from task_core.public_view import ROLE_RANK, filter_events, redact_module_list

logger = logging.getLogger("task_core")

ENVELOPE_KEYS = frozenset({"v", "id", "method", "params", "session"})

V2_METHODS = {
    "core.protocol": "public",
    "core.health": "public",
    "module.list": "public",
    "capability.list": "public",
    "device.counts": "public",
    "device.list": "operator",
    "device.get": "operator",
    "device.assign": "administrator",
    "device.unassign": "administrator",
    "events.recent": "operator",
    "events.since": "public",
    "events.subscribe": "public",
    "session.login": "public",
    "session.logout": "public",
    "session.whoami": "public",
}

# Every v2 method that changes configuration or state (D5 rule: administrator).
STATE_CHANGING = frozenset({"device.assign", "device.unassign"})


def ok(req_id, result: dict) -> dict:
    return {"v": 2, "id": req_id, "ok": True, "result": result}


def fail(req_id, code: str, message: str) -> dict:
    return {"v": 2, "id": req_id, "ok": False, "error": {"code": code, "message": message}}


def is_v2(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    version = payload.get("v")
    return type(version) is int and version == 2


class V2Handler:
    def __init__(self, core) -> None:
        self.core = core

    def handle(self, payload: dict, uid: int):
        """Return (response, subscriber-or-None)."""
        req_id = payload.get("id") if isinstance(payload.get("id"), str) else None
        if req_id is None:
            return fail(None, "bad-request", "missing id"), None
        if set(payload) - ENVELOPE_KEYS:
            return fail(req_id, "bad-request", "unknown envelope key"), None
        method = payload.get("method")
        if not isinstance(method, str):
            return fail(req_id, "bad-request", "missing method"), None
        params = payload.get("params", {})
        if not isinstance(params, dict):
            return fail(req_id, "bad-request", "invalid params"), None
        stream = []
        try:
            result = self._dispatch(method, params, payload, uid, stream)
        except ApiError as exc:
            return fail(req_id, exc.code, exc.message), None
        except PersistError:
            logger.error("persist failed")
            return fail(req_id, "internal-error", "internal error"), None
        except Exception:
            logger.error("internal error method=%s", method)
            return fail(req_id, "internal-error", "internal error"), None
        if not isinstance(result, dict):
            logger.error("internal error method=%s", method)
            return fail(req_id, "internal-error", "internal error"), None
        return ok(req_id, result), (stream[0] if stream else None)

    def _dispatch(self, method, params, payload, uid, stream):
        sessions = self.core.sessions
        session = None
        role = "public"
        if "session" in payload:
            session = sessions.resolve(payload["session"], uid, touch=True)
            role = session.role
        if method.startswith("medical.patients.") or method not in V2_METHODS:
            raise ApiError("not-found", "unknown method")
        minimum = V2_METHODS[method]
        if ROLE_RANK[role] < ROLE_RANK[minimum]:
            raise ApiError("forbidden", f"{method} requires {minimum}")
        core = self.core
        if method == "core.protocol":
            return {"versions": [1, 2], "core": __version__, "boot_id": core.bus.boot_id}
        if method == "module.list":
            result = core.call("module.list", {})
            return result if role != "public" else redact_module_list(result)
        if method == "core.health":
            # v2 only: the v1 core.health result is unchanged (Phase 1 wire format).
            return dict(core.call(method, params), hotplug=core.hotplug_status())
        if method in ("capability.list", "device.list", "device.get"):
            return core.call(method, params)
        if method == "device.counts":
            return core.devices.counts()
        if method == "device.assign":
            return self._assign(params)
        if method == "device.unassign":
            return core.call("device.unassign", params)
        if method == "events.recent":
            return {"events": filter_events(role, core.bus.recent_v2())}
        if method == "events.since":
            return self._since(params, role)
        if method == "events.subscribe":
            return self._subscribe(params, role, session, stream)
        if method == "session.login":
            return sessions.login(uid, params.get("username"), params.get("secret"))
        if method == "session.logout":
            if session is None:
                raise ApiError("unauthenticated", "session invalid")
            return sessions.logout(session)
        if method == "session.whoami":
            if session is None:
                return {"role": "public"}
            return sessions.info(session)
        raise ApiError("not-found", "unknown method")

    def _assign(self, params: dict) -> dict:
        logical = params.get("logical")
        device_id = params.get("device_id")
        if not isinstance(logical, str) or logical not in LOGICAL:
            raise ApiError("invalid-logical-device", "invalid logical device")
        if not isinstance(device_id, str):
            raise ApiError("unknown-device", "unknown device")
        alias = params.get("alias", None)
        if alias is not None and not isinstance(alias, str):
            raise ApiError("bad-request", "invalid alias")
        confirm = params.get("confirm_displace", False)
        if not isinstance(confirm, bool):
            raise ApiError("bad-request", "invalid confirm_displace")
        try:
            return self.core.devices.assign(logical, device_id, alias, v2=True, confirm_displace=confirm)
        except PersistError:
            raise ApiError("internal-error", "internal error") from None

    def _since(self, params: dict, role: str) -> dict:
        seq = params.get("seq")
        boot_id = params.get("boot_id")
        if type(seq) is not int or seq < 0:
            raise ApiError("bad-request", "invalid seq")
        if not isinstance(boot_id, str):
            raise ApiError("bad-request", "invalid boot_id")
        bus = self.core.bus
        ring = bus.recent_v2()
        last = bus.last_seq()
        if boot_id != bus.boot_id:
            return {"boot_id": bus.boot_id, "seq": last, "gap": True, "events": filter_events(role, ring)}
        gap = bool(ring) and seq < ring[0]["seq"] - 1
        events = [event for event in ring if event["seq"] > seq]
        return {"boot_id": bus.boot_id, "seq": last, "gap": gap, "events": filter_events(role, events)}

    def _subscribe(self, params: dict, role: str, session, stream: list) -> dict:
        topics = params.get("topics", [])
        if not isinstance(topics, list) or not all(isinstance(item, str) for item in topics):
            raise ApiError("bad-request", "invalid topics")
        opened = self.core.streams.open(role, topics, session)
        if opened is None:
            raise ApiError("busy", "too many streams")
        subscriber, seq = opened
        stream.append(subscriber)
        return {"boot_id": self.core.bus.boot_id, "seq": seq, "topics": list(topics), "role": role}
