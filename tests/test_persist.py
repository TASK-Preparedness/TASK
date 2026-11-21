import errno
import json
import os
import stat

from task_core import persist as persist_mod
from task_core.devices import RawDevice

from conftest import LineClient, ublox


def test_replace_sequence_and_failed_rename_keeps_previous(env, monkeypatch):
    core = env(
        devices=[
            ublox(),
            RawDevice(vid="0bda", pid="2838", serial="rtl1", subsystem="usb", bus_path="2-1"),
        ]
    )
    client = LineClient(core.config.socket)
    devices = client.request("device.list")["result"]["devices"]
    gps_id = next(item["id"] for item in devices if item["class"] == "gps")
    sdr_id = next(item["id"] for item in devices if item["class"] == "sdr")
    events = []
    real_fsync = os.fsync
    real_replace = os.replace

    def spy_fsync(fd):
        kind = "fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file"
        events.append(kind)
        return real_fsync(fd)

    def spy_replace(src, dst):
        events.append("rename")
        return real_replace(src, dst)

    monkeypatch.setattr(persist_mod.os, "fsync", spy_fsync)
    monkeypatch.setattr(persist_mod.os, "replace", spy_replace)
    assert client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": gps_id, "alias": "stern gps"},
    )["ok"]
    assert core.devices.store.steps == ["write", "flush", "fsync-file", "rename", "fsync-dir"]
    assert events == ["fsync-file", "rename", "fsync-dir"]
    previous = (core.config.state_dir / "devices.json").read_bytes()

    def fail_replace(src, dst):
        raise OSError(errno.EIO, "rename failed")

    monkeypatch.setattr(persist_mod.os, "replace", fail_replace)
    failed = client.request("device.assign", {"logical": "sdr.primary", "device_id": sdr_id})
    assert failed["ok"] is False
    assert failed["error"]["code"] == "internal-error"
    assert failed["error"]["message"] == "internal error"
    assert "Traceback" not in failed["error"]["message"]
    assert (core.config.state_dir / "devices.json").read_bytes() == previous
    still = client.request("device.list")["result"]["assignments"]
    assert "gps.primary" in still
    assert "sdr.primary" not in still
    client.close()


def test_failed_file_fsync_leaves_previous_file(env, monkeypatch):
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assert client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": device_id, "alias": "stern gps"},
    )["ok"]
    previous = (core.config.state_dir / "devices.json").read_bytes()
    real_fsync = os.fsync

    def fail_file(fd):
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "file fsync failed")
        return real_fsync(fd)

    monkeypatch.setattr(persist_mod.os, "fsync", fail_file)
    failed = client.request("device.unassign", {"logical": "gps.primary"})
    assert failed["error"]["code"] == "internal-error"
    assert failed["error"]["message"] == "internal error"
    assert (core.config.state_dir / "devices.json").read_bytes() == previous
    assert (
        client.request("device.list")["result"]["assignments"]["gps.primary"]["device_id"]
        == device_id
    )
    client.close()


def test_corrupt_file_is_kept_as_evidence(env):
    core = env(do_open=False, devices=[ublox()])
    blob = b"{not json"
    target = core.config.state_dir / "devices.json"
    target.write_bytes(blob)
    core.open()
    assert target.read_bytes() == blob
    evidence = list(core.config.state_dir.glob("devices.json.corrupt.*"))
    assert len(evidence) == 1
    assert evidence[0].read_bytes() == blob
    client = LineClient(core.config.socket)
    assert client.request("core.health")["result"]["ok"] is True
    assert client.request("device.list")["result"]["assignments"] == {}
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assert client.request(
        "device.assign", {"logical": "gps.primary", "device_id": device_id}
    )["ok"]
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["v"] == 1
    assert evidence[0].read_bytes() == blob
    assert target.read_bytes() != blob
    client.close()


def test_failed_evidence_copy_does_not_touch_original(env, caplog):
    assert os.geteuid() != 0
    core = env(do_open=False)
    blob = b"%%%corrupt%%%"
    target = core.config.state_dir / "devices.json"
    target.write_bytes(blob)
    os.chmod(core.config.state_dir, 0o555)
    try:
        caplog.set_level("WARNING")
        core.open()
        assert target.read_bytes() == blob
        assert list(core.config.state_dir.glob("devices.json.corrupt.*")) == []
        assert "evidence copy failed" in caplog.text
        client = LineClient(core.config.socket)
        assert client.request("core.health")["result"]["ok"] is True
        assert client.request("device.list")["result"]["assignments"] == {}
        client.close()
    finally:
        os.chmod(core.config.state_dir, 0o755)


def test_genuine_directory_fsync_failure_is_not_success(env, monkeypatch, caplog):
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assert client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": device_id, "alias": "stern gps"},
    )["ok"]
    real_fsync = os.fsync

    def fail_dir(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "SECRET_PATH /var/lib/task")
        return real_fsync(fd)

    monkeypatch.setattr(persist_mod.os, "fsync", fail_dir)
    caplog.set_level("ERROR")
    failed = client.request("device.unassign", {"logical": "gps.primary"})
    assert failed["ok"] is False
    assert failed["error"]["code"] == "internal-error"
    assert failed["error"]["message"] == "internal error"
    raw = json.dumps(failed)
    assert "SECRET_PATH" not in raw
    assert "EIO" not in raw
    assert "SECRET_PATH" not in caplog.text
    assert "EIO" not in caplog.text
    assert "directory fsync failed" in caplog.text
    listed = client.request("device.list")["result"]["assignments"]
    assert listed["gps.primary"]["device_id"] == device_id
    stored = (core.config.state_dir / "devices.json").read_text(encoding="utf-8")
    assert "stern gps" not in stored
    client.close()


def test_directory_fsync_unsupported_is_logged_once(env, monkeypatch, caplog):
    from task_core.persist import reset_directory_fsync_warning

    reset_directory_fsync_warning()
    real_fsync = os.fsync

    def spy_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "unsupported")
        return real_fsync(fd)

    monkeypatch.setattr(persist_mod.os, "fsync", spy_fsync)
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    caplog.set_level("WARNING")
    assert client.request(
        "device.assign", {"logical": "gps.primary", "device_id": device_id}
    )["ok"]
    assert client.request("device.unassign", {"logical": "gps.primary"})["ok"]
    assert caplog.text.count("directory fsync not supported") == 1
    client.close()
