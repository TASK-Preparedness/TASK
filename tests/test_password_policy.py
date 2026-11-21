# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 31-35: the D4 password policy (section 6.5)."""

import json
import os
import pty
import select
import sys
import time
import warnings
import unicodedata
from pathlib import Path

import pytest

from task_core import passwords
from task_core.passwords import CONTROL_MESSAGE, LENGTH_MESSAGE, PolicyError, check_for_set, hash_password

from p2fixtures import V2Client, p2env  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
INVALID = {"code": "unauthenticated", "message": "invalid credentials"}


def _set(core, password, name="dragon", role="administrator"):
    """What `task-core-admin user passwd` stores (same policy function, same hash function)."""
    stored = hash_password(password)
    path = Path(core.config.state_dir) / "accounts.json"
    document = json.loads(path.read_text())
    document["accounts"][name] = {"role": role, "hash": stored, "disabled": False, "created": "2026-10-08T12:00:00Z"}
    tmp = path.with_name(".t.tmp")
    tmp.write_text(json.dumps(document))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _login(client, secret, name="dragon"):
    return client.call("session.login", {"username": name, "secret": secret})


def test_31_length_bounds_at_set_time(p2env):
    with pytest.raises(PolicyError) as short:
        check_for_set("a" * 7)
    assert str(short.value) == LENGTH_MESSAGE == "password must be 8\u2013256 characters"
    with pytest.raises(PolicyError):
        check_for_set("a" * 257)
    with pytest.raises(PolicyError):
        check_for_set("\U0001F511" * 257)
    assert check_for_set("\U0001F511" * 256) == "\U0001F511" * 256
    assert len(("\U0001F511" * 256).encode("utf-8")) == 1024
    combining = "e\u0301" * 4  # 8 code points as typed, 4 after NFC
    with pytest.raises(PolicyError):
        check_for_set(combining)
    assert len(check_for_set("e\u0301" * 8)) == 8
    core = p2env()
    client = V2Client(core.config.socket)
    for password in ("a" * 8, "b" * 64, "c" * 256, "\U0001F511" * 256):
        _set(core, password)
        assert _login(client, password)["ok"] is True
    client.close()


def test_32_length_at_login(p2env, monkeypatch):
    core = p2env()
    client = V2Client(core.config.socket)
    calls = []
    real = passwords.dummy_verify
    monkeypatch.setattr(passwords, "dummy_verify", lambda: calls.append(1) or real())
    assert _login(client, "x" * 257)["error"] == INVALID
    assert _login(client, "x" * 7)["error"] == INVALID
    assert len(calls) == 2
    for _ in range(3):
        _login(client, "y" * 257)
    assert _login(client, "z" * 300)["error"]["code"] == "rate-limited"  # out-of-policy attempts count
    monkeypatch.setattr(passwords, "dummy_verify", real)
    fresh = p2env()
    keyed = "\U0001F511" * 256
    _set(fresh, keyed)
    body = json.dumps({"v": 2, "id": "big", "method": "session.login",
                       "params": {"username": "dragon", "secret": keyed}}, ensure_ascii=True).encode() + b"\n"
    assert b"\\ud83d\\udd11" in body and len(body) < 65536
    c2 = V2Client(fresh.config.socket)
    c2.send_raw(body)
    assert c2.read_json()["ok"] is True
    c2.close()
    client.close()


def test_33_no_trimming_no_normalization_surprises(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    pairs = [("pass word ", "pass word"), (" password", "password")]
    for stored, other in pairs:
        _set(core, stored)
        assert _login(client, stored)["ok"] is True
        assert _login(client, other)["error"] == INVALID
    _set(core, " " * 8)
    assert _login(client, " " * 8)["ok"] is True
    nfd = unicodedata.normalize("NFD", "caf\u00e9-pass\u00e9")
    nfc = unicodedata.normalize("NFC", nfd)
    assert nfd != nfc
    _set(core, nfd)
    assert _login(client, nfc)["ok"] is True
    _set(core, nfc)
    assert _login(client, nfd)["ok"] is True
    _set(core, "password")
    assert _login(client, "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44")["error"] == INVALID
    _set(core, "Password1")
    assert _login(client, "password1")["error"] == INVALID
    client.close()


def test_34_control_characters_rejected_at_set_time():
    for code in list(range(0x00, 0x20)) + [0x7F]:
        with pytest.raises(PolicyError) as error:
            check_for_set("password" + chr(code) + "x")
        assert str(error.value) == CONTROL_MESSAGE
    with pytest.raises(PolicyError):
        check_for_set("long enough password\n")
    with pytest.raises(PolicyError):
        check_for_set("long\tenough")


def test_34_getpass_path_strips_only_the_line_terminator():
    """A real pseudo-terminal drives task-core-admin's getpass prompt."""
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from task_core.admin import Context, read_new_password\n"
            "print('RESULT=' + repr(read_new_password(Context(), 'dragon')))\n") % str(ROOT)
    with warnings.catch_warnings():  # the child only execs; see test_admin_cli.pty_cli
        warnings.simplefilter("ignore", DeprecationWarning)
        pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execv(sys.executable, [sys.executable, "-c", code])
        finally:
            os._exit(127)
    output = b""
    answered = 0
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 1024)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        prompts = output.count(b"password for dragon: ") + output.count(b"Repeat the password: ")
        while answered < prompts and answered < 2:
            os.write(fd, b"  secret pw  \n")
            answered += 1
        if b"RESULT=" in output and output.rstrip().endswith(b"'"):
            break
    os.waitpid(pid, 0)
    assert b"RESULT='  secret pw  '" in output
    assert output.count(b"secret pw") == 1  # no echo: only the printed result shows it


def test_35_no_composition_rules(p2env):
    core = p2env()
    client = V2Client(core.config.socket)
    generated = "aZ3 !\"'$`\\#%&()*+,-./:;<=>?@[]^_{|}~ Qx9 Lm2 Pk7 Rt5 Yw8 Ue4 Io6 Hj1 Gf0 Ds"
    generated = generated[:64]
    assert len(generated) == 64
    for password in ("aaaaaaaa", "12345678", "password", "correct horse battery staple", generated):
        assert check_for_set(password) == password
        _set(core, password)
        assert _login(client, password)["ok"] is True
    client.close()
