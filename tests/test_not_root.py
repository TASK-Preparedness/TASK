import os
from pathlib import Path

from task_core.errors import RootRefused

from conftest import LineClient, ublox

ROOT = Path(__file__).resolve().parents[1] / "task_core"


def test_runs_and_assigns_when_not_root(env):
    assert os.geteuid() != 0
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    health = client.request("core.health")
    assert health["ok"] is True
    assert health["result"]["ok"] is True
    assert health["result"]["uid"] == os.geteuid()
    assert health["result"]["version"] == "0.2.1"
    listed = client.request("device.list")
    assert listed["ok"] is True
    assert len(listed["result"]["devices"]) == 1
    modules = client.request("module.list")
    assert modules["ok"] is True
    assigned = client.request(
        "device.assign",
        {
            "logical": "gps.primary",
            "device_id": listed["result"]["devices"][0]["id"],
        },
    )
    assert assigned["ok"] is True
    client.close()


def test_refuses_uid_zero_without_socket(env):
    source = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.glob("*.py"))
    assert "sudo" not in source
    assert "subprocess" not in source
    core = env(euid_fn=lambda: 0, do_open=False)
    try:
        core.open()
        raised = False
    except RootRefused:
        raised = True
    assert raised is True
    assert not Path(core.config.socket).exists()
