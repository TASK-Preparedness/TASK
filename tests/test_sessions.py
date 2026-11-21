# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 13-15, 17, 19-21: sessions, rate limits, expiry, accounts.json."""

import json
import logging
import os
from pathlib import Path

from task_core import passwords

from p2fixtures import (DRAGON_PW, OP_PW, UBLOX_ID, FakeClock, V2Client, cached_hash, default_accounts,  # noqa: F401
                        fixture_devices_json, login, p2env, write_accounts, write_sessions)

INVALID = {"code": "unauthenticated", "message": "invalid credentials"}


def test_13_identical_failures_and_dummy_scrypt(p2env, monkeypatch):
    core = p2env()
    calls = []
    real = passwords.dummy_verify
    monkeypatch.setattr(passwords, "dummy_verify", lambda: calls.append(1) or real())
    client = V2Client(core.config.socket)
    unknown = client.call("session.login", {"username": "nobody", "secret": DRAGON_PW}, req_id="x")
    assert len(calls) == 1
    wrong = client.call("session.login", {"username": "dragon", "secret": "wrong password"}, req_id="x")
    assert len(calls) == 1  # the real hash was checked
    assert unknown == wrong == {"v": 2, "id": "x", "ok": False, "error": INVALID}
    client.close()


def test_14_client_allow_list_and_timeouts(p2env, caplog):
    core = p2env(clients=[os.geteuid() + 1])
    client = V2Client(core.config.socket)
    forbidden = {"code": "forbidden", "message": "session.login not allowed for this client"}
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == forbidden
    sessions = core._base / "sessions.toml"
    sessions.write_text("[clients\nbroken", encoding="utf-8")
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == forbidden
    sessions.write_text("", encoding="utf-8")
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == forbidden
    caplog.set_level(logging.INFO, logger="task_core")
    write_sessions(sessions, [os.geteuid()], idle=59, absolute=86401)
    reply = client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})
    assert reply["result"]["idle_timeout_s"] == 7200 and reply["result"]["expires_in_s"] == 43200
    assert "sessions idle_seconds out of range; using default 7200" in caplog.text
    assert "sessions absolute_seconds out of range; using default 43200" in caplog.text
    write_sessions(sessions, [os.geteuid()], idle=600, absolute=3600)
    reply = client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})
    assert reply["result"]["idle_timeout_s"] == 600 and reply["result"]["expires_in_s"] == 3600
    client.close()


def _fail(client, user="dragon"):
    return client.call("session.login", {"username": user, "secret": "wrong password"})


def test_15_rate_limiting(p2env):
    clock = FakeClock()
    core = p2env(clock=clock)
    client = V2Client(core.config.socket)
    for _ in range(5):
        assert _fail(client)["error"] == INVALID
    limited = client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})
    assert limited["error"] == {"code": "rate-limited", "message": "too many attempts, retry in 30 s"}
    clock.advance(29)
    assert _fail(client)["error"]["message"] == "too many attempts, retry in 1 s"
    expected_waits = [60, 120, 240, 480, 900, 900]
    clock.advance(1)
    for wait in expected_waits:
        assert _fail(client)["error"] == INVALID
        assert _fail(client)["error"] == {"code": "rate-limited", "message": f"too many attempts, retry in {wait} s"}
        clock.advance(wait)
    # a success resets the counter
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["ok"] is True
    for _ in range(4):
        assert _fail(client)["error"] == INVALID
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["ok"] is True
    client.close()


def test_15_username_and_uid_keys_are_independent(p2env):
    holder = {"uid": os.geteuid()}
    second = os.geteuid() + 1
    clock = FakeClock()
    core = p2env(clock=clock, clients=[os.geteuid(), second], peer_uid_fn=lambda _c: holder["uid"])
    first = V2Client(core.config.socket)
    for _ in range(5):
        _fail(first, user="nobody")
    # same uid, different username: the uid key is locked
    assert first.call("session.login", {"username": "op", "secret": OP_PW})["error"]["code"] == "rate-limited"
    holder["uid"] = second
    other = V2Client(core.config.socket)
    # other uid, the locked username: the username key is locked
    assert other.call("session.login", {"username": "nobody", "secret": "x" * 8})["error"]["code"] == "rate-limited"
    # other uid, other username: free
    assert other.call("session.login", {"username": "op", "secret": OP_PW})["ok"] is True
    first.close()
    other.close()


def test_17_idle_expiry_and_stream_frames_do_not_refresh(p2env):
    clock = FakeClock()
    core = p2env(clock=clock, heartbeat_interval=0.05)
    client = V2Client(core.config.socket)
    token = login(core)
    clock.advance(7199)
    assert client.call("core.health", session=token)["ok"] is True
    clock.advance(7199)
    assert client.call("core.health", session=token)["ok"] is True
    stream = V2Client(core.config.socket)
    assert stream.call("events.subscribe", {}, session=token)["ok"] is True
    clock.advance(7000)
    for _ in range(3):
        core.bus.publish("device.appeared", "devmgr", {"id": "x"})
    frames = [stream.try_read(2) for _ in range(3)]
    assert all(frame and "event" in frame for frame in frames)
    heartbeat = stream.try_read(2)
    assert heartbeat and "heartbeat" in heartbeat
    clock.advance(201)  # 7201 s since the last RPC that carried the token
    assert client.call("core.health", session=token)["error"] == {"code": "unauthenticated", "message": "session invalid"}
    stream.close()
    client.close()


