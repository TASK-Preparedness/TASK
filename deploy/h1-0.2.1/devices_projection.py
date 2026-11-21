#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Canonical projection of /var/lib/rain/devices.json for the H1 0.2.1 deploy scripts.

Used by backup.sh / install-0.2.1.sh / rollback-0.2.0.sh (snapshot) and
healthcheck.sh (compare) instead of a byte-level sha256 of devices.json.
Python 3 standard library only (json, os, pwd, grp, hashlib). Never writes
devices.json; only reads it (and writes the snapshot file it is told to).

What rain-core persists (release ce4766b; identical in 0.2.0 b6dd151):
  * rain_core/persist.py:72-75  save_assignments() writes exactly
        {"v": 1, "assignments": {<logical>: {"device_id": .., "alias": ..}}}
    as json.dumps(indent=2) + "\\n", via Store.replace() (persist.py:77-115:
    mkstemp in the same directory -> write -> fsync -> os.replace -> dir fsync;
    the new file is mode 0600 owned by the writing uid).
  * The only caller is Manager._write() (rain_core/devices.py:458-467), called only
    from Manager.assign() (devices.py:394) and Manager.unassign() (devices.py:432,
    also for an already-empty logical: K7, tests/test_known_behaviour.py test_43).
  * Startup only reads it (devices.py:177 -> persist.py:59-70). A corrupt file is
    copied to devices.json.corrupt.<stamp> and left in place (persist.py:117-132).
  * appear/disappear/change/apply_enumerated and the H1 resync backstop never
    write it. Device records (vid/pid/serial/devnode/connected/...) are memory only.

Consequently the list of runtime fields Core writes into devices.json is EMPTY
(RUNTIME_FIELDS below). There are no per-device identity fields on disk other
than the device_id itself (derived from hardware identity, never re-written).

Schema (mirrors the loader, persist.py:135-164, i.e. what Core itself accepts):
  top level is an object with "v" == 1 and "assignments" an object; every key is a
  logical in LOGICAL (devices.py:13); every value is an object whose "device_id"
  is "dev_" + 16 lowercase hex and whose "alias" (optional) is a string or null.
  Keys the loader ignores (extra top-level keys, extra per-entry keys) are reported
  as INFO and are not part of the projection, exactly as Core drops them.

Projection (what must survive an install/rollback):
  {"v": 1,
   "assignments": {logical: {"device_id": id, "alias": alias_or_null}},
   "device_ids": sorted(set of assigned device_ids)}

Commands:
  devices_projection.py snapshot <devices.json> <out.json>
  devices_projection.py compare  <snapshot.json> <devices.json>
  devices_projection.py validate <devices.json>        (absent file = OK)
  devices_projection.py check-list <devices.json> < rain-core-admin-devices.json
      (bundle r3) cross-check the on-disk assignments against the authenticated
      `rain-core-admin devices --json` output read from stdin.
Exit status: 0 pass, 1 check failed, 2 usage / snapshot unreadable.
check-list: 0 pass (WARN lines allowed), 2 unexpected tool output (INCOMPLETE),
            3 rain-core's device list contradicts devices.json (state).
