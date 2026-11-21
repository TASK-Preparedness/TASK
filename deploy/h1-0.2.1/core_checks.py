#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Public (unauthenticated) rain-core checks for the H1 0.2.1 deploy scripts (bundle r3).

Only methods that rain-core serves to a *public* peer are used, so the result does not
depend on the caller's uid being listed in /etc/rain/auth.toml [peers] (root is not
listed on the Pi: deploy/pi-install.sh:66 refuses to authorize uid 0):

  v1 core.health      public  rain_core/api.py:24
  v2 core.health      public  rain_core/protocol_v2.py:22  (+ hotplug, :108-110)
  v2 core.protocol    public  rain_core/protocol_v2.py:21  (:103-104)
  v2 device.counts    public  rain_core/protocol_v2.py:25  (:113-114 -> devices.py:249-254)

v1 device.list / device.get / events.recent need operator (rain_core/api.py:26-31,
enforced at api.py:135-138), which is why bundle r3 no longer calls `rain-smoke devices`.

Every reply is validated (ok:true, required fields, types, values), not only parsed.
Python 3 standard library only. Read-only: sends no state-changing request.

Commands (socket from $RAIN_SOCKET, else `socket =` in $RAIN_ETC_DIR/core.toml, else
/run/rain/core.sock):
  core_checks.py v1-health  <version>
  core_checks.py v2-health  <version>
  core_checks.py protocol   <version>
  core_checks.py counts     [--min-total N]
