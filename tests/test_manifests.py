from pathlib import Path

from conftest import SHARE, LineClient, modules_by_id


def test_invalid_manifest_does_not_stop_system(env, tmp_path):
    share = tmp_path / "share"
    modules = share / "modules"
    modules.mkdir(parents=True)
    (share / "devices").mkdir()
    (modules / "system.yaml").write_text(
        (SHARE / "modules" / "system.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (modules / "broken.yaml").write_text("api: 99\nid: broken\n", encoding="utf-8")
    core = env(share_dir=share)
    client = LineClient(core.config.socket)
    states = modules_by_id(client.request("module.list"))
    assert states["broken"]["state"] == "rejected"
    assert states["broken"]["reason"] == "unsupported api"
    assert states["system"]["state"] == "ready"
    assert client.request("core.health")["result"]["ok"] is True
    client.close()


def test_dependency_cycle_is_rejected(env, tmp_path):
    share = tmp_path / "share"
    modules = share / "modules"
    modules.mkdir(parents=True)
    (share / "devices").mkdir()
    body = """
api: 1
id: {id}
name: {name}
version: 0.1.0
summary: cycle test
requires: [{dep}]
capabilities:
  requires: []
logical_devices: []
permissions:
  public: []
  operator: []
  administrator: []
systemd: []
"""
    (modules / "aaa.yaml").write_text(body.format(id="aaa", name="A", dep="bbb"), encoding="utf-8")
    (modules / "bbb.yaml").write_text(body.format(id="bbb", name="B", dep="aaa"), encoding="utf-8")
    core = env(share_dir=share)
    client = LineClient(core.config.socket)
    states = modules_by_id(client.request("module.list"))
    assert states["aaa"]["state"] == "rejected"
    assert states["bbb"]["state"] == "rejected"
    assert client.request("core.health")["result"]["ok"] is True
    client.close()
    assert Path(core.config.state_dir / "patients.db").exists() is False
