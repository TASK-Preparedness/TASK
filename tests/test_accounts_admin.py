# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 22, 19 (user passwd), 20 (replace sequence) and 90 (break-glass reset)."""

import json
import os
import stat
import tempfile
from pathlib import Path

from task_core import admin
from task_core.accounts import parse_document
from task_core.passwords import valid_hash_format

from p2fixtures import (DRAGON_PW, FakeGr, FakePw, SpyOps, V2Client, fixture_devices_json, login, p2env,  # noqa
                        request_spy, run_admin, write_core_toml)

SERVICE = FakePw("rain-core", 993, 993)


def _setup(tmp=None):
    base = Path(tempfile.mkdtemp(prefix="rnadm", dir="/tmp"))
    state = base / "state"
    state.mkdir()
    sessions = base / "sessions.toml"
    config = write_core_toml(base, state, sessions, str(base / "c.sock"))
    return base, state, sessions, config


def _pw(name):
    return {"rain-core": SERVICE, "kado": FakePw("kado", 1000, 1000)}[name]


def _root(argv, config, passwords=(), ops=None, getgrnam=None):
    return run_admin(["--config", str(config)] + argv, euid=0, passwords=passwords, getpwnam=_pw,
                     getgrnam=getgrnam or (lambda name: FakeGr(993, [])), ops=ops)


def test_22_user_commands_privilege_drop_mode_and_format():
    base, state, _sessions, config = _setup()
    ops = SpyOps()
    secret = "correct horse battery"
    code, out, err, ctx = _root(["user", "add", "dragon", "--role", "administrator"], config, [secret, secret], ops)
    assert code == 0, err
    assert ops.calls == [("fork",), ("setgroups", []), ("setgid", 993), ("setuid", 993)]
    path = state / "accounts.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    document = json.loads(path.read_text())
    entry = document["accounts"]["dragon"]
    assert document["v"] == 1 and entry["role"] == "administrator" and entry["disabled"] is False
    assert entry["hash"].startswith("scrypt$n=32768,r=8,p=1$") and valid_hash_format(entry["hash"])
    assert entry["created"].endswith("Z")
    assert secret not in out + err and secret not in path.read_text()
    assert ctx.prompts == ["New password for dragon: ", "Repeat the password: "]
    assert admin.LAST_STORE_STEPS == ["write", "flush", "fsync-file", "rename", "fsync-dir"]  # test 20
    assert (state / ".accounts.lock").exists()
    # duplicate, op, list, passwd, disable/enable/remove
    assert _root(["user", "add", "dragon", "--role", "operator"], config, ["x" * 9, "x" * 9])[0] == 1
    assert _root(["user", "add", "op", "--role", "operator"], config, ["op pass 1", "op pass 1"])[0] == 0
    code, out, _err, _ = _root(["user", "list"], config)
    assert out.splitlines() == ["dragon\tadministrator\tenabled", "op\toperator\tenabled"]
    assert "scrypt" not in out
    old_hash = entry["hash"]
    assert _root(["user", "passwd", "dragon"], config, ["another pass", "another pass"])[0] == 0
    assert json.loads(path.read_text())["accounts"]["dragon"]["hash"] != old_hash
    assert _root(["user", "disable", "op"], config)[0] == 0
    assert parse_document(path.read_bytes())["op"]["disabled"] is True
    assert _root(["user", "enable", "op"], config)[0] == 0
    assert parse_document(path.read_bytes())["op"]["disabled"] is False
    assert _root(["user", "remove", "op"], config)[0] == 0
    assert set(parse_document(path.read_bytes())) == {"dragon"}
    # policy and mismatch at the prompt; nothing changes
    before = path.read_bytes()
    code, _o, err, _ = _root(["user", "passwd", "dragon"], config, ["short"])
    assert code == 1 and "password must be 8\u2013256 characters" in err
    code, _o, err, _ = _root(["user", "passwd", "dragon"], config, ["long enough 1", "long enough 2"])
    assert code == 1 and "do not match" in err
    code, _o, err, _ = _root(["user", "passwd", "dragon"], config, ["tab\tinside pw"])
    assert code == 1 and "control character" in err
    assert path.read_bytes() == before
    # usernames are validated; non-root is refused
    assert _root(["user", "add", "Bad Name", "--role", "operator"], config)[0] == 1
    code, _o, err, _ = run_admin(["--config", str(config), "user", "list"], euid=1000)
    assert code == 1 and "must run as root" in err


