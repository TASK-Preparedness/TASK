# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Shared helpers for the Phase 2 (task-core 0.2.0) tests.

The golden fixture is Joshua's Pi 5 device set (PHASE-2.md section 17): the
u-blox 7, the RTL-SDR Blog V4 and the CP2102, with gps.primary assigned to the
u-blox under the alias "smoke". All values here are TEST DATA.
"""

import json
import os
import socket
import tempfile
from pathlib import Path

from task_core.devices import RawDevice

UBLOX_ID = "dev_74a462923d20f21e"
SDR_ID = "dev_ca4a208a9242de2c"
CP2102_ID = "dev_ccbc25d5a4210a5a"
UBLOX_BY_ID = "/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00"
CP2102_BY_ID = "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0"
SHARE = Path(__file__).resolve().parents[1] / "share"

FIXTURE_STRINGS = [
    "u-blox AG - www.u-blox.com",
    "u-blox 7 - GPS/GNSS Receiver",
    "RTLSDRBlog",
    "Blog V4",
    "Silicon Labs",
    "CP2102 USB to UART Bridge Controller",
    "00000001",
    "0001",
]


def ublox(devnode="/dev/ttyACM0"):
    return RawDevice(
        devnode=devnode,
        by_id=UBLOX_BY_ID,
        vid="1546",
        pid="01a7",
        serial=None,
        manufacturer="u-blox AG - www.u-blox.com",
        product="u-blox 7 - GPS/GNSS Receiver",
        subsystem="usb-serial",
        bus_path="platform-xhci-hcd.0-usb-0:1",
    )


def rtlsdr():
    return RawDevice(
        devnode="/dev/bus/usb/003/002",
        vid="0bda",
        pid="2838",
        serial="00000001",
        manufacturer="RTLSDRBlog",
        product="Blog V4",
        subsystem="usb",
        bus_path="platform-xhci-hcd.1-usb-0:1",
    )


def cp2102(devnode="/dev/ttyUSB0"):
    return RawDevice(
        devnode=devnode,
        by_id=CP2102_BY_ID,
        vid="10c4",
        pid="ea60",
        serial="0001",
        manufacturer="Silicon Labs",
        product="CP2102 USB to UART Bridge Controller",
        subsystem="usb-serial",
        bus_path="platform-xhci-hcd.1-usb-0:2",
    )


def golden_devices():
    return [ublox(), rtlsdr(), cp2102()]


def fixture_devices_json() -> bytes:
    """devices.json exactly as 0.1.1 writes it for gps.primary -> u-blox "smoke"."""
    document = {"v": 1, "assignments": {"gps.primary": {"device_id": UBLOX_ID, "alias": "smoke"}}}
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


class FakeClock:
    """Injected monotonic clock. Tests advance it; nothing sleeps for a timeout."""

    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


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

    def stop(self):
        return None


class V2Client:
    """A minimal v2 line client for tests."""

    def __init__(self, path, timeout=5):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.buf = b""
        self.counter = 0

    def send_raw(self, data: bytes) -> None:
        self.sock.sendall(data)

    def call(self, method, params=None, session=None, extra=None, version=2, req_id=None):
        self.counter += 1
        body = {"v": version, "id": req_id or f"r{self.counter}", "method": method}
        if params is not None:
            body["params"] = params
        if session is not None:
            body["session"] = session
        if extra:
            body.update(extra)
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

    def try_read(self, timeout):
        self.sock.settimeout(timeout)
        try:
            return self.read_json()
        except (socket.timeout, EOFError):
            return None

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


_HASH_CACHE = {}


def cached_hash(password):
    from task_core.passwords import hash_password

    if password not in _HASH_CACHE:
        _HASH_CACHE[password] = hash_password(password)
    return _HASH_CACHE[password]


DRAGON_PW = "dragon pass 1"
OP_PW = "op password 2"


def write_accounts(state_dir: Path, accounts: dict, mode=0o600) -> Path:
    """accounts: name -> (role, password, disabled)."""
    document = {"v": 1, "accounts": {}}
    for name, (role, password, disabled) in accounts.items():
        document["accounts"][name] = {
            "role": role,
            "hash": cached_hash(password),
            "disabled": disabled,
            "created": "2026-10-08T12:00:00Z",
        }
    path = Path(state_dir) / "accounts.json"
    tmp = path.with_name(".accounts.test.tmp")
    tmp.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return path


def default_accounts():
    return {"dragon": ("administrator", DRAGON_PW, False), "op": ("operator", OP_PW, False)}


def write_sessions(path: Path, clients, idle=None, absolute=None):
    lines = ["[clients]"]
    for uid in clients:
        lines.append(f'{int(uid)} = "test-client"')
    if idle is not None or absolute is not None:
        lines.append("[timeouts]")
        if idle is not None:
            lines.append(f"idle_seconds = {idle}")
        if absolute is not None:
            lines.append(f"absolute_seconds = {absolute}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_auth_toml(path: Path, peers: dict) -> None:
    lines = ["[peers]"]
    for uid, role in peers.items():
        lines.append(f'{int(uid)} = "{role}"')
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


import pytest  # noqa: E402


@pytest.fixture
def p2env():
    """Start a real Core (fake enumerator) with sessions.toml and accounts.json.

    Defaults model the Pi during the Phase 2 acceptance: [peers] still grants the
    test uid administrator (v1 only), the test uid is in sessions.toml [clients],
    accounts dragon (administrator) and op (operator), the golden devices, and
    the 0.1.1 devices.json fixture.
    """
    from task_core.config import Config
    from task_core.main import Core

    opened = []
    bases = []

    def start(
        devices=None,
        peers=None,
        clients=None,
        accounts="default",
        clock=None,
        sessions_file=True,
        timeouts=None,
        devices_json=True,
        peer_uid_fn=None,
        state_dir=None,
        base=None,
        do_open=True,
        **kwargs,
    ):
        if base is None:
            base = Path(tempfile.mkdtemp(prefix="rn2", dir="/tmp"))
            bases.append(base)
        if state_dir is None:
            state_dir = base / "state"
            state_dir.mkdir(exist_ok=True)
            if devices_json and not (state_dir / "devices.json").exists():
                (state_dir / "devices.json").write_bytes(fixture_devices_json())
            if accounts == "default":
                accounts = default_accounts()
            if accounts and not (state_dir / "accounts.json").exists():
                write_accounts(state_dir, accounts)
        if peers is None:
            peers = {os.geteuid(): "administrator"}
        write_auth_toml(base / "auth.toml", peers)
        sessions_path = base / "sessions.toml"
        if sessions_file is True:
            idle, absolute = (timeouts or (None, None))
            write_sessions(sessions_path, clients if clients is not None else [os.geteuid()], idle, absolute)
        clock = clock or FakeClock()
        fake = FakeEnumerator(golden_devices() if devices is None else devices)
        core = Core(
            Config(
                socket=str(base / "c.sock"),
                state_dir=Path(state_dir),
                share_dir=SHARE,
                auth_file=base / "auth.toml",
                sessions_file=sessions_path,
            ),
            enumerator_factory=lambda: fake,
            peer_uid_fn=peer_uid_fn,
            clock=clock,
            **kwargs,
        )
        core._fake = fake
        core._clock = clock
        core._base = base
        opened.append(core)
        if do_open:
            core.open()
        return core

    yield start
    for core in opened:
        try:
            core.close()
        except Exception:
            pass
    import shutil

    for base in bases:
        shutil.rmtree(base, ignore_errors=True)


def login(core, username="dragon", password=None, client=None):
    password = password if password is not None else (DRAGON_PW if username == "dragon" else OP_PW)
    own = client is None
    client = client or V2Client(core.config.socket)
    try:
        reply = client.call("session.login", {"username": username, "secret": password})
    finally:
        if own:
            client.close()
    assert reply["ok"] is True, reply
    return reply["result"]["session"]


DEVICE_KEYS = {"device_id", "by_id", "serial", "devnode", "vid", "pid", "manufacturer", "product", "class",
               "potential", "logical", "alias", "logical_devices", "assignments"}


def identifying_findings(value, path="$", in_event_data=False, topic=None):
    """Recursive scan used by tests 36, 37, 58, 65 and 80. Returns a list of findings."""
    import re

    findings = []
    patterns = [re.compile(r"dev_[0-9a-f]{16}"), re.compile(r"/dev/"), re.compile(r"by-id"),
                re.compile(r"usb-path:")]
    words = ["gps.primary", "mesh.primary", "sdr.primary", "radio.primary", "smoke"] + FIXTURE_STRINGS
    if isinstance(value, dict):
        for key, item in value.items():
            if key in DEVICE_KEYS:
                findings.append(f"{path}.{key}: forbidden key")
            if key == "id" and in_event_data and not (topic or "").startswith("module."):
                # an id inside event data is only allowed as a module id (module.* events)
                findings.append(f"{path}.id: id inside event data")
            child_topic = value.get("topic", topic) if isinstance(value.get("topic"), str) else topic
            findings += identifying_findings(item, f"{path}.{key}", in_event_data or key == "data", child_topic)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings += identifying_findings(item, f"{path}[{index}]", in_event_data, topic)
    elif isinstance(value, str):
        for pattern in patterns:
            if pattern.search(value):
                findings.append(f"{path}: value matches {pattern.pattern}")
        for word in words:
            if word in value and not (word in ("0001", "00000001") and not _standalone(value, word)):
                findings.append(f"{path}: value contains {word!r}")
    return findings


def _standalone(text, word):
    """Serial strings like 0001 are only flagged when not part of a longer number/hex id."""
    import re

    return re.search(r"(?<![0-9A-Za-z])" + re.escape(word) + r"(?![0-9A-Za-z])", text) is not None


# ---------------------------------------------------------------- task-core-admin helpers

class FakeTTY:
    """Scripted controlling terminal for confirmations (in-process runs)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.written = ""

    def write(self, text):
        self.written += text

    def flush(self):
        pass

    def readline(self):
        if not self.answers:
            return ""
        return self.answers.pop(0) + "\n"

    def close(self):
        pass


