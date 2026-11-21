from task_core.devices import RawDevice

from conftest import LineClient, capabilities_by_name, ublox


def _sdr():
    return RawDevice(
        vid="0bda",
        pid="2838",
        serial="rtl1",
        subsystem="usb",
        bus_path="2-1",
        product="RTL2838",
    )


def test_sdr_does_not_provide_transmit(env):
    core = env(devices=[_sdr()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assert client.request(
        "device.assign", {"logical": "sdr.primary", "device_id": device_id}
    )["ok"]
    caps = capabilities_by_name(client.request("capability.list"))
    assert caps["radio.rx"]["status"] == "no-provider"
    assert caps["radio.rx"]["kind"] == "device-backed"
    assert caps["radio.tx"]["status"] == "no-device"
    client.close()


def test_weather_is_provider_only(env):
    core = env()
    client = LineClient(core.config.socket)
    before = capabilities_by_name(client.request("capability.list"))
    assert before["weather.products"]["kind"] == "provider-only"
    assert before["weather.products"]["status"] == "no-provider"
    gps = ublox()
    core._fake.add(gps)
    device_id = None
    for device in client.request("device.list")["result"]["devices"]:
        if device["connected"] and device["class"] == "gps":
            device_id = device["id"]
    assert device_id
    assert client.request(
        "device.assign", {"logical": "gps.primary", "device_id": device_id}
    )["ok"]
    after = capabilities_by_name(client.request("capability.list"))
    assert after["weather.products"]["status"] == "no-provider"
    assert after["weather.products"]["status"] != "no-device"
    assert after["gps.position"]["status"] == "no-provider"
    client.close()
