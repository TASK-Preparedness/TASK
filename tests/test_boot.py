from task_core.errors import EnumeratorError

from conftest import LineClient, capabilities_by_name, modules_by_id


def test_boots_with_nothing_attached(env):
    core = env()
    client = LineClient(core.config.socket)
    health = client.request("core.health")
    assert health["result"]["ok"] is True
    states = modules_by_id(client.request("module.list"))
    assert states["system"]["state"] == "ready"
    assert states["medical"]["state"] == "ready"
    for name in ("gps", "mesh", "sdr", "radio", "weather"):
        assert states[name]["state"] == "inactive"
    assert not (core.config.state_dir / "patients.db").exists()
    assert not (core.config.state_dir / "station.db").exists()
    caps = capabilities_by_name(client.request("capability.list"))
    assert all(item["status"] != "available" for item in caps.values())
    client.close()


def test_udev_constructor_failure_stays_up(env):
    def factory():
        raise EnumeratorError("udev unavailable")

    core = env(enumerator_factory=factory)
    client = LineClient(core.config.socket)
    health = client.request("core.health")
    assert health["result"]["ok"] is True
    listed = client.request("device.list")
    assert listed["result"]["devices"] == []
    client.close()
    assert core.server is not None


def test_bus_subscriber_error_does_not_stop_the_next(env):
    core = env()
    seen = []

    def bad(_event):
        raise RuntimeError("SECRET_TRACE")

    def good(event):
        seen.append(event["topic"])

    core.bus.subscribe(bad)
    core.bus.subscribe(good)
    core.bus.publish("device.appeared", "devmgr", {})
    assert "device.appeared" in seen
    client = LineClient(core.config.socket)
    assert client.request("core.health")["result"]["ok"] is True
    client.close()