Exit status: 0 OK; 1 rain-core unhealthy (unreachable, error reply, wrong version,
malformed reply, hotplug not alive); 3 counts below --min-total (state); 64 usage.
"""

import json
import os
import socket
import sys
import time

ALIVE = ("running", "restarting", "degraded")
HOTPLUG_INT_FIELDS = ("restarts", "missed", "events", "dispatch_errors")
V1_HEALTH_KEYS = ("ok", "version", "uid", "uptime_seconds")
ATTEMPTS = int(os.environ.get("RAIN_CHECK_ATTEMPTS", "20"))
DELAY = float(os.environ.get("RAIN_CHECK_DELAY", "0.5"))


class Unhealthy(Exception):
    pass


def socket_path():
    sock = os.environ.get("RAIN_SOCKET")
    if sock:
        return sock
    cfg = os.environ.get("RAIN_ETC_DIR", "/etc/rain") + "/core.toml"
    try:
        with open(cfg, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("socket") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "/run/rain/core.sock"


def call_once(version, method, params=None):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(3)
    try:
        conn.connect(socket_path())
        body = {"v": version, "id": "h1-r3", "method": method, "params": params or {}}
        conn.sendall(json.dumps(body).encode() + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        conn.close()
    line = buf.split(b"\n", 1)[0]
    if not line:
        raise OSError("empty reply")
    reply = json.loads(line.decode("utf-8"))
    if not isinstance(reply, dict):
        raise ValueError("reply is not a JSON object")
    return reply


def call(version, method, params=None, accept=None):
    """Retry while the socket is starting; return the first acceptable reply."""
    last = None
    for attempt in range(ATTEMPTS):
        try:
            reply = call_once(version, method, params)
            if accept is None or accept(reply):
                return reply
            last = "unexpected reply: %s" % json.dumps(reply, sort_keys=True)[:400]
        except (OSError, ValueError) as exc:
            last = "%s: %s" % (type(exc).__name__, exc)
        if attempt + 1 < ATTEMPTS:
            time.sleep(DELAY)
    raise Unhealthy("v%d %s failed after %d attempts at %s (%s)" % (version, method, ATTEMPTS, socket_path(), last))


def ok_result(reply, method):
    if reply.get("ok") is not True:
        error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
        raise Unhealthy("%s replied ok=%r error=%s/%s" % (method, reply.get("ok"), error.get("code"),
                                                          error.get("message")))
    result = reply.get("result")
    if not isinstance(result, dict):
        raise Unhealthy("%s result is %s, expected an object" % (method, type(result).__name__))
    return result


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_health_fields(result, want, method):
    missing = [key for key in V1_HEALTH_KEYS if key not in result]
    if missing:
        raise Unhealthy("%s result missing %s" % (method, missing))
    if result["ok"] is not True:
        raise Unhealthy("%s result.ok=%r" % (method, result["ok"]))
    if result["version"] != want:
        raise Unhealthy("%s version=%r, expected %r" % (method, result["version"], want))
    if not is_int(result["uid"]) or result["uid"] < 0:
        raise Unhealthy("%s uid=%r is not a non-negative integer" % (method, result["uid"]))
    if not isinstance(result["uptime_seconds"], (int, float)) or isinstance(result["uptime_seconds"], bool) \
            or result["uptime_seconds"] < 0:
        raise Unhealthy("%s uptime_seconds=%r invalid" % (method, result["uptime_seconds"]))


def version_is(want):
    def accept(reply):
        result = reply.get("result")
        return reply.get("ok") is True and isinstance(result, dict) and result.get("version") == want
    return accept


def v1_health(want):
    # Waits up to ATTEMPTS*DELAY for the expected version (the unit may still be starting).
    try:
        reply = call(1, "core.health", accept=version_is(want))
    except Unhealthy as first:
        try:
            reply = call_once(1, "core.health")  # report what it does say
        except (OSError, ValueError):
            raise first from None
    result = ok_result(reply, "v1 core.health")
    check_health_fields(result, want, "v1 core.health")
    if "hotplug" in result:
        raise Unhealthy("v1 core.health carries 'hotplug' (v1 wire format must be unchanged)")
    return "v1 core.health ok version=%s uid=%s uptime_seconds=%s" % (
        result["version"], result["uid"], result["uptime_seconds"])


def v2_health(want):
    result = ok_result(call(2, "core.health"), "v2 core.health")
    check_health_fields(result, want, "v2 core.health")
    hotplug = result.get("hotplug")
    if want == "0.2.0":
        if hotplug is not None:
            raise Unhealthy("v2 core.health on 0.2.0 unexpectedly carries hotplug=%r" % (hotplug,))
        return "v2 core.health ok version=0.2.0 (no hotplug field, as expected for 0.2.0)"
    if not isinstance(hotplug, dict):
        raise Unhealthy("v2 core.health hotplug=%r, expected an object" % (hotplug,))
    state = hotplug.get("state")
    if state not in ALIVE:
        raise Unhealthy("hotplug.state=%r is not alive (alive: %s); hotplug=%s"
                        % (state, ", ".join(ALIVE), json.dumps(hotplug, sort_keys=True)))
    for key in HOTPLUG_INT_FIELDS:
        if not is_int(hotplug.get(key)) or hotplug[key] < 0:
            raise Unhealthy("hotplug.%s=%r is not a non-negative integer" % (key, hotplug.get(key)))
    if "last_error" not in hotplug or not (hotplug["last_error"] is None or isinstance(hotplug["last_error"], str)):
        raise Unhealthy("hotplug.last_error=%r invalid" % (hotplug.get("last_error"),))
    return "v2 core.health ok version=%s hotplug=%s" % (want, json.dumps(hotplug, sort_keys=True))


def protocol(want):
    result = ok_result(call(2, "core.protocol"), "v2 core.protocol")
    if result.get("versions") != [1, 2]:
        raise Unhealthy("core.protocol versions=%r, expected [1, 2]" % (result.get("versions"),))
    if result.get("core") != want:
        raise Unhealthy("core.protocol core=%r, expected %r" % (result.get("core"), want))
    if not isinstance(result.get("boot_id"), str) or not result["boot_id"]:
        raise Unhealthy("core.protocol boot_id=%r invalid" % (result.get("boot_id"),))
    return "v2 core.protocol ok versions=[1, 2] core=%s" % want


def counts(min_total):
    result = ok_result(call(2, "device.counts"), "v2 device.counts")
    if set(result) != {"total", "connected", "disconnected"}:
        raise Unhealthy("device.counts keys=%s, expected total/connected/disconnected" % sorted(result))
    for key in ("total", "connected", "disconnected"):
        if not is_int(result[key]) or result[key] < 0:
            raise Unhealthy("device.counts %s=%r is not a non-negative integer" % (key, result[key]))
    if result["connected"] + result["disconnected"] != result["total"]:
        raise Unhealthy("device.counts inconsistent: %r" % (result,))
    line = "v2 device.counts ok (public, redacted) total=%d connected=%d disconnected=%d" % (
        result["total"], result["connected"], result["disconnected"])
    if result["total"] < min_total:
        # rain-core keeps a record for every assigned device id, connected or not
        # (devices.py:180-199 _install_placeholders), so total >= assigned ids.
        return 3, line + "; FAIL total < %d assigned device id(s) in devices.json" % min_total
    return 0, line


def main(argv):
    try:
        if len(argv) == 3 and argv[1] in ("v1-health", "v2-health", "protocol"):
            line = {"v1-health": v1_health, "v2-health": v2_health, "protocol": protocol}[argv[1]](argv[2])
            print("OK    " + line)
            return 0
        if len(argv) in (2, 4) and argv[1] == "counts":
            min_total = 0
            if len(argv) == 4:
                if argv[2] != "--min-total" or not argv[3].isdigit():
                    raise SystemExit(64)
                min_total = int(argv[3])
            code, line = counts(min_total)
            print(("OK    " if code == 0 else "FAIL  ") + line)
            return code
    except Unhealthy as exc:
        print("FAIL  %s" % exc)
        return 1
    except (OSError, ValueError) as exc:
        print("FAIL  %s: %s" % (type(exc).__name__, exc))
        return 1
    sys.stderr.write(__doc__.split("Commands")[1])
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