def test_17_absolute_expiry(p2env):
    clock = FakeClock()
    core = p2env(clock=clock)
    client = V2Client(core.config.socket)
    reply = client.call("session.login", {"username": "op", "secret": OP_PW})["result"]
    assert reply["idle_timeout_s"] == 7200 and reply["expires_in_s"] == 43200
    token = reply["session"]
    for _ in range(720):
        clock.advance(60)
        assert client.call("session.whoami", session=token)["ok"] is True
    assert client.call("session.whoami", session=token)["result"]["expires_in_s"] == 0
    clock.advance(1)
    assert client.call("session.whoami", session=token)["error"]["code"] == "unauthenticated"
    client.close()


def test_19_account_changes_invalidate_sessions(p2env):
    core = p2env()
    state = core.config.state_dir
    client = V2Client(core.config.socket)
    cases = [
        {"dragon": ("administrator", DRAGON_PW, True), "op": ("operator", OP_PW, False)},   # disabled
        {"op": ("operator", OP_PW, False)},                                                 # removed
        {"dragon": ("operator", DRAGON_PW, False), "op": ("operator", OP_PW, False)},        # role change
        {"dragon": ("administrator", "a new password", False), "op": ("operator", OP_PW, False)},  # new hash
    ]
    for accounts in cases:
        write_accounts(state, default_accounts())
        token = login(core)
        op_token = login(core, "op")
        assert client.call("session.whoami", session=token)["ok"] is True
        before = os.stat(state / "accounts.json")
        write_accounts(state, accounts)
        after = os.stat(state / "accounts.json")
        assert (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size)
        assert client.call("session.whoami", session=token)["error"]["code"] == "unauthenticated"
        assert client.call("session.whoami", session=op_token)["ok"] is True
    client.close()


def test_20_permissions_rejected_fail_closed(p2env, caplog):
    caplog.set_level(logging.INFO, logger="task_core")
    core = p2env(accounts=None)
    write_accounts(core.config.state_dir, default_accounts(), mode=0o640)
    client = V2Client(core.config.socket)
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == INVALID
    assert "accounts file permissions rejected" in caplog.text
    os.chmod(core.config.state_dir / "accounts.json", 0o600)
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["ok"] is True
    os.chmod(core.config.state_dir / "accounts.json", 0o604)
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == INVALID
    client.close()


def test_20_corrupt_accounts_evidence_and_assignments_intact(p2env, caplog):
    caplog.set_level(logging.INFO, logger="task_core")
    from pathlib import Path
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="rn2c", dir="/tmp"))
    state = base / "state"
    state.mkdir()
    (state / "devices.json").write_bytes(fixture_devices_json())
    bad = b'{"v": 2, "accounts": {}}\n'
    path = state / "accounts.json"
    path.write_bytes(bad)
    os.chmod(path, 0o600)
    core = p2env(base=base, state_dir=state)
    evidence = sorted(state.glob("accounts.json.corrupt.*"))
    assert len(evidence) == 1 and evidence[0].read_bytes() == bad
    assert path.read_bytes() == bad
    assert "corrupt accounts preserved at accounts.json.corrupt." in caplog.text
    client = V2Client(core.config.socket)
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"] == INVALID
    assert len(sorted(state.glob("accounts.json.corrupt.*"))) == 1  # not re-copied on every login
    from conftest import LineClient

    v1 = LineClient(core.config.socket)
    assert v1.request("device.list")["result"]["assignments"]["gps.primary"]["device_id"] == UBLOX_ID
    v1.close()
    assert (state / "devices.json").read_bytes() == fixture_devices_json()
    client.close()
    import shutil

    shutil.rmtree(base, ignore_errors=True)


def test_21_no_secrets_on_disk_or_in_logs(p2env, caplog):
    caplog.set_level(logging.DEBUG)
    core = p2env()
    client = V2Client(core.config.socket)
    token = login(core)
    client.call("session.login", {"username": "dragon", "secret": "Wrong-Secret-xyz"})
    client.call("session.login", {"username": "Wrong-Secret-xyz", "secret": "Wrong-Secret-xyz"})
    client.call("session.logout", session=token)
    stored_hash = cached_hash(DRAGON_PW)
    salt_and_key = stored_hash.split("$", 2)[2]
    secrets = [token, DRAGON_PW, "Wrong-Secret-xyz", salt_and_key]
    log_text = caplog.text
    for secret in secrets:
        assert secret not in log_text
    assert "login ok user=dragon role=administrator" in log_text
    assert "login failed" in log_text and "logout user=dragon" in log_text
    for path in Path(core.config.state_dir).rglob("*"):
        if path.is_file() and path.name != "accounts.json":
            data = path.read_bytes()
            for secret in secrets:
                assert secret.encode() not in data
    accounts_bytes = (core.config.state_dir / "accounts.json").read_bytes()
    assert token.encode() not in accounts_bytes and DRAGON_PW.encode() not in accounts_bytes
    client.close()
