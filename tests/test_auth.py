import logging

from conftest import LineClient


def test_roles_and_ignored_token(env, caplog):
    operator = env(peers={50: "operator"}, peer_uid_fn=lambda _conn: 50)
    operator_client = LineClient(operator.config.socket)
    denied = operator_client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": "dev_0123456789abcdef"},
    )
    assert denied["error"]["code"] == "forbidden"
    assert denied["error"]["message"] == "device.assign requires administrator"
    operator_client.close()

    public = env(peers={}, peer_uid_fn=lambda _conn: 424242)
    public_client = LineClient(public.config.socket)
    assert public_client.request("device.list")["error"]["code"] == "forbidden"
    assert public_client.request("core.health")["result"]["ok"] is True
    caplog.set_level(logging.DEBUG, logger="task_core")
    token = "super-secret-token-value"
    still = public_client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": "dev_0123456789abcdef"},
        token=token,
    )
    assert still["error"]["code"] == "forbidden"
    assert token not in caplog.text
    public_client.close()


def test_manifest_permission_does_not_grant_access(env, tmp_path):
    from conftest import SHARE

    share = tmp_path / "share"
    modules = share / "modules"
    modules.mkdir(parents=True)
    (share / "devices").mkdir()
    text = (SHARE / "modules" / "system.yaml").read_text(encoding="utf-8")
    text = text.replace("public: []", "public: [device.list]", 1)
    (modules / "system.yaml").write_text(text, encoding="utf-8")
    core = env(peers={}, peer_uid_fn=lambda _conn: 7, share_dir=share)
    client = LineClient(core.config.socket)
    assert client.request("device.list")["error"]["code"] == "forbidden"
    client.close()
