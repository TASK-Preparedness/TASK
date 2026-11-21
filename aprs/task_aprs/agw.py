# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Minimal AGWPE client for Direwolf (loopback only).

Verified against Direwolf src/server.c (master: 'k' :1713, 'K' :1799, 'y' :2079; tag 1.7: :1695, :1768, :2047):
* header = 36 bytes: portx, 3 reserved, datakind, reserved, pid, reserved, call_from[10], call_to[10],
  data_len (LE int32), user_reserved (LE int32).
* 'K' to Direwolf: data = one byte (ignored; Direwolf uses the header port) + raw AX.25 frame without FCS.
* 'K' from Direwolf (after 'k'): data[0] = channel << 4, then the raw frame.
* 'y': reply data = LE int32 count of frames in the transmit queue of that channel.
A falling 'y' count only shows queue progress inside Direwolf. It is NOT proof of radio transmission.
"""

import socket
import struct
import threading

from task_aprs.netutil import ensure_loopback

HDR = struct.Struct("<B3xBxBx10s10sii")
assert HDR.size == 36
MAX_DATA = 64 * 1024


class AgwError(OSError):
    pass


def pack(kind: str, port: int = 0, data: bytes = b"", pid: int = 0, call_from: str = "", call_to: str = "") -> bytes:
    return HDR.pack(port & 0xFF, ord(kind), pid, call_from.encode()[:9], call_to.encode()[:9], len(data), 0) + data


def unpack_header(buf: bytes):
    port, kind, pid, cf, ct, n, _ = HDR.unpack(buf)
    if not 0 <= n <= MAX_DATA:
        raise AgwError("bad AGW data length")
    return port, chr(kind), pid, cf.split(b"\0")[0].decode("ascii", "replace"), \
        ct.split(b"\0")[0].decode("ascii", "replace"), n


class AgwClient:
    """Blocking client. RX frames arrive via on_frame(channel, raw_ax25) from a reader thread;
    replies to 'y' are delivered through outstanding()."""

    name = "direwolf-agw"
    has_queue_feedback = True

    def __init__(self, host="127.0.0.1", port=8000, timeout=3.0, on_frame=None, on_close=None):
        self.host, self.port, self.timeout = ensure_loopback(host), int(port), timeout
        self.on_frame, self.on_close = on_frame, on_close
        self.sock = None
        self._send_lock = threading.Lock()
        self._cv = threading.Condition()
        self._replies = {}
        self._reader = None
        self.version = None

    # -------------------------------------------------------------- connection
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(None)
        self._reader = threading.Thread(target=self._read_loop, name="task-aprs-agw", daemon=True)
        self._reader.start()
        self._send(pack("R"))
        self.version = self._wait("R")
        return self

    def close(self):
        s, self.sock = self.sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    @property
    def connected(self):
        return self.sock is not None

    def _send(self, data: bytes):
        if self.sock is None:
            raise AgwError("not connected to Direwolf AGW")
        with self._send_lock:
            self.sock.sendall(data)

    def _recv_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise EOFError
            out += chunk
        return out

    def _read_loop(self):
        try:
            while self.sock is not None:
                port, kind, pid, cf, ct, n = unpack_header(self._recv_exact(HDR.size))
                data = self._recv_exact(n) if n else b""
                if kind == "K":
                    if data and self.on_frame:
                        self.on_frame(data[0] >> 4, data[1:])
                    continue
                with self._cv:
                    self._replies[(kind, port if kind in "yg" else None)] = data
                    self._cv.notify_all()
        except (OSError, EOFError, struct.error, AttributeError):
            pass
        finally:
            was = self.sock is not None
            self.sock = None
            with self._cv:
                self._cv.notify_all()
            if was and self.on_close:
                self.on_close()

    def _wait(self, kind, port=None, timeout=None):
        key = (kind, port)
        with self._cv:
            ok = self._cv.wait_for(lambda: key in self._replies or self.sock is None, timeout or self.timeout)
            if key not in self._replies:
                raise AgwError(f"no AGW '{kind}' reply" + ("" if ok else " (timeout)"))
            return self._replies.pop(key)

    # -------------------------------------------------------------- requests
    def version_text(self):
        v = self.version or b""
        if len(v) >= 8:
            major, minor = struct.unpack("<ii", v[:8])
            return f"{major}.{minor}"
        return "unknown"

    def port_info(self):
        self._send(pack("G"))
        data = self._wait("G")
        return data.split(b"\0")[0].decode("ascii", "replace")

    def enable_raw_rx(self):
        self._send(pack("k"))

    def send_raw(self, channel: int, frame: bytes):
        """Hand one raw AX.25 frame to Direwolf's transmit queue for `channel`."""
        if not frame or len(frame) > 2048:
            raise ValueError("bad frame")
        self._send(pack("K", channel, bytes([(channel & 0x0F) << 4]) + frame))

    def outstanding(self, channel: int) -> int:
        self._send(pack("y", channel))
        data = self._wait("y", channel)
        if len(data) < 4:
            raise AgwError("short 'y' reply")
        return struct.unpack("<i", data[:4])[0]
