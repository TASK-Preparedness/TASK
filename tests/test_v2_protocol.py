# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 3, 6, 8-12, 16, 18 and 23: the v2 envelope, roles and sessions."""

import json
import os
import re

import task_core
from task_core.protocol_v2 import STATE_CHANGING, V2_METHODS

from conftest import LineClient
from p2fixtures import (CP2102_ID, DRAGON_PW, OP_PW, SDR_ID, UBLOX_ID, V2Client, login,  # noqa: F401
                        p2env)


def test_03_v1_ignores_session_and_auth(p2env):
    core = p2env()
    client = LineClient(core.config.socket)
    plain = client.request("device.list")
    token = login(core)
    for extra in ({"session": token}, {"session": "garbage"}, {"auth": {"token": token}}):
        body = {"v": 1, "id": "1", "method": "device.list", "params": {}}
        body.update(extra)
        client.send_raw(json.dumps(body).encode() + b"\n")
        assert client.read_json() == plain
    client.close()
    # [peers] still grants roles in v1; a uid outside [peers] is public in v1
    other = p2env(peers={os.geteuid() + 1: "administrator"})
    public = LineClient(other.config.socket)
    assert public.request("device.list")["error"]["code"] == "forbidden"
    public.close()


def test_06_no_sessions_toml_forbids_login_only(p2env):
    core = p2env(sessions_file=False)
    client = V2Client(core.config.socket)
    reply = client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})
    assert reply["error"] == {"code": "forbidden", "message": "session.login not allowed for this client"}
    assert client.call("core.health")["ok"] is True
    v1 = LineClient(core.config.socket)
    assert v1.request("device.list")["ok"] is True
    assert v1.request("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID})["ok"] is True
    v1.close()
    client.close()


def test_08_core_protocol_and_versions(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    reply = client.call("core.protocol", {})
    assert reply["v"] == 2 and reply["ok"] is True
    assert reply["result"]["versions"] == [1, 2]
    assert reply["result"]["core"] == task_core.__version__
    assert re.fullmatch(r"[0-9a-f]{32}", reply["result"]["boot_id"])
    for raw in (b'{"v":3,"id":"x","method":"core.protocol"}\n', b'{"v":"2","id":"x","method":"core.protocol"}\n',
                b'{"id":"x","method":"core.protocol"}\n'):
        client.send_raw(raw)
        assert client.read_json()["error"] == {"code": "bad-request", "message": "unsupported version"}
    client.close()


def test_09_envelope_rules(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    assert client.call("core.health")["v"] == 2
    bad_key = client.call("core.health", extra={"auth": {"token": "x"}})
    assert bad_key["v"] == 2 and bad_key["error"]["code"] == "bad-request"
    assert client.call("core.health", extra={"other": 1})["error"]["code"] == "bad-request"
    unknown = client.call("no.such")
    assert set(unknown["error"]) == {"code", "message"}
    assert unknown["error"]["code"] == "not-found"
    real = client.call("device.get", {"id": UBLOX_ID}, req_id="same")
    invented = client.call("device.get", {"id": "dev_0123456789abcdef"}, req_id="same")
    malformed = client.call("device.get", {"logical": "bogus"}, req_id="same")
    assert real == invented == malformed
    assert real["error"] == {"code": "forbidden", "message": "device.get requires operator"}
    assert client.call("medical.patients.list")["error"]["code"] == "not-found"
    token = login(core)
    assert client.call("medical.patients.list", session=token)["error"]["code"] == "not-found"
    client.send_raw(b'{"v":2,"method":"core.health"}\n')
    assert client.read_json() == {"v": 2, "id": None, "ok": False,
                                  "error": {"code": "bad-request", "message": "missing id"}}
    assert client.call("core.health", params=[])["error"] == {"code": "bad-request", "message": "invalid params"}
    client.close()


def test_10_no_session_is_public_even_for_peers_admin(p2env):
    core = p2env(peers={os.geteuid(): "administrator"})
    client = V2Client(core.config.socket)
    assert client.call("device.list")["error"]["code"] == "forbidden"
    assert client.call("session.whoami")["result"] == {"role": "public"}
    assert client.call("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID})["error"]["code"] == "forbidden"
    client.close()


def test_11_bad_session_is_unauthenticated_never_public(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    expected = {"code": "unauthenticated", "message": "session invalid"}
    for token in ("", "garbage", "x" * 43, 5, None):
        reply = client.call("core.health", session=token) if token is not None else client.call(
            "core.health", extra={"session": None})
        assert reply["error"] == expected
    token = login(core)
    assert client.call("session.logout", session=token)["ok"] is True
    assert client.call("core.health", session=token)["error"] == expected
    client.close()


def test_12_login_whoami_logout(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    for name, password, role in (("dragon", DRAGON_PW, "administrator"), ("op", OP_PW, "operator")):
        reply = client.call("session.login", {"username": name, "secret": password})
        result = reply["result"]
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", result["session"])
        assert result["username"] == name and result["role"] == role
        assert result["idle_timeout_s"] == 7200 and result["expires_in_s"] == 43200
        who = client.call("session.whoami", session=result["session"])["result"]
        assert who == {"role": role, "username": name, "idle_timeout_s": 7200, "expires_in_s": 43200}
        assert client.call("session.logout", session=result["session"])["result"] == {}
        assert client.call("session.whoami", session=result["session"])["error"]["code"] == "unauthenticated"
    assert client.call("session.login", {"username": 5, "secret": "x"})["error"]["code"] == "bad-request"
    assert client.call("session.login", {"username": "dragon", "secret": None})["error"]["code"] == "bad-request"
    assert client.call("session.logout")["error"]["code"] == "unauthenticated"
    client.close()


def test_16_uid_binding(p2env):
    holder = {"uid": os.geteuid()}
    core = p2env(peer_uid_fn=lambda _conn: holder["uid"])
    token = login(core)
    holder["uid"] = os.geteuid() + 1
    other = V2Client(core.config.socket)
    assert other.call("core.health", session=token)["error"] == {"code": "unauthenticated", "message": "session invalid"}
    holder["uid"] = os.geteuid()
    mine = V2Client(core.config.socket)
    assert mine.call("session.whoami", session=token)["result"]["username"] == "dragon"
    other.close()
    mine.close()


def test_18_restart_invalidates_tokens_and_changes_boot_id(p2env):
    core = p2env()
    base = core._base
    client = V2Client(core.config.socket)
    boot = client.call("core.protocol")["result"]["boot_id"]
    token = login(core)
    client.close()
    core.close()
    again = p2env(base=base, state_dir=base / "state")
    client = V2Client(again.config.socket)
    assert client.call("core.protocol")["result"]["boot_id"] != boot
    assert client.call("core.health", session=token)["error"]["code"] == "unauthenticated"
    client.close()


def test_23_roles_and_state_changing_methods_require_administrator(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    op = login(core, "op")
    dragon = login(core, "dragon")
    assert client.call("device.list", session=op)["ok"] is True
    assert client.call("device.get", {"id": UBLOX_ID}, session=op)["ok"] is True
    assert client.call("events.recent", session=op)["ok"] is True
    assert client.call("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID}, session=op)["error"] == {
        "code": "forbidden", "message": "device.assign requires administrator"}
    assert client.call("device.unassign", {"logical": "gps.primary"}, session=op)["error"]["code"] == "forbidden"
    assigned = client.call("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID}, session=dragon)
    assert assigned["result"] == {"logical": "sdr.primary", "device_id": SDR_ID, "alias": None, "displaced": []}
    assert client.call("device.unassign", {"logical": "sdr.primary"}, session=dragon)["result"] == {
        "logical": "sdr.primary", "device_id": None}
    # table-driven: every state-changing method is administrator-only, and nothing else mutates
    assert STATE_CHANGING == {"device.assign", "device.unassign"}
    for method in STATE_CHANGING:
        assert V2_METHODS[method] == "administrator"
    identifying = {"device.list", "device.get", "events.recent"}
    for method in identifying:
        assert V2_METHODS[method] == "operator"
    assert {m for m, r in V2_METHODS.items() if r == "public"} == {
        "core.protocol", "core.health", "module.list", "capability.list", "device.counts", "events.since",
        "events.subscribe", "session.login", "session.logout", "session.whoami"}
    client.close()
