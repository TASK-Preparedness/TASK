# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Bundle r3 regression tests: no unauthenticated device.list, distinct exit codes,
optional authenticated check, and the installer never stopping a running rain-core.

Pi evidence (2026-10-09): `sudo rain-smoke devices` -> ok:false forbidden
"device.list requires operator", exit 1; r2 healthcheck.sh:63 ran it under set -e and
install-0.2.1.sh:104-106 then stopped a healthy rain-core.
"""

import json
import re
import os
import stat
import subprocess
from pathlib import Path

import pytest

from test_healthcheck_script import (  # noqa: F401  (fixture + helpers)
    BASE, BUNDLE, GPS, SDR, backup, box, doc, health, rewrite, run,
)

REPO = BUNDLE.parent.parent
DRAGON_SECRET = "pw-typed-by-operator-7f3a"   # test data only


def r2_bundle(tmp_path):
    """The r2 scripts exactly as committed in 3b0083b (the version that ran on the Pi)."""
    out = tmp_path / "r2"
    out.mkdir()
    for name in ("healthcheck.sh", "_rain_h1_common.sh", "devices_projection.py"):
        data = subprocess.run(["git", "-C", str(REPO), "show", f"3b0083b:deploy/h1-0.2.1/{name}"],
                              capture_output=True, check=True).stdout
        (out / name).write_bytes(data)
    return out


def admin_stub(box, body, rc=0):
    """A stand-in rain-core-admin that records argv/env and prints `body`."""
    path = box["tmp"] / "rain-core-admin"
    record = box["tmp"] / "admin.record"
    path.write_text(f"""#!/usr/bin/env python3
import json, os, sys
stdin = sys.stdin.read() if "--password-stdin" in sys.argv else None
with open({str(record)!r}, "w") as h:
    json.dump({{"argv": sys.argv[1:], "env": dict(os.environ), "stdin": stdin}}, h)
