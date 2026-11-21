# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Bundle r2 regression tests: backup.sh + healthcheck.sh end to end (off-target).

backup.sh writes the snapshot; the live files are then changed; healthcheck.sh is
run with RAIN_PRE_SNAPSHOT. systemctl and rain-smoke are stubs on PATH; v1/v2 are
answered by FakeCore, which serves a PUBLIC peer exactly like rain-core 0.2.x, and rain_core is a version stub on
PYTHONPATH. Nothing here needs root, a real service or hardware.
"""

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parent.parent
GPS = "dev_74a462923d20f21e"
SDR = "dev_ca4a208a9242de2c"
CP = "dev_ccbc25d5a4210a5a"
AUTH = b'# SPDX-License-Identifier: GPL-3.0-or-later\n[peers]\n1000 = "administrator"\n'
CORE = b'socket = "/run/rain/core.sock"\nstate_dir = "/var/lib/rain"\n'
BASE = {"gps.primary": {"device_id": GPS, "alias": "smoke"}, "sdr.primary": {"device_id": SDR, "alias": None}}


def doc(assignments):
    return (json.dumps({"v": 1, "assignments": assignments}, indent=2) + "\n").encode()


FORBIDDEN_SMOKE_DEVICES = (
    '{\n  "v": 1,\n  "id": "1",\n  "ok": false,\n  "error": {\n    "code": "forbidden",\n'
    '    "message": "device.list requires operator"\n  }\n}')


class FakeCore(threading.Thread):
    """Answers v1/v2 like rain-core 0.2.x does for a PUBLIC peer (root on the Pi is not
    in auth.toml [peers]): health/protocol/counts succeed, v1 device.list is forbidden
    (rain_core/api.py:26,135-138)."""

    def __init__(self, path, version="0.2.1"):
        super().__init__(daemon=True)
        self.version = version
        self.hotplug_state = "running"
        self.counts = {"total": 3, "connected": 2, "disconnected": 1}
        self.protocol_versions = [1, 2]
        self.health_ok = True
        self.calls = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.stop = False

    def answer(self, request):
        v, method, rid = request.get("v"), request.get("method"), request.get("id")
        self.calls.append((v, method, "session" in request))
        health = {"ok": self.health_ok, "version": self.version, "uid": 993, "uptime_seconds": 12.5}
        if method == "core.health":
            result = dict(health)
            if v == 2 and self.version == "0.2.1":
                result["hotplug"] = {"state": self.hotplug_state, "restarts": 0, "missed": 0, "events": 4,
                                     "dispatch_errors": 0, "last_error": None}
            return {"v": v, "id": rid, "ok": True, "result": result}
        if v == 2 and method == "core.protocol":
            return {"v": 2, "id": rid, "ok": True,
                    "result": {"versions": self.protocol_versions, "core": self.version, "boot_id": "b-1"}}
        if v == 2 and method == "device.counts":
            return {"v": 2, "id": rid, "ok": True, "result": dict(self.counts)}
        if method in ("device.list", "device.get", "events.recent", "device.assign", "device.unassign"):
            minimum = "administrator" if method.startswith("device.a") or method.startswith("device.u") else "operator"
            return {"v": v, "id": rid, "ok": False,
                    "error": {"code": "forbidden", "message": f"{method} requires {minimum}"}}
        return {"v": v, "id": rid, "ok": False, "error": {"code": "not-found", "message": "unknown method"}}

    def run(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            with conn:
                buf = b""
                while b"\n" not in buf:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                try:
                    reply = self.answer(json.loads(buf.split(b"\n", 1)[0]))
                except ValueError:
                    continue
                conn.sendall(json.dumps(reply).encode() + b"\n")


@pytest.fixture
def box(tmp_path):
    etc, state, backups, stub, pystub = (tmp_path / n for n in ("etc", "state", "backups", "bin", "py"))
    for d in (etc, state, backups, stub, pystub / "rain_core"):
        d.mkdir(parents=True)
    (etc / "auth.toml").write_bytes(AUTH)
    (etc / "core.toml").write_bytes(CORE)
    os.chmod(etc / "auth.toml", 0o640)
    os.chmod(etc / "core.toml", 0o644)
    (state / "devices.json").write_bytes(doc(BASE))
    os.chmod(state / "devices.json", 0o600)
    unit = tmp_path / "rain-core.service"
    unit.write_text("[Unit]\n")
    (pystub / "rain_core" / "__init__.py").write_text('__version__ = "0.2.1"\n')
    calls = tmp_path / "systemctl.calls"
    (stub / "systemctl").write_text(
        f'#!/bin/sh\necho "$*" >> {calls}\n'
        f'if [ "$1" = is-active ]; then [ -f {tmp_path}/unit-inactive ] && {{ [ "$2" = --quiet ] || echo inactive; exit 3; }}; '
        f'[ "$2" = --quiet ] || echo active; exit 0; fi\nexit 0\n')
    # rain-smoke exactly as observed on the Pi for a public peer (exit 1 on device.list)
    smoke = stub / "rain-smoke"
    smoke.write_text(f"#!/bin/sh\necho \"$*\" >> {tmp_path}/smoke.calls\ncase \"$1\" in\n"
                     " health) echo '{\"v\": 1, \"id\": \"1\", \"ok\": true, \"result\": {\"ok\": true, "
                     "\"version\": \"0.2.1\", \"uid\": 993, \"uptime_seconds\": 12.5}}' ;;\n"
                     f" devices) cat <<'J'\n{FORBIDDEN_SMOKE_DEVICES}\nJ\n exit 1 ;;\n"
                     " *) exit 2 ;;\nesac\n")
    for f in (stub / "systemctl", smoke):
        os.chmod(f, 0o755)
    sock = Path(f"/tmp/h1r3-{os.getpid()}-{id(tmp_path)}.sock")
    server = FakeCore(sock)
    server.start()
    env = dict(os.environ, PYTHON=sys.executable, PYTHONPATH=str(pystub), RAIN_STATE_DIR=str(state),
               RAIN_ETC_DIR=str(etc), RAIN_BACKUP_ROOT=str(backups), RAIN_UNIT_FILE=str(unit),
               RAIN_SMOKE=str(smoke), RAIN_SOCKET=str(sock), RAIN_ALLOW_NONROOT="1",
               RAIN_CHECK_ATTEMPTS="3", RAIN_CHECK_DELAY="0.05",
               RAIN_CORE_ADMIN=str(tmp_path / "no-such-rain-core-admin"),
               PATH=f"{stub}:{os.environ['PATH']}")
    for key in ("RAIN_PRE_SNAPSHOT", "SUDO_USER"):
        env.pop(key, None)
    yield {"etc": etc, "state": state, "devices": state / "devices.json", "env": env, "server": server,
           "tmp": tmp_path, "calls": calls, "stub": stub, "sock": sock}
    server.stop = True
    server.join(2)
    server.sock.close()
    sock.unlink(missing_ok=True)


def run(box, script, *args, snap=None, bundle=BUNDLE, stdin=None, env=None):
    full = dict(box["env"], **(env or {}))
    if snap:
        full["RAIN_PRE_SNAPSHOT"] = str(snap)
    result = subprocess.run(["bash", str(bundle / script), *args], env=full, capture_output=True, text=True,
                            timeout=60, input=stdin if stdin is not None else "", start_new_session=True)
    return result.returncode, result.stdout + result.stderr


def backup(box):
    code, out = run(box, "backup.sh")
    assert code == 0, out
    path = Path([line for line in out.splitlines() if line.startswith("BACKUP=")][-1].split("=", 1)[1])
    for name in ("auth.toml", "core.toml", "devices.json", "devices.projection.json", "STAT.txt", "SHA256SUMS"):
        assert (path / name).is_file(), name
    projection = json.loads((path / "devices.projection.json").read_text())["projection"]
    assert projection["assignments"]["gps.primary"] == {"device_id": GPS, "alias": "smoke"}
    return path


def rewrite(path, data):
    with open(path, "r+b") as handle:
        handle.truncate(0)
        handle.write(data)


def health(box, snap):
    return run(box, "healthcheck.sh", "0.2.1", snap=snap)


# ------------------------------------------------------------------ must PASS


def test_backup_records_projection_and_identical_state_passes(box):
    snap = backup(box)
    sums = (snap / "SHA256SUMS").read_text()
    assert " devices.projection.json" in sums and " STAT.txt" in sums and " SHA256SUMS" not in sums
    code, out = health(box, snap)
    assert code == 0, out
    assert "OK    auth.toml sha256" in out and "OK    core.toml owner:group:mode" in out
    assert "OK    devices.json: 2 assignment(s) preserved" in out
    assert "RESULT=PASS" in out and "SKIPPED  authenticated device.list (requires operator credentials" in out


def test_runtime_and_connection_change_passes(box):
    snap = backup(box)
    noisy = {k: dict(v, connected=False, devnode=None) for k, v in BASE.items()}
    rewrite(box["devices"], json.dumps({"v": 1, "assignments": noisy}).encode())
    code, out = health(box, snap)
    assert code == 0, out


def test_reformatted_reordered_passes(box):
    snap = backup(box)
    rewrite(box["devices"], json.dumps({"assignments": dict(reversed(list(BASE.items()))), "v": 1},
                                       separators=(",", ":")).encode())
    code, out = health(box, snap)
    assert code == 0, out
    assert "projection is identical" in out


def test_new_device_is_info(box):
    snap = backup(box)
    rewrite(box["devices"], doc(dict(BASE, **{"mesh.primary": {"device_id": CP, "alias": None}})))
    code, out = health(box, snap)
    assert code == 0, out
    assert f"INFO  new device id {CP}" in out


def test_without_snapshot_valid_file_passes(box):
    code, out = health(box, None)
    assert code == 0 and "OK    " in out, out


# ------------------------------------------------------------------ must FAIL


def test_removed_id_fails(box):
    snap = backup(box)
    rewrite(box["devices"], doc({"gps.primary": BASE["gps.primary"]}))
    code, out = health(box, snap)
    assert code == 3 and f"FAIL  device id {SDR} MISSING" in out and "RESULT=FAIL-STATE" in out


def test_changed_identity_fails(box):
    snap = backup(box)
    rewrite(box["devices"], doc(dict(BASE, **{"gps.primary": {"device_id": CP, "alias": "smoke"}})))
    code, out = health(box, snap)
    assert code == 3 and "gps.primary.device_id changed" in out


@pytest.mark.parametrize("change", ["removed", "alias"])
def test_assignment_changed_or_removed_fails(box, change):
    snap = backup(box)
    if change == "removed":
        new = {"sdr.primary": BASE["sdr.primary"]}
    else:
        new = dict(BASE, **{"gps.primary": {"device_id": GPS, "alias": None}})
    rewrite(box["devices"], doc(new))
    code, out = health(box, snap)
    assert code == 3 and "FAIL  assignment gps.primary" in out


@pytest.mark.parametrize("payload", [b'{"v": 1, "assignments": {"gps.pri', b"not json", b""])
def test_corrupt_or_truncated_fails(box, payload):
    snap = backup(box)
    rewrite(box["devices"], payload)
    code, out = health(box, snap)
    assert code == 3 and "schema check failed" in out


def test_corrupt_without_snapshot_fails(box):
    rewrite(box["devices"], b"{")
    code, out = health(box, None)
    assert code == 3 and "not valid JSON" in out and "RESULT=FAIL-STATE" in out


def test_missing_devices_json_fails(box):
    snap = backup(box)
    box["devices"].unlink()
    code, out = health(box, snap)
    assert code == 3 and "MISSING" in out


@pytest.mark.parametrize("name", ["devices.json", "auth.toml", "core.toml"])
def test_mode_change_fails(box, name):
    snap = backup(box)
    target = box["devices"] if name == "devices.json" else box["etc"] / name
    os.chmod(target, 0o666)
    code, out = health(box, snap)
    assert code == 3 and "FAIL  owner:group:mode" in out and ":666" in out


@pytest.mark.parametrize("name,data", [
    ("auth.toml", AUTH + b"\n"),                        # one trailing byte
    ("auth.toml", AUTH.replace(b"administrator", b"operator")),
    ("core.toml", CORE.replace(b"\n", b"\r\n")),        # same content, CRLF
    ("core.toml", b" " + CORE),
])
def test_any_toml_byte_change_fails(box, name, data):
    snap = backup(box)
    rewrite(box["etc"] / name, data)
    code, out = health(box, snap)
    assert code == 3 and f"FAIL  {name} sha256 changed" in out


def test_r1_snapshot_without_projection_is_refused(box):
    snap = backup(box)
    (snap / "devices.projection.json").unlink()
    code, out = health(box, snap)
    assert code == 2 and "not a usable r2/r3 snapshot" in out and "RESULT=INCOMPLETE" in out


def test_backup_refuses_an_invalid_devices_json(box):
    rewrite(box["devices"], b'{"v": 1, "assignments": {"gps.primary": {"device_id": "nope"}}}')
    code, out = run(box, "backup.sh")
    assert code == 1 and "not valid for rain-core's loader" in out
    assert not any(Path(box["env"]["RAIN_BACKUP_ROOT"]).iterdir())


def test_backup_with_absent_devices_json(box):
    box["devices"].unlink()
    code, out = run(box, "backup.sh")
    assert code == 0, out
    snap = Path([line for line in out.splitlines() if line.startswith("BACKUP=")][-1].split("=", 1)[1])
    assert (snap / "devices.json.ABSENT").is_file()
    assert json.loads((snap / "devices.projection.json").read_text())["present"] is False
    code, out = health(box, snap)
    assert code == 0 and "absent at snapshot and now" in out, out
