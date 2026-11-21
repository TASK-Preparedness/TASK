from pathlib import Path

from conftest import SHARE, LineClient


def test_patient_methods_do_not_exist(env):
    core = env()
    client = LineClient(core.config.socket)
    listed = client.request("medical.patients.list")
    unlock = client.request("medical.patients.unlock")
    assert listed["error"]["code"] == "not-found"
    assert unlock["error"]["code"] == "not-found"
    assert client.request("core.health")["result"]["ok"] is True
    client.close()
    assert not (core.config.state_dir / "patients.db").exists()
    medical = (SHARE / "modules" / "medical.yaml").read_text(encoding="utf-8")
    assert "patient" not in medical
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path(__file__).resolve().parents[1].joinpath("task_core").glob("*.py")
    )
    assert "patients.db" not in source
    assert "station.db" not in source
    assert "sqlcipher" not in source.lower()


def test_suite_did_not_create_system_databases():
    assert not Path("/var/lib/task/patients.db").exists()
    assert not Path("/var/lib/task/station.db").exists()