def test_22_client_allow_and_remove_edit_sessions_toml():
    base, _state, sessions, config = _setup()
    code, out, _err, _ = _root(["client", "allow", "kado"], config)
    assert code == 0
    assert 'usermod -aG rain-core kado' in out and "not run by this tool" in out
    from task_core.config import read_toml

    assert read_toml(sessions.read_text())["clients"] == {"1000": "kado"}
    assert stat.S_IMODE(sessions.stat().st_mode) == 0o644
    sessions.write_text(sessions.read_text() + "\n[timeouts]\nidle_seconds = 600\n")
    code, out, _err, _ = _root(["client", "allow", "kado"], config, getgrnam=lambda n: FakeGr(993, ["kado"]))
    assert "usermod" not in out
    assert read_toml(sessions.read_text())["timeouts"] == {"idle_seconds": 600}
    assert _root(["client", "remove", "kado"], config)[0] == 0
    assert read_toml(sessions.read_text())["clients"] == {}
    assert read_toml(sessions.read_text())["timeouts"] == {"idle_seconds": 600}


def test_22_probe_sends_no_session_and_needs_no_root(p2env):
    core = p2env()
    seen = request_spy(core)
    code, out, err, _ = run_admin(["probe", "--socket", core.config.socket], euid=os.geteuid())
    assert code == 0, err
    assert json.loads(out)["core.protocol"]["core"] == "0.2.1"
    code, out, err, _ = run_admin(["probe", "--public", "--socket", core.config.socket])
    assert code == 0
    methods = [json.loads(line)["method"] for line in out.splitlines()]
    assert methods == ["core.protocol", "core.health", "module.list", "capability.list", "device.counts",
                       "session.whoami", "events.since"]
    assert seen and all(has_session is False for _m, has_session, _p in seen)


def test_19_user_passwd_invalidates_existing_sessions(p2env):
    core = p2env()
    base = core._base
    config = write_core_toml(base, core.config.state_dir, base / "sessions.toml", core.config.socket)
    token = login(core)
    client = V2Client(core.config.socket)
    assert client.call("session.whoami", session=token)["ok"] is True
    assert _root(["user", "passwd", "dragon"], config, ["brand new pass", "brand new pass"])[0] == 0
    assert client.call("session.whoami", session=token)["error"]["code"] == "unauthenticated"
    client.close()


def test_90_break_glass_reset(p2env):
    core = p2env()
    base, state = core._base, core.config.state_dir
    config = write_core_toml(base, state, base / "sessions.toml", core.config.socket)
    devices = state / "devices.json"
    original, inode = devices.read_bytes(), os.stat(devices).st_ino
    token = login(core)
    # with the Core running
    assert _root(["user", "passwd", "dragon"], config, ["reset pass one", "reset pass one"])[0] == 0
    client = V2Client(core.config.socket)
    assert client.call("session.whoami", session=token)["error"]["code"] == "unauthenticated"
    assert client.call("session.login", {"username": "dragon", "secret": DRAGON_PW})["error"]["message"] == \
        "invalid credentials"
    assert client.call("session.login", {"username": "dragon", "secret": "reset pass one"})["ok"] is True
    client.close()
    # with the Core stopped
    core.close()
    assert _root(["user", "passwd", "dragon"], config, ["reset pass two", "reset pass two"])[0] == 0
    again = p2env(base=base, state_dir=state)
    code, out, err, _ = run_admin(["report", "--user", "dragon", "--socket", again.config.socket],
                                  passwords=["reset pass two"])
    assert code == 0, err
    assert "version: 0.2.1" in out
    assert devices.read_bytes() == original and os.stat(devices).st_ino == inode