class SpyOps:
    """Records the privilege drop and runs the child inline (no fork, no real setuid)."""

    def __init__(self):
        self.calls = []

    def setgroups(self, groups):
        self.calls.append(("setgroups", list(groups)))

    def setgid(self, gid):
        self.calls.append(("setgid", gid))

    def setuid(self, uid):
        self.calls.append(("setuid", uid))

    def fork_and_wait(self, child):
        self.calls.append(("fork",))
        return child()


class FakePw:
    def __init__(self, name, uid, gid):
        self.pw_name, self.pw_uid, self.pw_gid = name, uid, gid


class FakeGr:
    def __init__(self, gid, members):
        self.gr_gid, self.gr_mem = gid, list(members)


def request_spy(core):
    """Record every v2 request the server receives: (method, carried a session, params)."""
    seen = []
    original = core.handle_v2

    def spy(payload, uid):
        seen.append((payload.get("method"), "session" in payload, dict(payload.get("params") or {})))
        return original(payload, uid)

    core.handle_v2 = spy
    return seen


def run_admin(argv, *, euid=None, passwords=(), tty=None, stdin=b"", getpwnam=None, getgrnam=None, ops=None):
    """Run task-core-admin in-process. Returns (exit code, stdout, stderr, context)."""
    import io

    from task_core import admin

    prompts = []
    answers = list(passwords)

    def fake_getpass(prompt):
        prompts.append(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)

    out, err = io.StringIO(), io.StringIO()
    ctx = admin.Context(
        geteuid=(lambda: euid) if euid is not None else os.geteuid,
        getpass=fake_getpass,
        stdin_bytes=lambda limit: stdin[:limit],
        open_tty=(lambda: tty) if tty is not None else (lambda: None),
        stdout=out,
        stderr=err,
        getpwnam=getpwnam or admin.pwd.getpwnam,
        getgrnam=getgrnam or admin.grp.getgrnam,
        ops=ops or SpyOps(),
    )
    ctx.prompts = prompts
    code = admin.main(list(argv), ctx)
    return code, out.getvalue(), err.getvalue(), ctx


def write_core_toml(base: Path, state_dir: Path, sessions_file: Path, socket_path: str) -> Path:
    path = Path(base) / "core.toml"
    path.write_text(
        f'socket = "{socket_path}"\nstate_dir = "{state_dir}"\nshare_dir = "{SHARE}"\n'
        f'auth_file = "{Path(base) / "auth.toml"}"\nsessions_file = "{sessions_file}"\n',
        encoding="utf-8",
    )
    return path
