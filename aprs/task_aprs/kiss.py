# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""KISS-over-TCP client (fallback when AGW is disabled). KISS gives no transmit feedback at all:
the only state after a write is "submitted"."""

import socket
import threading

from task_comms.aprs import KissDecoder, kiss_frame
from task_aprs.netutil import ensure_loopback


class KissClient:
    name = "direwolf-kiss"
    has_queue_feedback = False

    def __init__(self, host="127.0.0.1", port=8001, timeout=3.0, on_frame=None, on_close=None):
        self.host, self.port, self.timeout = ensure_loopback(host), int(port), timeout
        self.on_frame, self.on_close = on_frame, on_close
        self.sock = None
        self._lock = threading.Lock()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(None)
        threading.Thread(target=self._read_loop, name="task-aprs-kiss", daemon=True).start()
        return self

    @property
    def connected(self):
        return self.sock is not None

    def close(self):
        s, self.sock = self.sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def send_raw(self, channel: int, frame: bytes):
        if self.sock is None:
            raise OSError("not connected to Direwolf KISS")
        with self._lock:
            self.sock.sendall(kiss_frame(frame, channel))

    def _read_loop(self):
        dec = KissDecoder()
        try:
            while self.sock is not None:
                data = self.sock.recv(4096)
                if not data:
                    break
                for item in dec.feed(data):
                    port, payload = item
                    if self.on_frame:
                        self.on_frame(port, payload)
        except (OSError, AttributeError):
            pass
        finally:
            was = self.sock is not None
            self.sock = None
            if was and self.on_close:
                self.on_close()
