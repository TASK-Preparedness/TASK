import json
import socket
from pathlib import Path

import pytest

from task_core.api import IDLE_TIMEOUT, MAX_REQUEST
from task_core.bus import RING_SIZE
from task_core.config import load_config
from task_core.errors import ConfigError

from conftest import LineClient


def test_objects_only_and_unknown_method_and_missing_id(env):
    core = env()
    client = LineClient(core.config.socket)
    client.send_raw(b"[1, 2]\n")
    array = client.read_json()
    assert array["ok"] is False
    assert array["error"]["code"] == "bad-request"
    client.send_raw(b'"hello"\n')
    text = client.read_json()
    assert text["error"]["code"] == "bad-request"
    missing = client.request("core.health", include_id=False)
    assert missing["id"] is None
    assert missing["error"]["code"] == "bad-request"
    unknown = client.request("no.such")
    assert unknown["error"]["code"] == "not-found"
    assert client.request("core.health")["result"]["ok"] is True
    client.close()
    assert IDLE_TIMEOUT == 30


def test_oversize_drops_client_and_neighbor_survives(env):
    core = env()
    broken = LineClient(core.config.socket)
    broken.send_raw(b"x" * (MAX_REQUEST + 50))
    first = broken.read_json()
    assert first["error"]["code"] == "bad-request"
    broken.sock.settimeout(1)
    try:
        leftover = broken.sock.recv(16)
    except socket.timeout:
        leftover = b"still-open"
    assert leftover == b""
    other = LineClient(core.config.socket)
    assert other.request("core.health")["result"]["ok"] is True
    other.close()


def test_internal_error_hides_the_exception(env, caplog):
    def boom(_params):
        raise RuntimeError("SECRET_TRACE /tmp/nope.py")

    core = env(extra_methods={"test.boom": ("public", boom)})
    client = LineClient(core.config.socket)
    import logging

    caplog.set_level(logging.DEBUG, logger="task_core")
    response = client.request("test.boom")
    assert response["ok"] is False
    assert response["error"]["code"] == "internal-error"
    assert response["error"]["message"] == "internal error"
    raw = json.dumps(response)
    assert "SECRET_TRACE" not in raw
    assert "Traceback" not in raw
    assert "RuntimeError" not in raw
    assert "SECRET_TRACE" not in caplog.text
    assert "Traceback" not in caplog.text
    other = LineClient(core.config.socket)
    assert other.request("core.health")["result"]["ok"] is True
    other.close()
    client.close()


def test_idle_and_stalled_clients_are_closed(env):
    core = env(idle=0.4)
    idle = LineClient(core.config.socket, timeout=2)
    try:
        idle.sock.recv(16)
        closed_idle = True
    except socket.timeout:
        closed_idle = False
    assert closed_idle is True
    stalled = LineClient(core.config.socket, timeout=2)
    stalled.send_raw(b'{"v":1')
    try:
        stalled.sock.recv(16)
        closed_stalled = True
    except socket.timeout:
        closed_stalled = False
    assert closed_stalled is True
    healthy = LineClient(core.config.socket)
    assert healthy.request("core.health")["result"]["ok"] is True
    healthy.close()


def test_ninth_client_is_closed(env):
    core = env()
    held = [LineClient(core.config.socket) for _ in range(8)]
    extra = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    extra.settimeout(2)
    extra.connect(core.config.socket)
    assert extra.recv(16) == b""
    extra.close()
    for client in held:
        assert client.request("core.health")["result"]["ok"] is True
        client.close()


def test_ring_keeps_the_newest_two_hundred():
    from task_core.bus import Bus

    bus = Bus()
    for index in range(RING_SIZE + 5):
        bus.publish("device.appeared", "devmgr", {"n": index})
    recent = bus.recent()
    assert len(recent) == RING_SIZE
    assert recent[0]["data"]["n"] == 5
    assert recent[-1]["data"]["n"] == RING_SIZE + 4


def test_socket_must_be_an_absolute_filesystem_path(tmp_path, monkeypatch):
    created = []

    def refuse(*_args, **_kwargs):
        created.append(True)
        raise AssertionError("socket created")

    monkeypatch.setattr(socket, "socket", refuse)
    samples = ("127.0.0.1:80", "core.sock", "tcp://127.0.0.1/rain", "80")
    for value in samples:
        path = tmp_path / f"{len(created)}-{value.replace('/', '_')[:20]}.toml"
        path.write_text(
            "\n".join(
                [
                    f'socket = "{value}"',
                    'state_dir = "/tmp/rain-state"',
                    'share_dir = "/tmp/rain-share"',
                    'auth_file = "/tmp/rain-auth.toml"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            load_config(path)
    numeric = tmp_path / "numeric.toml"
    numeric.write_text(
        "\n".join(
            [
                "socket = 80",
                'state_dir = "/tmp/rain-state"',
                'share_dir = "/tmp/rain-share"',
                'auth_file = "/tmp/rain-auth.toml"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(numeric)
    valid = tmp_path / "ok.toml"
    valid.write_text(
        "\n".join(
            [
                'socket = "/tmp/rain-phase1.sock"',
                'state_dir = "/tmp/rain-state"',
                'share_dir = "/tmp/rain-share"',
                'auth_file = "/tmp/rain-auth.toml"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_config(valid)
    assert loaded.socket == "/tmp/rain-phase1.sock"
    assert created == []
    assert not Path("/tmp/rain-phase1.sock").exists()