sys.stdout.write({body!r})
sys.exit({rc})
""")
    os.chmod(path, 0o755)
    return path, record


def listing(devices):
    return json.dumps({"device.list": {"devices": devices}}, indent=2, sort_keys=True) + "\n"


GOOD = [
    {"id": GPS, "connected": True, "logical": "gps.primary", "alias": "smoke", "class": "gps"},
    {"id": SDR, "connected": False, "logical": "sdr.primary", "alias": None, "class": "sdr"},
    {"id": "dev_ccbc25d5a4210a5a", "connected": True, "logical": None, "alias": None, "class": "unknown"},
]


# ------------------------------------------------------------ the Pi defect itself


def test_r2_healthcheck_fails_on_forbidden_device_list(box, tmp_path):
    """Would have caught the Pi defect: r2 exits 1 at `rain-smoke devices` (forbidden)."""
    old = r2_bundle(tmp_path)
    code, out = run(box, "healthcheck.sh", "0.2.1", bundle=old)
    # set -e kills r2 inside LIST="$("$SMOKE" devices)" (r2 healthcheck.sh:62-63): the
    # forbidden reply is swallowed and the script dies right after v2 health, exit 1.
    assert code == 1
    assert out.rstrip().endswith("[healthcheck] v2 core.health OK"), out
    assert "healthcheck passed" not in out
    assert "devices" in (box["tmp"] / "smoke.calls").read_text()


def test_r3_passes_where_r2_failed_and_never_calls_device_list(box):
    code, out = health(box, None)
    assert code == 0 and "RESULT=PASS" in out, out
    methods = {(v, m) for v, m, _session in box["server"].calls}
    assert (1, "device.list") not in methods and (2, "device.list") not in methods
    assert {(1, "core.health"), (2, "core.health"), (2, "core.protocol"), (2, "device.counts")} <= methods
    assert not any(session for _v, _m, session in box["server"].calls)
    assert "SKIPPED  authenticated device.list (requires operator credentials" in out


def test_no_deploy_script_calls_an_operator_only_v1_method():
    # comments and `quoted` prose may name the old call; code may not
    texts = {p.name: re.sub(r"`[^`]*`", "", "\n".join(l for l in p.read_text().splitlines()
                                                        if not l.lstrip().startswith("#")))
             for p in BUNDLE.iterdir() if p.suffix in (".sh", ".py")}
    for name, text in texts.items():
        assert '"$SMOKE" devices' not in text and "rain-smoke devices" not in text, name
        for method in ("device.list", "device.get", "events.recent", "device.assign", "device.unassign"):
            assert f'call(1, "{method}"' not in text, (name, method)


def test_r3_does_not_need_rain_smoke(box):
    os.unlink(box["stub"] / "rain-smoke")
    code, out = health(box, None)
    assert code == 0 and "RESULT=PASS" in out, out


def test_r3_does_not_need_set_e_tolerance(box):
    text = (BUNDLE / "healthcheck.sh").read_text()
    assert "set -uo pipefail" in text and "set -euo pipefail" not in text


# ------------------------------------------------------------ Core unhealthy -> FAIL-CORE (1)


@pytest.mark.parametrize("breakage,needle", [
    ("hotplug-stopped", "hotplug.state='stopped' is not alive"),
    ("hotplug-disabled", "hotplug.state='disabled' is not alive"),
    ("wrong-version", "version='0.2.0', expected '0.2.1'"),
    ("health-not-ok", "result.ok=False"),
    ("bad-counts", "device.counts inconsistent"),
    ("bad-protocol", "core.protocol versions=[1]"),
    ("socket-gone", "failed after 3 attempts"),
    ("unit-inactive", "unit rain-core is not active"),
])
def test_unhealthy_core_is_fail_core(box, breakage, needle):
    server = box["server"]
    if breakage.startswith("hotplug-"):
        server.hotplug_state = breakage.split("-", 1)[1]
    elif breakage == "wrong-version":
        server.version = "0.2.0"
    elif breakage == "health-not-ok":
        server.health_ok = False
    elif breakage == "bad-counts":
        server.counts = {"total": 5, "connected": 1, "disconnected": 1}
    elif breakage == "bad-protocol":
        server.protocol_versions = [1]
    elif breakage == "socket-gone":
        os.unlink(box["sock"])
    elif breakage == "unit-inactive":
        (box["tmp"] / "unit-inactive").write_text("")
    code, out = health(box, None)
    assert code == 1 and "RESULT=FAIL-CORE" in out, out
    assert needle in out, out
    assert "stop" not in box["calls"].read_text().split()


def test_counts_below_assignments_is_fail_state(box):
    box["server"].counts = {"total": 1, "connected": 1, "disconnected": 0}  # 2 ids assigned in BASE
    code, out = health(box, None)
    assert code == 3 and "total < 2 assigned device id(s)" in out and "RESULT=FAIL-STATE" in out, out


# ------------------------------------------------------------ optional authenticated check


def test_authenticated_ok_with_password_stdin(box):
    path, record = admin_stub(box, listing(GOOD))
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon", "--password-stdin",
                    stdin=DRAGON_SECRET + "\n", env={"RAIN_CORE_ADMIN": str(path)})
    assert code == 0 and "RESULT=PASS" in out, out
    assert 'OK    gps.primary -> dev_74a462923d20f21e alias="smoke" connected' in out
    assert "WARN  sdr.primary -> dev_ca4a208a9242de2c alias=null assigned but DISCONNECTED" in out
    seen = json.loads(record.read_text())
    assert seen["argv"][:4] == ["devices", "--user", "dragon", "--json"] and "--password-stdin" in seen["argv"]
    assert seen["stdin"] == DRAGON_SECRET + "\n"            # handed straight through, once
    assert DRAGON_SECRET not in json.dumps(seen["argv"]) + json.dumps(seen["env"])
    assert DRAGON_SECRET not in out
    leftovers = [p for p in box["tmp"].rglob("*") if p.is_file() and p != record
                 and DRAGON_SECRET.encode() in p.read_bytes()]
    assert leftovers == []


@pytest.mark.parametrize("rc,needle", [
    (3, "authentication or authorization refused (exit 3)"),
    (4, "could not reach rain-core"),
    (5, "cancelled (exit 5)"),
    (1, "rain-core-admin exited 1"),
])
def test_authenticated_tool_errors_are_incomplete(box, rc, needle):
    path, _record = admin_stub(box, "", rc=rc)
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon", "--password-stdin",
                    stdin="wrong\n", env={"RAIN_CORE_ADMIN": str(path)})
    assert code == 2 and "RESULT=INCOMPLETE" in out and needle in out, out
    assert "stop" not in box["calls"].read_text().split()


def test_authenticated_tool_missing_is_incomplete(box):
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon", "--password-stdin",
                    stdin="x\n")
    assert code == 2 and "rain-core-admin not found" in out and "RESULT=INCOMPLETE" in out, out


@pytest.mark.parametrize("body", ["not json", "{}", json.dumps({"device.list": {"devices": [{"id": "x"}]}}),
                                  json.dumps({"device.list": {"devices": "nope"}})])
def test_authenticated_unexpected_output_is_incomplete(box, body):
    path, _record = admin_stub(box, body)
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon", "--password-stdin",
                    stdin="x\n", env={"RAIN_CORE_ADMIN": str(path)})
    assert code == 2 and "not the expected device.list JSON" in out, out


def test_authenticated_contradiction_is_fail_state(box):
    wrong = [dict(GOOD[0], alias="other"), GOOD[1], GOOD[2]]
    path, _record = admin_stub(box, listing(wrong))
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon", "--password-stdin",
                    stdin="x\n", env={"RAIN_CORE_ADMIN": str(path)})
    assert code == 3 and "FAIL  gps.primary -> dev_74a462923d20f21e: rain-core reports" in out, out


def test_authenticated_missing_assigned_device_is_fail_state(box):
    path, _record = admin_stub(box, listing([GOOD[1], GOOD[2]]))
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon", "--password-stdin",
                    stdin="x\n", env={"RAIN_CORE_ADMIN": str(path)})
    assert code == 3 and "is absent from rain-core's device.list" in out, out


def test_authenticated_without_terminal_is_skipped_incomplete(box):
    path, record = admin_stub(box, listing(GOOD))
    code, out = run(box, "healthcheck.sh", "0.2.1", "--authenticated", "--user", "dragon",
                    env={"RAIN_CORE_ADMIN": str(path)})
    assert code == 2 and "SKIPPED  authenticated device.list (requires operator credentials; no terminal" in out
    assert not record.exists()


@pytest.mark.parametrize("args", [["--user", "dragon"], ["--authenticated"], ["--authenticated", "--user", "-x"],
                                  ["0.3.0"], []])
def test_usage_errors_are_64(box, args):
    argv = args if args and not args[0].startswith("0.") else args
    if not args or not args[0].startswith("0."):
        argv = ["0.2.1", *args] if args else []
    code, out = run(box, "healthcheck.sh", *argv)
    assert code == 64 and "RESULT=USAGE" in out, out


# ------------------------------------------------------------ installer verdict never stops


@pytest.mark.parametrize("rc,expected,needle", [
    (0, 0, ""), (1, 1, "FAIL-CORE"), (2, 2, "INCOMPLETE"), (3, 3, "FAIL-STATE"), (64, 2, "treated as INCOMPLETE"),
])
def test_health_verdict_never_stops_the_service(box, rc, expected, needle):
    script = (f'set -euo pipefail; HERE={str(BUNDLE)!r}; source "$HERE/_rain_h1_common.sh"; '
              f'say() {{ echo "[t] $*"; }}; RC2=0; health_verdict {rc} "sudo bash rollback" "/b" || RC2=$?; '
              f'echo "VERDICT=$RC2"')
    result = subprocess.run(["bash", "-c", script], env=box["env"], capture_output=True, text=True)
    assert f"VERDICT={expected}" in result.stdout, result.stdout + result.stderr
    assert needle in result.stdout
    calls = box["calls"].read_text().split("\n") if box["calls"].exists() else []
    assert not any(line.startswith("stop") for line in calls)


def test_install_and_rollback_have_no_post_start_stop():
    for name in ("install-0.2.1.sh", "rollback-0.2.0.sh"):
        text = (BUNDLE / name).read_text()
        after_start = text.split('systemctl start "$UNIT"\n')[-1]
        assert 'systemctl stop' not in after_start, name
        assert "health_verdict" in after_start, name
