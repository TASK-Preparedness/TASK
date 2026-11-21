# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""rain-core GPS status (read-only, public).

rain-core 0.2.1 has no position method: ``gps.position`` exists only as a *capability* in
``capability.list`` (``rain_core/capabilities.py``: Phase 1 registers no providers, so it is
``no-device`` or ``no-provider``). Positions therefore come from gpsd (``gpsd.py``); this module
only reports what Core says so the GPS panel can show it. One sessionless v2 request over
``/run/rain/core.sock``; never a write method.
"""

import json
import socket

CORE_SOCKET = "/run/rain/core.sock"
STATUS_TEXT = {"available": "available", "no-provider": "device connected, no Core provider",
               "no-device": "no GPS assigned/connected"}


def gps_capability(path=CORE_SOCKET, timeout=1.5):
    """Return (status or None, detail)."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(path)
    except OSError as exc:
        return None, f"rain-core not reachable ({exc.strerror or exc})"
    try:
        s.sendall(json.dumps({"v": 2, "id": "maps1", "method": "capability.list", "params": {}}).encode() + b"\n")
        buf = b""
        while b"\n" not in buf and len(buf) < 256 * 1024:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        reply = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        if not reply.get("ok"):
            return None, "rain-core refused capability.list"
        for c in reply.get("result", {}).get("capabilities", []):
            if isinstance(c, dict) and c.get("name") == "gps.position":
                st = c.get("status")
                return st, STATUS_TEXT.get(st, str(st))
        return None, "rain-core does not report gps.position"
    except (OSError, ValueError, AttributeError) as exc:
        return None, f"rain-core reply not understood ({exc})"
    finally:
        s.close()
