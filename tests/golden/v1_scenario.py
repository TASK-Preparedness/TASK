# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""The scripted v1 session behind the golden transcript (PHASE-2.md test 2).

Recorded once against rain-core 0.1.1 (tag phase1-accepted) with:

    git archive phase1-accepted | tar -x -C /tmp/rc-011
    PYTHONPATH=/tmp/rc-011 python3 tests/golden/v1_scenario.py --record \
        tests/golden/v1_transcript_0.1.1.json

and replayed against the working tree by tests/test_v1_golden.py. Only the
rain_core package on sys.path differs between the two runs. No request uses
"v": 2 (section 5.1: that is the one intended difference).
"""

import json
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

from task_core.config import Config
from task_core.devices import RawDevice
from task_core.main import Core

PUBLIC, OPERATOR, ADMIN = 5001, 5002, 5003
UBLOX_BY_ID = "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"
CP2102_BY_ID = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"


def devices():
    ublox = RawDevice(devnode="/dev/ttyACM0", by_id=UBLOX_BY_ID, vid="1546", pid="01a7",
                      manufacturer="u-blox AG - www.u-blox.com", product="u-blox 7 - GPS/GNSS Receiver",
                      subsystem="usb-serial", bus_path="platform-xhci-hcd.0-usb-0:1")
    sdr = RawDevice(devnode="/dev/bus/usb/003/002", vid="0bda", pid="2838", serial="00000001",
                    manufacturer="RTLSDRBlog", product="Blog V4", subsystem="usb",
                    bus_path="platform-xhci-hcd.1-usb-0:1")
    cp = RawDevice(devnode="/dev/ttyUSB0", by_id=CP2102_BY_ID, vid="10c4", pid="ea60", serial="0001",
                   manufacturer="Silicon Labs", product="CP2102 USB to UART Bridge Controller",
                   subsystem="usb-serial", bus_path="platform-xhci-hcd.1-usb-0:2")
    noserial = RawDevice(devnode="/dev/ttyUSB1", vid="1a86", pid="7523", subsystem="usb-serial",
                         bus_path="platform-xhci-hcd.0-usb-0:2")
    return ublox, sdr, cp, noserial


class Enum:
    def __init__(self, items):
        self.items = list(items)

    def start(self, appear, disappear, change):
        self.appear, self.disappear, self.change_cb = appear, disappear, change
        return list(self.items)

    def stop(self):
        return None


class Client:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(path)
        self.buf = b""

    def send(self, data: bytes):
        self.sock.sendall(data)

    def read(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                return {"closed": True}
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    def closed(self):
        self.sock.settimeout(2)
        try:
            return self.sock.recv(16) == b""
        except socket.timeout:
            return False


def normalize(value, key=None):
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if key == "time" and isinstance(value, str):
        return "<time>"
    if key == "id" and isinstance(value, str) and value.startswith("evt_"):
        return "<evt>"
    if key == "uptime_seconds":
        return "<uptime>"
    return value


def req(method, params=None, rid="1", **extra):
    body = {"v": 1, "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    body.update(extra)
    return json.dumps(body).encode() + b"\n"


NEW_V2_NAMES = ["core.protocol", "device.counts", "session.login", "session.logout",
                "session.whoami", "events.subscribe", "events.since"]


def run() -> list:
    base = Path(tempfile.mkdtemp(prefix="rngold", dir="/tmp"))
    try:
        return _run(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _run(base: Path) -> list:
    state = base / "state"
    state.mkdir()
    fixture = {"v": 1, "assignments": {"gps.primary": {"device_id": "dev_74a462923d20f21e", "alias": "smoke"}}}
    (state / "devices.json").write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    auth = base / "auth.toml"
    auth.write_text(f'[peers]\n{OPERATOR} = "operator"\n{ADMIN} = "administrator"\n', encoding="utf-8")
    share = Path(__file__).resolve().parents[2] / "share"
    holder = {"uid": PUBLIC}
    ublox, sdr, cp, noserial = devices()
    enum = Enum([ublox, sdr, cp])
    core = Core(Config(socket=str(base / "c.sock"), state_dir=state, share_dir=share, auth_file=auth),
                enumerator_factory=lambda: enum, euid_fn=lambda: 993,
                peer_uid_fn=lambda _conn: holder["uid"])
    core.open()
    transcript = []

    def connect(uid, name):
        holder["uid"] = uid
        client = Client(core.config.socket)
        client.send(req("core.health", rid="sync"))
        transcript.append({"client": name, "send": "core.health sync", "reply": normalize(client.read())})
        return client

    def step(client, name, data: bytes):
        client.send(data)
        reply = client.read()
        transcript.append({"client": name, "send": data.decode("utf-8", "replace"), "reply": normalize(reply)})
        return reply

    def snapshot(label):
        transcript.append({"devices_json": label, "text": (state / "devices.json").read_text(encoding="utf-8")})

    try:
        pub = connect(PUBLIC, "public")
        op = connect(OPERATOR, "operator")
        adm = connect(ADMIN, "administrator")
        snapshot("startup")
        # envelope errors (PHASE-1.md section 6 rows)
        for raw in (b"not json\n", b"\xff\xfe\n", b"\n", b"[1,2]\n", b'"text"\n', b"42\n", b"null\n",
                    b'{"v":1,"method":"core.health"}\n', b'{"v":1,"id":7,"method":"core.health"}\n',
                    b'{"v":1,"id":null,"method":"core.health"}\n',
                    b'{"id":"a","method":"core.health"}\n', b'{"v":0,"id":"a","method":"core.health"}\n',
                    b'{"v":"1","id":"a","method":"core.health"}\n', b'{"v":3,"id":"a","method":"core.health"}\n',
                    b'{"v":2.0,"id":"a","method":"core.health"}\n', b'{"v":"2","id":"a","method":"core.health"}\n',
                    b'{"v":true,"id":"a","method":"core.health"}\n', b'{"v":1.0,"id":"a","method":"core.health"}\n',
                    b'{"v":1,"id":"a"}\n', b'{"v":1,"id":"a","method":5}\n',
                    b'{"v":1,"id":"a","method":"core.health","params":[]}\n',
                    b'{"v":1,"id":"a","method":"core.health","params":"x"}\n',
                    b'{"v":1,"id":"a","method":"no.such"}\n'):
            step(pub, "public", raw)
        # every method, every role
        methods = [("core.health", None), ("module.list", None), ("capability.list", None),
                   ("device.list", None), ("device.get", {"id": "dev_74a462923d20f21e"}),
                   ("events.recent", None),
                   ("device.assign", {"logical": "sdr.primary", "device_id": "dev_ca4a208a9242de2c"}),
                   ("device.unassign", {"logical": "sdr.primary"})]
        for client, name in ((pub, "public"), (op, "operator")):
            for method, params in methods:
                step(client, name, req(method, params))
        for method, params in methods:
            step(adm, "administrator", req(method, params))
        snapshot("after admin sdr round trip")
        # medical and the new Phase 2 names, sent as v1
        for client, name in ((pub, "public"), (adm, "administrator")):
            for method in ["medical.patients.list", "medical.patients.get"] + NEW_V2_NAMES:
                step(client, name, req(method, {}))
        # v1 ignores session and auth
        step(pub, "public", req("device.list", {}, session="abc"))
        step(pub, "public", req("device.list", {}, auth={"token": "x"}))
        step(adm, "administrator", req("device.list", {}, session="abc", auth={"token": "x"}))
        # device.get variants
        for params in ({"logical": "gps.primary"}, {"logical": "mesh.primary"}, {"logical": "bogus"},
                       {}, {"id": "dev_0000000000000000"}, {"id": ""}, {"logical": ""}):
            step(op, "operator", req("device.get", params))
        # assign error rows and displacement (v1: last write wins, no confirmation)
        for params in ({"logical": "bogus", "device_id": "dev_ca4a208a9242de2c"},
                       {"logical": 5, "device_id": "dev_ca4a208a9242de2c"},
                       {"device_id": "dev_ca4a208a9242de2c"},
                       {"logical": "sdr.primary"}, {"logical": "sdr.primary", "device_id": 5},
                       {"logical": "sdr.primary", "device_id": "dev_0000000000000000"},
                       {"logical": "sdr.primary", "device_id": "dev_ca4a208a9242de2c", "alias": 5},
                       {"logical": "sdr.primary", "device_id": "dev_ca4a208a9242de2c", "alias": "sdr"},
                       {"logical": "gps.primary", "device_id": "dev_ccbc25d5a4210a5a", "alias": "x"},
                       {"logical": "mesh.primary", "device_id": "dev_ccbc25d5a4210a5a"},
                       {"logical": "gps.primary", "device_id": "dev_74a462923d20f21e", "alias": "smoke"}):
            step(adm, "administrator", req("device.assign", params))
            snapshot("after assign " + json.dumps(params, sort_keys=True))
        for params in ({"logical": "bogus"}, {}, {"logical": 3}, {"logical": "radio.primary"},
                       {"logical": "mesh.primary"}, {"logical": "sdr.primary"}):
            step(adm, "administrator", req("device.unassign", params))
            snapshot("after unassign " + json.dumps(params, sort_keys=True))
        # hot-plug cycle including an unstable-identity device
        enum.disappear(ublox)
        step(op, "operator", req("device.list"))
        enum.appear(ublox)
        enum.appear(noserial)
        step(op, "operator", req("device.list"))
        enum.disappear(noserial)
        enum.appear(cp)
        step(op, "operator", req("device.list"))
        step(op, "operator", req("capability.list"))
        step(op, "operator", req("module.list"))
        step(op, "operator", req("events.recent"))
        step(adm, "administrator", req("events.recent"))
        snapshot("end")
        # oversize request closes only that client
        big = Client(core.config.socket)
        big.send(b"x" * (65536 + 50))
        transcript.append({"client": "oversize", "send": "65586 x bytes", "reply": normalize(big.read()),
                           "closed": big.closed()})
        step(pub, "public", req("core.health"))
    finally:
        core.close()
    time.sleep(0.05)
    return transcript


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--record":
        import rain_core

        data = {"recorded_with": rain_core.__version__, "transcript": run()}
        Path(sys.argv[2]).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("recorded", len(data["transcript"]), "entries with rain_core", rain_core.__version__)
    else:
        print(__doc__)
        sys.exit(1)