"""

import grp
import hashlib
import json
import os
import pwd
import stat
import sys

FORMAT = "rain-h1-devices-projection/1"
LOGICAL = ("gps.primary", "mesh.primary", "sdr.primary", "radio.primary")  # rain_core/devices.py:13
RUNTIME_FIELDS = ()  # derived from code: rain-core writes no runtime fields to devices.json
ENTRY_FIELDS = ("device_id", "alias")  # persist.py:72-75 / devices.py:458-465
HEX = "0123456789abcdef"


class SchemaError(Exception):
    pass


def device_id_ok(value):
    # rain_core/persist.py:160-164
    return (isinstance(value, str) and value.startswith("dev_") and len(value) == 20
            and all(ch in HEX for ch in value[4:]))


def owner_mode(path):
    """owner:group:mode exactly as `stat -c '%U:%G:%a'` prints it."""
    st = os.stat(path)
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return "%s:%s:%s" % (owner, group, format(stat.S_IMODE(st.st_mode), "o"))


def parse(raw):
    """Return (projection, notes). Raises SchemaError with a precise reason."""
    notes = []
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise SchemaError("not UTF-8: %s" % exc)
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise SchemaError("not valid JSON (corrupt or truncated): %s" % exc)
    if not isinstance(document, dict):
        raise SchemaError("top level is %s, expected an object" % type(document).__name__)
    if document.get("v") != 1:
        raise SchemaError("\"v\" is %r, expected 1" % (document.get("v"),))
    assignments = document.get("assignments")
    if not isinstance(assignments, dict):
        raise SchemaError("\"assignments\" is %s, expected an object" % type(assignments).__name__)
    extra = sorted(set(document) - {"v", "assignments"})
    if extra:
        notes.append("top-level keys ignored by rain-core's loader: %s" % ", ".join(extra))
    cleaned = {}
    for logical, entry in assignments.items():
        if logical not in LOGICAL:
            raise SchemaError("assignment key %r is not a logical device %s" % (logical, list(LOGICAL)))
        if not isinstance(entry, dict):
            raise SchemaError("assignment %s is %s, expected an object" % (logical, type(entry).__name__))
        device_id = entry.get("device_id")
        if not device_id_ok(device_id):
            raise SchemaError("assignment %s has invalid device_id %r" % (logical, device_id))
        alias = entry.get("alias", None)
        if alias is not None and not isinstance(alias, str):
            raise SchemaError("assignment %s has non-string alias %r" % (logical, alias))
        ignored = sorted(set(entry) - set(ENTRY_FIELDS))
        if ignored:
            notes.append("assignment %s: keys ignored by rain-core's loader: %s" % (logical, ", ".join(ignored)))
        cleaned[logical] = {"device_id": device_id, "alias": alias}
    projection = {
        "v": 1,
        "assignments": {k: cleaned[k] for k in sorted(cleaned)},
        "device_ids": sorted({e["device_id"] for e in cleaned.values()}),
    }
    return projection, notes


def read_state(path):
    """Snapshot record for path (raises SchemaError if present but invalid)."""
    if not os.path.lexists(path):
        return {"format": FORMAT, "path": path, "present": False, "runtime_fields_ignored": list(RUNTIME_FIELDS)}
    if not os.path.isfile(path):
        raise SchemaError("%s exists but is not a regular file" % path)
    with open(path, "rb") as handle:
        raw = handle.read()
    projection, notes = parse(raw)
    return {
        "format": FORMAT,
        "path": path,
        "present": True,
        "owner_group_mode": owner_mode(path),
        "sha256_informational": hashlib.sha256(raw).hexdigest(),
        "projection": projection,
        "notes": notes,
        "runtime_fields_ignored": list(RUNTIME_FIELDS),
    }


def fmt(entry):
    return json.dumps(entry, sort_keys=True)


def compare(before, path, out):
    """Compare the live file at path with snapshot record before. Returns failure count."""
    failures = 0

    def fail(msg):
        nonlocal failures
        failures += 1
        out.write("FAIL  %s\n" % msg)

    def info(msg):
        out.write("INFO  %s\n" % msg)

    try:
        now = read_state(path)
    except SchemaError as exc:
        fail("%s: schema check failed: %s" % (path, exc))
        return failures
    except OSError as exc:
        fail("%s: unreadable: %s" % (path, exc))
        return failures
    for note in now.get("notes", []):
        info(note)

    if not before.get("present"):
        if now["present"]:
            info("devices.json was absent at snapshot; now present and valid (%s)" % now["owner_group_mode"])
            for logical, entry in now["projection"]["assignments"].items():
                info("new assignment %s -> %s" % (logical, fmt(entry)))
        else:
            info("devices.json absent at snapshot and now (no assignments)")
        return failures

    if not now["present"]:
        fail("%s is MISSING; snapshot had %d assignment(s): %s"
             % (path, len(before["projection"]["assignments"]), fmt(before["projection"]["assignments"])))
        return failures

    if now["owner_group_mode"] != before["owner_group_mode"]:
        fail("owner:group:mode of %s changed: before=%s now=%s"
             % (path, before["owner_group_mode"], now["owner_group_mode"]))

    old_a = before["projection"]["assignments"]
    new_a = now["projection"]["assignments"]
    for logical in sorted(old_a):
        if logical not in new_a:
            fail("assignment %s MISSING (before: %s)" % (logical, fmt(old_a[logical])))
            continue
        for field in ENTRY_FIELDS:
            if old_a[logical][field] != new_a[logical][field]:
                fail("assignment %s.%s changed: before=%s now=%s"
                     % (logical, field, json.dumps(old_a[logical][field]), json.dumps(new_a[logical][field])))
    for logical in sorted(set(new_a) - set(old_a)):
        info("new assignment %s -> %s (not in snapshot; not a failure)" % (logical, fmt(new_a[logical])))

    old_ids = set(before["projection"]["device_ids"])
    new_ids = set(now["projection"]["device_ids"])
    for device_id in sorted(old_ids - new_ids):
        held = [k for k, v in old_a.items() if v["device_id"] == device_id]
        fail("device id %s MISSING (held %s in snapshot)" % (device_id, ", ".join(held)))
    for device_id in sorted(new_ids - old_ids):
        info("new device id %s (not in snapshot; not a failure)" % device_id)

    if now["sha256_informational"] != before["sha256_informational"] and failures == 0 \
            and now["projection"] == before["projection"]:
        info("bytes differ from snapshot but the projection is identical (formatting/key order/ignored keys)")
    if failures == 0:
        out.write("OK    devices.json: %d assignment(s) preserved, owner:group:mode %s\n"
                  % (len(old_a), now["owner_group_mode"]))
    return failures


def check_list(path, text, out):
    """Validate `rain-core-admin devices --json` output and cross-check it with devices.json."""
    try:
        document = json.loads(text)
        listing = document["device.list"]
        devices = listing["devices"]
        if not isinstance(devices, list):
            raise TypeError("devices is not a list")
        by_id = {}
        for item in devices:
            if not isinstance(item, dict) or not device_id_ok(item.get("id")):
                raise TypeError("device entry without a valid id: %r" % (item,))
            if not isinstance(item.get("connected"), bool):
                raise TypeError("device %s has non-boolean connected" % item["id"])
            for key in ("logical", "alias"):
                if item.get(key) is not None and not isinstance(item.get(key), str):
                    raise TypeError("device %s has invalid %s" % (item["id"], key))
            if item.get("logical") is not None and item["logical"] not in LOGICAL:
                raise TypeError("device %s has unknown logical %r" % (item["id"], item["logical"]))
            by_id[item["id"]] = item
    except (ValueError, KeyError, TypeError) as exc:
        out.write("INCOMPLETE  rain-core-admin output is not the expected device.list JSON: %s\n" % exc)
        return 2
    try:
        state = read_state(path)
    except (SchemaError, OSError) as exc:
        out.write("FAIL  %s: %s\n" % (path, exc))
        return 3
    assignments = state.get("projection", {}).get("assignments", {}) if state["present"] else {}
    failures = 0
    for logical, entry in sorted(assignments.items()):
        item = by_id.get(entry["device_id"])
        if item is None:
            out.write("FAIL  %s -> %s (devices.json) is absent from rain-core's device.list\n"
                      % (logical, entry["device_id"]))
            failures += 1
            continue
        if item.get("logical") != logical or item.get("alias") != entry["alias"]:
            out.write("FAIL  %s -> %s: rain-core reports logical=%r alias=%r, devices.json has alias=%r\n"
                      % (logical, entry["device_id"], item.get("logical"), item.get("alias"), entry["alias"]))
            failures += 1
            continue
        if item["connected"]:
            out.write("OK    %s -> %s alias=%s connected\n" % (logical, entry["device_id"], json.dumps(entry["alias"])))
        else:
            out.write("WARN  %s -> %s alias=%s assigned but DISCONNECTED (hardware unplugged?)\n"
                      % (logical, entry["device_id"], json.dumps(entry["alias"])))
    for item in sorted(by_id.values(), key=lambda d: d["id"]):
        if item.get("logical") and item["logical"] not in assignments:
            out.write("FAIL  rain-core reports %s -> %s but devices.json has no such assignment\n"
                      % (item["logical"], item["id"]))
            failures += 1
    connected = sum(1 for d in by_id.values() if d["connected"])
    out.write("INFO  device.list: %d device(s), %d connected, %d assignment(s) checked\n"
              % (len(by_id), connected, len(assignments)))
    return 3 if failures else 0


def main(argv):
    if len(argv) == 4 and argv[1] == "snapshot":
        try:
            record = read_state(argv[2])
        except (SchemaError, OSError) as exc:
            sys.stderr.write("FAIL  %s: %s\n" % (argv[2], exc))
            return 1
        data = json.dumps(record, indent=2, sort_keys=True) + "\n"
        with open(argv[3], "w", encoding="utf-8") as handle:
            handle.write(data)
        sys.stdout.write(data)
        return 0
    if len(argv) == 4 and argv[1] == "compare":
        try:
            with open(argv[2], encoding="utf-8") as handle:
                before = json.load(handle)
            if before.get("format") != FORMAT:
                raise ValueError("unknown snapshot format %r" % before.get("format"))
        except (OSError, ValueError) as exc:
            sys.stderr.write("FAIL  snapshot %s unreadable: %s\n" % (argv[2], exc))
            return 2
        return 1 if compare(before, argv[3], sys.stdout) else 0
    if len(argv) == 3 and argv[1] == "validate":
        try:
            record = read_state(argv[2])
        except (SchemaError, OSError) as exc:
            sys.stdout.write("FAIL  %s: %s\n" % (argv[2], exc))
            return 1
        for note in record.get("notes", []):
            sys.stdout.write("INFO  %s\n" % note)
        if record["present"]:
            sys.stdout.write("OK    %s valid: %s\n" % (argv[2], fmt(record["projection"]["assignments"])))
        else:
            sys.stdout.write("OK    %s absent (no assignments)\n" % argv[2])
        return 0
    if len(argv) == 3 and argv[1] == "check-list":
        return check_list(argv[2], sys.stdin.read(), sys.stdout)
    sys.stderr.write(__doc__.split("Commands:")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
