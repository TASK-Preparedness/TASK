# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Bundle r2 regression tests for devices_projection.py (the devices.json check).

Run from the repository root:  python3 -m pytest -q deploy/h1-0.2.1/tests
(not part of tests/ so the rain-core suite count is unchanged).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
sys.path.insert(0, str(BUNDLE))
import devices_projection as dp  # noqa: E402

GPS = "dev_74a462923d20f21e"
SDR = "dev_ca4a208a9242de2c"
CP = "dev_ccbc25d5a4210a5a"


def doc(assignments):
    """devices.json exactly as rain-core writes it (persist.py:72-75)."""
    return (json.dumps({"v": 1, "assignments": assignments}, indent=2) + "\n").encode()


BASE = {"gps.primary": {"device_id": GPS, "alias": "smoke"}, "sdr.primary": {"device_id": SDR, "alias": None}}


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "devices.json"
    path.write_bytes(doc(BASE))
    os.chmod(path, 0o600)
    snap = tmp_path / "devices.projection.json"
    return path, snap


def cli(*args):
    return subprocess.run([sys.executable, str(BUNDLE / "devices_projection.py"), *map(str, args)],
                          capture_output=True, text=True)


def take(path, snap):
    result = cli("snapshot", path, snap)
    assert result.returncode == 0, result.stderr
    return json.loads(snap.read_text())


def check(path, snap):
    result = cli("compare", snap, path)
    return result.returncode, result.stdout + result.stderr


def rewrite(path, data):
    """Replace content in place (keeps inode, owner and mode)."""
    with open(path, "r+b") as handle:
        handle.truncate(0)
        handle.write(data)


# ------------------------------------------------------------------ must PASS


def test_identical_file_passes(state):
    path, snap = state
    record = take(path, snap)
    assert record["projection"]["assignments"] == {k: BASE[k] for k in sorted(BASE)}
    assert record["projection"]["device_ids"] == sorted([GPS, SDR])
    assert record["owner_group_mode"].endswith(":600")
    assert record["runtime_fields_ignored"] == []
    code, out = check(path, snap)
    assert code == 0, out
    assert "OK    devices.json: 2 assignment(s) preserved" in out


def test_connection_or_runtime_change_passes(state):
    """rain-core persists no runtime fields (devices.py:458-467). Keys its loader ignores
    (e.g. connected/last_seen/devnode, if any writer ever added them) must not fail."""
    path, snap = state
    take(path, snap)
    noisy = {k: dict(v, connected=False, last_seen="2026-10-08T21:00:00Z", devnode=None) for k, v in BASE.items()}
    rewrite(path, json.dumps({"v": 1, "assignments": noisy, "devices": {GPS: {"connected": False}}}).encode())
    code, out = check(path, snap)
    assert code == 0, out
    assert "ignored by rain-core's loader" in out
    assert "projection is identical" in out


def test_reformatted_and_reordered_json_passes(state):
    path, snap = state
    take(path, snap)
    reordered = {"assignments": {"sdr.primary": {"alias": None, "device_id": SDR},
                                 "gps.primary": {"alias": "smoke", "device_id": GPS}}, "v": 1}
    rewrite(path, json.dumps(reordered, separators=(",", ":")).encode())  # compact, no newline
    code, out = check(path, snap)
    assert code == 0, out
    assert "bytes differ from snapshot but the projection is identical" in out


def test_new_device_and_new_assignment_are_info(state):
    path, snap = state
    take(path, snap)
    rewrite(path, doc(dict(BASE, **{"mesh.primary": {"device_id": CP, "alias": "lora"}})))
    code, out = check(path, snap)
    assert code == 0, out
    assert f"INFO  new device id {CP}" in out
    assert "INFO  new assignment mesh.primary" in out
    assert "FAIL" not in out


def test_absent_before_and_after_passes(tmp_path):
    path, snap = tmp_path / "devices.json", tmp_path / "snap.json"
    assert take(path, snap)["present"] is False
    code, out = check(path, snap)
    assert code == 0 and "absent at snapshot and now" in out


