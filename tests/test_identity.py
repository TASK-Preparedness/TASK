from task_core.devices import RawDevice, identity_for, make_id

from conftest import LineClient, ublox


def test_same_by_id_is_one_device_when_devnode_changes(env):
    first = ublox("/dev/ttyUSB0")
    core = env(devices=[first])
    client = LineClient(core.config.socket)
    listed = client.request("device.list")
    device = listed["result"]["devices"][0]
    key, stable = identity_for(first)
    assert stable is True
    assert key.startswith("serial-by-id:")
    assert device["id"] == make_id(key)
    assert device["devnode"] == "/dev/ttyUSB0"
    assigned = client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": device["id"], "alias": "stern gps"},
    )
    assert assigned["ok"] is True
    moved = ublox("/dev/ttyUSB1")
    core._fake.change(moved)
    again = client.request("device.list")
    assert len(again["result"]["devices"]) == 1
    assert again["result"]["devices"][0]["id"] == device["id"]
    assert again["result"]["devices"][0]["devnode"] == "/dev/ttyUSB1"
    assert again["result"]["assignments"]["gps.primary"]["device_id"] == device["id"]
    stored = (core.config.state_dir / "devices.json").read_text(encoding="utf-8")
    assert "ttyUSB" not in stored
    client.close()


def test_missing_serial_is_unstable_bus_path(env):
    raw = RawDevice(
        devnode="/dev/ttyUSB4",
        vid="0403",
        pid="6001",
        serial=None,
        subsystem="usb-serial",
        bus_path="1-1.2",
    )
    key, stable = identity_for(raw)
    assert stable is False
    assert key == "usb-path:1-1.2"
    core = env(devices=[raw])
    client = LineClient(core.config.socket)
    device = client.request("device.list")["result"]["devices"][0]
    assert device["identity_stable"] is False
    assert device["id"] == make_id(key)
    assert device["logical"] is None
    client.close()
