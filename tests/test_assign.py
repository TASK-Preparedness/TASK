import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import SHARE, LineClient, capabilities_by_name, ublox


def test_assignment_reloads_in_a_new_process_and_survives_unplug(env):
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assigned = client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": device_id, "alias": "stern gps"},
    )
    assert assigned["ok"] is True
    client.close()
    state = str(core.config.state_dir)
    auth = str(core.config.auth_file)
    core.close()

    sock = str(Path(state).parent / "child.sock")
    script = r"""
import json, os
from pathlib import Path
from task_core.config import Config
from task_core.devices import RawDevice
from task_core.main import Core

class Fake:
    def __init__(self):
        self.raw = RawDevice(
            devnode="/dev/ttyUSB0",
            by_id="/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_12345-if00",
            vid="1546",
            pid="01a7",
            serial="12345",
            subsystem="usb-serial",
            bus_path="1-1.2",
        )
        self.on_disappear = None
    def start(self, on_appear, on_disappear, on_change):
        self.on_disappear = on_disappear
        return [self.raw]
    def stop(self):
        return None

core = Core(
    Config(
        socket=os.environ["SOCK"],
        state_dir=Path(os.environ["STATE"]),
        share_dir=Path(os.environ["SHARE"]),
        auth_file=Path(os.environ["AUTH"]),
    ),
    enumerator_factory=Fake,
)
core.open()
fake = core._enumerator
import socket as socks
sock = socks.socket(socks.AF_UNIX, socks.SOCK_STREAM)
sock.connect(os.environ["SOCK"])
def call(method, params=None):
    body = {"v": 1, "id": "1", "method": method, "params": params or {}}
    sock.sendall((json.dumps(body) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(65536)
    return json.loads(buf.split(b"\n", 1)[0])
before = call("device.list")["result"]
caps_before = call("capability.list")["result"]
fake.on_disappear(fake.raw)
after = call("device.list")["result"]
caps_after = call("capability.list")["result"]
health = call("core.health")["result"]
sock.close()
core.close()
print(json.dumps({"before": before, "after": after, "caps": caps_after, "health": health}))
"""
    env_vars = os.environ.copy()
    env_vars.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "SOCK": sock,
            "STATE": state,
            "SHARE": str(SHARE),
            "AUTH": auth,
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env_vars,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["health"]["ok"] is True
    assert payload["before"]["assignments"]["gps.primary"]["device_id"] == device_id
    assert payload["before"]["assignments"]["gps.primary"]["alias"] == "stern gps"
    assert payload["after"]["assignments"]["gps.primary"]["connected"] is False
    caps = {item["name"]: item["status"] for item in payload["caps"]["capabilities"]}
    assert caps["gps.position"] == "no-device"


def test_connected_assignment_is_not_available(env):
    core = env(devices=[ublox()])
    client = LineClient(core.config.socket)
    device_id = client.request("device.list")["result"]["devices"][0]["id"]
    assert client.request(
        "device.assign", {"logical": "gps.primary", "device_id": device_id}
    )["ok"]
    caps = capabilities_by_name(client.request("capability.list"))
    assert caps["gps.position"]["status"] == "no-provider"
    modules = {item["id"]: item["state"] for item in client.request("module.list")["result"]["modules"]}
    assert modules["gps"] == "inactive"
    client.close()


def test_unknown_device_is_rejected(env):
    core = env()
    client = LineClient(core.config.socket)
    response = client.request(
        "device.assign",
        {"logical": "gps.primary", "device_id": "dev_0123456789abcdef"},
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "unknown-device"
    client.close()