def test_absent_before_present_after_is_info(tmp_path):
    path, snap = tmp_path / "devices.json", tmp_path / "snap.json"
    take(path, snap)
    path.write_bytes(doc({"gps.primary": {"device_id": GPS, "alias": None}}))
    code, out = check(path, snap)
    assert code == 0 and "INFO  new assignment gps.primary" in out


def test_identical_rewrite_by_core_with_same_mode_passes(state):
    """An atomic rewrite (new inode, same bytes, same mode) is not a change."""
    path, snap = state
    take(path, snap)
    tmp = path.with_name(".devices.json.x.tmp")
    tmp.write_bytes(doc(BASE))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    code, out = check(path, snap)
    assert code == 0, out


# ------------------------------------------------------------------ must FAIL


def test_removed_device_id_fails(state):
    path, snap = state
    take(path, snap)
    rewrite(path, doc({"gps.primary": BASE["gps.primary"]}))
    code, out = check(path, snap)
    assert code == 1
    assert f"FAIL  device id {SDR} MISSING (held sdr.primary in snapshot)" in out
    assert "FAIL  assignment sdr.primary MISSING" in out


def test_changed_identity_field_fails(state):
    """The only identity field on disk is device_id (no vid/pid/serial are persisted)."""
    path, snap = state
    take(path, snap)
    rewrite(path, doc(dict(BASE, **{"gps.primary": {"device_id": CP, "alias": "smoke"}})))
    code, out = check(path, snap)
    assert code == 1
    assert f'FAIL  assignment gps.primary.device_id changed: before="{GPS}" now="{CP}"' in out
    assert f"FAIL  device id {GPS} MISSING" in out


def test_changed_alias_fails(state):
    path, snap = state
    take(path, snap)
    rewrite(path, doc(dict(BASE, **{"gps.primary": {"device_id": GPS, "alias": "other"}})))
    code, out = check(path, snap)
    assert code == 1 and 'FAIL  assignment gps.primary.alias changed: before="smoke" now="other"' in out


def test_assignment_moved_to_another_role_fails(state):
    path, snap = state
    take(path, snap)
    rewrite(path, doc({"gps.primary": BASE["gps.primary"], "radio.primary": BASE["sdr.primary"]}))
    code, out = check(path, snap)
    assert code == 1 and "FAIL  assignment sdr.primary MISSING" in out
    assert "INFO  new assignment radio.primary" in out


def test_all_assignments_removed_fails(state):
    path, snap = state
    take(path, snap)
    rewrite(path, doc({}))
    code, out = check(path, snap)
    assert code == 1 and out.count("FAIL  assignment") == 2


@pytest.mark.parametrize("payload,reason", [
    (b'{"v": 1, "assignments": {"gps.primary": {"device_id": "dev_74a4', "not valid JSON"),  # truncated
    (b"", "not valid JSON"),
    (b"\x00\x00\x00\x00", "not valid JSON"),
    (b"\xff\xfe{}", "not UTF-8"),
    (b"[]", "top level is list"),
    (b'{"v": 2, "assignments": {}}', '"v" is 2'),
    (b'{"v": 1}', '"assignments" is NoneType'),
    (b'{"v": 1, "assignments": {"gps.secondary": {"device_id": "dev_74a462923d20f21e"}}}', "not a logical device"),
    (b'{"v": 1, "assignments": {"gps.primary": {"device_id": "dev_74A462923D20F21E"}}}', "invalid device_id"),
    (b'{"v": 1, "assignments": {"gps.primary": {"device_id": "dev_74a462923d20f21e", "alias": 7}}}', "non-string alias"),
    (b'{"v": 1, "assignments": {"gps.primary": "dev_74a462923d20f21e"}}', "expected an object"),
])
def test_corrupt_truncated_or_schema_mismatch_fails(state, payload, reason):
    path, snap = state
    take(path, snap)
    rewrite(path, payload)
    code, out = check(path, snap)
    assert code == 1 and "schema check failed" in out and reason in out, out


