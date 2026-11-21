import json
import os
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from task_core.config import Config
from task_core.devices import RawDevice
from task_core.errors import EnumeratorError
from task_core.main import Core

SHARE = Path(__file__).resolve().parents[1] / "share"
BY_ID = "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_12345-if00"


class FakeEnumerator:
    def __init__(self, devices=None):
        self.devices = list(devices or [])
        self.on_appear = None
        self.on_disappear = None
        self.on_change = None

    def start(self, on_appear, on_disappear, on_change):
        self.on_appear = on_appear
        self.on_disappear = on_disappear
        self.on_change = on_change
        return list(self.devices)

    def add(self, raw):
        self.devices.append(raw)
        self.on_appear(raw)

    def remove(self, raw):
        self.devices = [item for item in self.devices if item is not raw]
        self.on_disappear(raw)

    def change(self, raw):
        self.on_change(raw)

    def stop(self):
        return None


class LineClient:
    def __init__(self, path, timeout=3):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.buf = b""

    def send_raw(self, data: bytes) -> None:
        self.sock.sendall(data)

    def request(self, method, params=None, req_id="1", token=None, include_id=True, version=1):
        body = {"v": version, "method": method, "params": params or {}}
        if include_id:
            body["id"] = req_id
        if token is not None:
            body["auth"] = {"token": token}
        self.send_raw(json.dumps(body).encode() + b"\n")
        return self.read_json()

    def read_json(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    def close(self) -> None:
        self.sock.close()


def write_auth(path: Path, mapping: dict) -> None:
    lines = ["[peers]"]
    for uid, role in mapping.items():
        lines.append(f'{int(uid)} = "{role}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ublox(devnode="/dev/ttyUSB0"):
    return RawDevice(
        devnode=devnode,
        by_id=BY_ID,
        vid="1546",
        pid="01a7",
        serial="12345",
        manufacturer="u-blox",
        product="u-blox",
        subsystem="usb-serial",
        bus_path="1-1.2",
    )


def uart(vid, pid, bus_path, serial="ABC123"):
    return RawDevice(
        devnode="/dev/ttyUSB9",
        vid=vid,
        pid=pid,
        serial=serial,
        subsystem="usb-serial",
        bus_path=bus_path,
    )


@pytest.fixture
def env():
    opened = []
    bases = []

    def start(
        devices=None,
        peers=None,
        idle=None,
        peer_uid_fn=None,
        extra_methods=None,
        enumerator_factory=None,
        euid_fn=None,
        share_dir=None,
        do_open=True,
        state_dir=None,
    ):
        base = Path(tempfile.mkdtemp(prefix="rn", dir="/tmp"))
        bases.append(base)
        auth = base / "auth.toml"
        if peers is None:
            peers = {os.geteuid(): "administrator"}
        write_auth(auth, peers)
        if state_dir is None:
            state_dir = base / "state"
            state_dir.mkdir()
        fake = None
        if enumerator_factory is None:
            fake = FakeEnumerator(devices or [])
            enumerator_factory = lambda: fake
        core = Core(
            Config(
                socket=str(base / "c.sock"),
                state_dir=Path(state_dir),
                share_dir=Path(share_dir or SHARE),
                auth_file=auth,
            ),
            enumerator_factory=enumerator_factory,
            euid_fn=euid_fn,
            idle_timeout=idle,
            peer_uid_fn=peer_uid_fn,
            extra_methods=extra_methods,
        )
        core._fake = fake
        opened.append(core)
        if do_open:
            core.open()
        return core

    yield start
    for core in opened:
        core.close()
    for base in bases:
        shutil.rmtree(base, ignore_errors=True)


def modules_by_id(payload):
    return {item["id"]: item for item in payload["result"]["modules"]}


def capabilities_by_name(payload):
    return {item["name"]: item for item in payload["result"]["capabilities"]}
