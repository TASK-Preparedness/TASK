# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PHASE-2.md tests 1, 5, 7 (compatibility) and 43-45 (known behaviour pinned: K7, K2, K6)."""

import hashlib
import os
from pathlib import Path

from task_core.config import load_config
from task_core.devices import RawDevice, identity_for, make_id

from conftest import LineClient
from p2fixtures import (CP2102_ID, SDR_ID, UBLOX_ID, V2Client, cp2102, fixture_devices_json, golden_devices,  # noqa
                        login, p2env, rtlsdr, ublox)

ROOT = Path(__file__).resolve().parents[1]

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_01_phase1_test_files_unchanged():
    """sha256 of every Phase 1 test file at tag phase1-accepted (b12e5fd), recorded in
    golden/phase1_tests.sha256.json. Phase 4C renamed rain->task: each file must now equal the mechanical
    rebrand (tests/rebrand_map.py) of that recorded original, recorded in golden/phase4c_rebranded_tests.sha256.json.
    test_not_root.py is recorded with its 0.2.1 content (line 19's version literal, PHASE-2.md 14.1)."""
    import json
    import subprocess

    from rebrand_map import rebrand_text

    manifest = json.loads((ROOT / "tests" / "golden" / "phase1_tests.sha256.json").read_text())
    rebranded = json.loads((ROOT / "tests" / "golden" / "phase4c_rebranded_tests.sha256.json").read_text())
    assert len(manifest["files"]) == 14 and set(rebranded["files"]) == set(manifest["files"])
    for name, digest in rebranded["files"].items():
        assert _sha(ROOT / "tests" / name) == digest, name
        out = subprocess.run(["git", "show", f"phase1-accepted:tests/{name}"], cwd=ROOT, capture_output=True)
        if out.returncode == 0 and name != "test_not_root.py":
            assert hashlib.sha256(out.stdout).hexdigest() == manifest["files"][name], name
            assert rebrand_text(out.stdout.decode()).encode() == (ROOT / "tests" / name).read_bytes(), name
    text = (ROOT / "tests" / "test_not_root.py").read_text().splitlines()
    assert text[18] == '    assert health["result"]["version"] == "0.2.1"'


def test_05_state_compatibility_and_golden_ids(p2env):
    assert [make_id(identity_for(raw)[0]) for raw in golden_devices()] == [UBLOX_ID, SDR_ID, CP2102_ID]
    assert identity_for(rtlsdr())[0] == "usb:0bda:2838:00000001"
    core = p2env()
    path = core.config.state_dir / "devices.json"
    original, inode = fixture_devices_json(), os.stat(path).st_ino
    assert path.read_bytes() == original
    v1 = LineClient(core.config.socket)
    assignments = v1.request("device.list")["result"]["assignments"]
    assert assignments == {"gps.primary": {"device_id": UBLOX_ID, "alias": "smoke", "connected": True}}
    gps = core._fake.devices[0]
    for _ in range(3):
        core._fake.remove(gps)
        core._fake.add(gps)
    assert path.read_bytes() == original and os.stat(path).st_ino == inode
    # assign/unassign round trip returns to the same document
    token = login(core)
    v2 = V2Client(core.config.socket)
    v2.call("device.assign", {"logical": "sdr.primary", "device_id": SDR_ID}, session=token)
    v2.call("device.unassign", {"logical": "sdr.primary"}, session=token)
    assert path.read_bytes() == original
    # 0.1.1 auth.toml and core.toml load unchanged
    core_toml = (ROOT / "deploy" / "core.toml").read_bytes()
    auth_toml = (ROOT / "deploy" / "auth.toml").read_bytes()
    config = load_config(ROOT / "deploy" / "core.toml")
    assert config.sessions_file is None and str(config.state_dir) == "/var/lib/rain"
    from task_core.auth import load_auth

    load_auth(ROOT / "deploy" / "auth.toml")
    assert (ROOT / "deploy" / "core.toml").read_bytes() == core_toml
    assert (ROOT / "deploy" / "auth.toml").read_bytes() == auth_toml
    v1.close()
    v2.close()