def test_missing_file_fails(state):
    path, snap = state
    take(path, snap)
    path.unlink()
    code, out = check(path, snap)
    assert code == 1 and "MISSING; snapshot had 2 assignment(s)" in out


def test_mode_change_fails(state):
    path, snap = state
    take(path, snap)
    os.chmod(path, 0o644)
    code, out = check(path, snap)
    assert code == 1 and "FAIL  owner:group:mode" in out and ":600 now=" in out and ":644" in out


def test_atomic_rewrite_with_new_mode_fails(state):
    """rain-core's own rewrite (mkstemp -> 0600) of a file that was 0640 is an owner/mode change."""
    path, snap = state
    os.chmod(path, 0o640)
    take(path, snap)
    tmp = path.with_name(".devices.json.y.tmp")
    tmp.write_bytes(doc(BASE))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    code, out = check(path, snap)
    assert code == 1 and "before=" in out and ":640 now=" in out


def test_owner_change_fails(state):
    """chown needs root; simulate by recording a different owner in the snapshot."""
    path, snap = state
    record = take(path, snap)
    owner, group, mode = record["owner_group_mode"].split(":")
    record["owner_group_mode"] = f"rain-core:{group}:{mode}" if owner != "rain-core" else f"root:{group}:{mode}"
    snap.write_text(json.dumps(record))
    code, out = check(path, snap)
    assert code == 1 and "FAIL  owner:group:mode" in out


def test_invalid_file_cannot_be_snapshotted(tmp_path):
    path = tmp_path / "devices.json"
    path.write_bytes(b"{")
    result = cli("snapshot", path, tmp_path / "s.json")
    assert result.returncode == 1 and "not valid JSON" in result.stderr
    assert not (tmp_path / "s.json").exists()


def test_unknown_snapshot_format_is_rejected(state):
    path, snap = state
    snap.write_text('{"format": "something-else"}')
    code, out = check(path, snap)
    assert code == 2 and "unknown snapshot format" in out


def test_validate(state, tmp_path):
    path, _snap = state
    assert cli("validate", path).returncode == 0
    assert cli("validate", tmp_path / "nope.json").returncode == 0
    path.write_bytes(b'{"v": 1, "assignments": []}')
    assert cli("validate", path).returncode == 1


def test_schema_mirrors_rain_core_loader():
    """The schema constants are the ones in rain_core (devices.py:13, persist.py:160-164)."""
    root = BUNDLE.parent.parent
    if not (root / "rain_core").is_dir():
        pytest.skip("rain_core source not alongside")
    sys.path.insert(0, str(root))
    from rain_core import devices, persist

    assert tuple(devices.LOGICAL) == dp.LOGICAL
    for value in (GPS, "dev_" + "0" * 16, "dev_" + "g" * 16, "dev_ABC", "dex_" + "a" * 16, GPS.upper()):
        assert persist._device_id_ok(value) == dp.device_id_ok(value), value


@pytest.mark.parametrize("payload", [
    doc(BASE),
    json.dumps({"assignments": {"sdr.primary": {"alias": None, "device_id": SDR}}, "v": 1, "extra": 1}).encode(),
    json.dumps({"v": 1, "assignments": {"gps.primary": {"device_id": GPS, "connected": True}}}).encode(),
    b'{"v": 1, "assignments": {"gps.primary": {"device_id": "dev_74a4',
    b"[]",
    b'{"v": 2, "assignments": {}}',
    b'{"v": 1, "assignments": {"gps.secondary": {"device_id": "dev_74a462923d20f21e"}}}',
    b'{"v": 1, "assignments": {"gps.primary": {"device_id": "dev_74a462923d20f21e", "alias": 7}}}',
    b'{"v": 1, "assignments": {"gps.primary": "x"}}',
])
def test_accepts_exactly_what_rain_core_loader_accepts(payload):
    root = BUNDLE.parent.parent
    if not (root / "rain_core").is_dir():
        pytest.skip("rain_core source not alongside")
    sys.path.insert(0, str(root))
    from rain_core import persist

    try:
        core = persist._valid_assignments(json.loads(payload.decode()))
    except (ValueError, UnicodeError):
        core = None
    try:
        mine = dp.parse(payload)[0]["assignments"]
    except dp.SchemaError:
        mine = None
    assert (core is None) == (mine is None)
    if core is not None:
        assert core == mine


