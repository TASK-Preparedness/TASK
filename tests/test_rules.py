from task_core.devices import RawDevice

from conftest import LineClient, uart


def test_generic_uart_is_not_claimed_as_mesh(env):
    core = env(
        devices=[
            uart("10c4", "ea60", "1-1.3"),
            uart("1a86", "7523", "1-1.4", serial="0000"),
        ]
    )
    client = LineClient(core.config.socket)
    devices = client.request("device.list")["result"]["devices"]
    assert len(devices) == 2
    for device in devices:
        assert device["class"] == "unknown"
        assert device["potential"] == []
        assert device["logical"] is None
        assert device["class"] != "mesh"
    client.close()


def test_known_hardware_is_classified_but_not_assigned(env):
    rtl = RawDevice(
        devnode=None,
        vid="0bda",
        pid="2838",
        serial=None,
        subsystem="usb",
        bus_path="1-1.5",
        product="RTL2838",
    )
    gps = RawDevice(
        devnode="/dev/ttyACM0",
        vid="1546",
        pid="01a7",
        serial="999",
        subsystem="usb-serial",
        bus_path="1-1.6",
    )
    core = env(devices=[rtl, gps])
    client = LineClient(core.config.socket)
    by_class = {item["class"]: item for item in client.request("device.list")["result"]["devices"]}
    assert set(by_class) == {"gps", "sdr"}
    assert by_class["gps"]["logical"] is None
    assert by_class["sdr"]["logical"] is None
    assert by_class["sdr"]["potential"] == ["radio.rx"]
    assert "radio.tx" not in by_class["sdr"]["potential"]
    caps = {
        item["name"]: item
        for item in client.request("capability.list")["result"]["capabilities"]
    }
    assert caps["gps.position"]["status"] != "available"
    assert caps["radio.rx"]["status"] != "available"
    assert caps["radio.tx"]["status"] != "available"
    client.close()