# sha256 at phase1-accepted (PHASE-2.md test 7)
FROZEN_DEPLOY = {
    "deploy/rain-core.service": None,
    "deploy/tmpfiles.d/rain.conf": None,
    "deploy/rain-smoke.py": None,
    "deploy/pi-install.sh": None,
}


def test_07_unit_and_deploy_files_byte_identical():
    import json

    manifest = json.loads((ROOT / "tests" / "golden" / "phase1_tests.sha256.json").read_text())
    for name, digest in manifest["deploy"].items():
        assert _sha(ROOT / name) == digest, name
    assert set(manifest["deploy"]) == set(FROZEN_DEPLOY)


def test_43_k7_unassign_empty_logical(p2env):
    """K7 (F3): unassigning an empty logical returns ok, emits device.unassigned and rewrites the file."""
    core = p2env()
    path = core.config.state_dir / "devices.json"
    v1 = LineClient(core.config.socket)
    token = login(core)
    v2 = V2Client(core.config.socket)
    for call in (lambda: v1.request("device.unassign", {"logical": "radio.primary"}),
                 lambda: v2.call("device.unassign", {"logical": "radio.primary"}, session=token)):
        inode = os.stat(path).st_ino
        seq = core.bus.last_seq()
        reply = call()
        assert reply["result"] == {"logical": "radio.primary", "device_id": None}
        events = [e for e in core.bus.recent_v2() if e["seq"] > seq]
        assert [e["topic"] for e in events] == ["device.unassigned"]
        assert os.stat(path).st_ino != inode  # rewritten
        assert path.read_bytes() == fixture_devices_json()
    v1.close()
    v2.close()


def test_44_k2_identical_units_share_one_id():
    """K2 (F6), known behaviour: identical factory serials / model-only by-id collide.

    Two CP2102 adapters with serial 0001 produce one id, and two u-blox 7 receivers
    (no iSerial; model-only by-id) produce one id. Changing this would change the frozen
    identity derivation and could re-key stored assignments; a change must be deliberate.
    """
    first, second = cp2102("/dev/ttyUSB0"), cp2102("/dev/ttyUSB1")
    second.bus_path = "platform-xhci-hcd.0-usb-0:2"
    assert make_id(identity_for(first)[0]) == make_id(identity_for(second)[0]) == CP2102_ID
    gps_a, gps_b = ublox("/dev/ttyACM0"), ublox("/dev/ttyACM1")
    gps_b.bus_path = "platform-xhci-hcd.1-usb-0:2"
    assert make_id(identity_for(gps_a)[0]) == make_id(identity_for(gps_b)[0]) == UBLOX_ID


def test_45_k6_rereported_parent_stays_until_restart(env):
    """K6: a parent re-reported after its tty went away, then unplugged, stays a disconnected
    record until restart. An assigned parent is never deleted (0.1.1 behaviour)."""
    from test_hotplug_parent_dedup import UBLOX_GHOST_ID, UBLOX_TTY_ID, boot, by_id, ids
    from test_hotplug_parent_dedup import ublox as udev_ublox

    parent, tty = udev_ublox()
    core, enum, client = boot(env, [parent, tty])
    enum._dispatch(tty.at("remove"))
    enum._dispatch(parent.at("change"))
    assert by_id(client, UBLOX_GHOST_ID)["connected"] is True
    enum._dispatch(parent.at("unbind"))
    enum._dispatch(parent.at("remove"))
    ghost = by_id(client, UBLOX_GHOST_ID)
    assert ghost is not None and ghost["connected"] is False
    assert sorted(ids(client)) == sorted([UBLOX_GHOST_ID, UBLOX_TTY_ID])
    client.close()
    state = core.config.state_dir
    core.close()
    again, _enum, client = boot(env, [], state_dir=state)
    assert ids(client) == []
    client.close()
