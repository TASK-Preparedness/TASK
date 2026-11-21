#!/usr/bin/python3
"""Phase 1 smoke client. Talks to /run/rain/core.sock as the calling uid."""

import json
import socket
import sys

SOCKET = "/run/rain/core.sock"


def call(method, params=None):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCKET)
    body = {"v": 1, "id": "1", "method": method, "params": params or {}}
    sock.sendall((json.dumps(body) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            raise SystemExit("socket closed")
        buf += chunk
    sock.close()
    return json.loads(buf.split(b"\n", 1)[0])


def main(argv):
    if len(argv) < 2 or argv[1] not in {"health", "devices", "assign"}:
        raise SystemExit("usage: rain-smoke health | devices | assign <device_id>")
    command = argv[1]
    if command == "health":
        result = call("core.health")
    elif command == "devices":
        result = call("device.list")
    else:
        if len(argv) != 3:
            raise SystemExit("usage: rain-smoke assign <device_id>")
        result = call(
            "device.assign",
            {"logical": "gps.primary", "device_id": argv[2], "alias": "smoke"},
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