# ------------------------------------------------------------------ r3: check-list
# Input is `rain-core-admin devices --json` (admin_client.py:465-475 -> {"device.list": ...});
# each device is Device.public() (devices.py:91-107: id, connected, logical, alias, ...).


def listing_text(devices):
    return json.dumps({"device.list": {"devices": devices}}, indent=2, sort_keys=True) + "\n"


def dev(device_id, connected, logical=None, alias=None):
    return {"id": device_id, "connected": connected, "logical": logical, "alias": alias, "class": "x",
            "identity_stable": True}


def check_list(path, text):
    result = subprocess.run([sys.executable, str(BUNDLE / "devices_projection.py"), "check-list", str(path)],
                            input=text, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def test_check_list_all_connected_passes(state):
    path, _ = state
    code, out = check_list(path, listing_text([dev(GPS, True, "gps.primary", "smoke"),
                                               dev(SDR, True, "sdr.primary"), dev(CP, True)]))
    assert code == 0 and out.count("OK    ") == 2 and "3 device(s), 3 connected, 2 assignment(s)" in out


def test_check_list_unplugged_sdr_is_warn_not_failure(state):
    """The Pi today: RTL-SDR unplugged, assignment kept (placeholder, devices.py:180-199)."""
    path, _ = state
    code, out = check_list(path, listing_text([dev(GPS, True, "gps.primary", "smoke"),
                                               dev(SDR, False, "sdr.primary")]))
    assert code == 0 and "WARN  sdr.primary -> %s alias=null assigned but DISCONNECTED" % SDR in out


@pytest.mark.parametrize("devices,needle", [
    ([dev(SDR, True, "sdr.primary")], "absent from rain-core's device.list"),
    ([dev(GPS, True, "gps.primary", "other"), dev(SDR, True, "sdr.primary")], "rain-core reports logical='gps.primary' alias='other'"),
    ([dev(GPS, True, None), dev(SDR, True, "sdr.primary")], "rain-core reports logical=None"),
    ([dev(GPS, True, "gps.primary", "smoke"), dev(SDR, True, "sdr.primary"), dev(CP, True, "mesh.primary")],
     "rain-core reports mesh.primary -> %s but devices.json has no such assignment" % CP),
])
def test_check_list_contradiction_is_fail_state(state, devices, needle):
    path, _ = state
    code, out = check_list(path, listing_text(devices))
    assert code == 3 and needle in out, out


@pytest.mark.parametrize("text", [
    "", "not json", "[]", "{}", json.dumps({"device.list": {}}), json.dumps({"device.list": {"devices": {}}}),
    listing_text([{"connected": True}]), listing_text([dict(dev(GPS, True), connected="yes")]),
    listing_text([dict(dev(GPS, True), alias=5)]), listing_text([dev(GPS, True, "bogus.logical")]),
])
def test_check_list_unexpected_output_is_incomplete(state, text):
    path, _ = state
    code, out = check_list(path, text)
    assert code == 2 and out.startswith("INCOMPLETE  rain-core-admin output is not the expected device.list JSON"), out


def test_check_list_no_assignments_file_passes(tmp_path):
    code, out = check_list(tmp_path / "devices.json", listing_text([dev(CP, True)]))
    assert code == 0 and "0 assignment(s) checked" in out
