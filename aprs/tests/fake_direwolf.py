# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Loopback fake Direwolf (AGW + KISS) for simulated tests. Transmits nothing: it only records frames."""

import socket
import struct
import threading

from task_aprs import agw
from task_comms.aprs import KissDecoder, kiss_frame


class _Server:
    def __init__(self):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.clients = []
        self.frames = []
        self.stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stop:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.clients.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def close(self):
        self.stop = True
        for c in self.clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()
        self.srv.close()


class FakeAgw(_Server):
    def __init__(self):
        self.queue = {}
        self.raw_rx = set()
        self.kinds = []
        super().__init__()

    def _recv(self, c, n):
        b = b""
        while len(b) < n:
            x = c.recv(n - len(b))
            if not x:
                raise EOFError
            b += x
        return b

    def _serve(self, c):
        try:
            while True:
                port, kind, pid, cf, ct, n = agw.unpack_header(self._recv(c, 36))
                data = self._recv(c, n) if n else b""
                self.kinds.append(kind)
                if kind == "R":
                    c.sendall(agw.pack("R", 0, struct.pack("<ii", 1, 7)))
                elif kind == "G":
                    c.sendall(agw.pack("G", 0, b"1;Port1 fake soundcard;\0"))
                elif kind == "k":
                    self.raw_rx.add(c)
                elif kind == "K":
                    self.frames.append((port, data[1:]))
                    self.queue[port] = self.queue.get(port, 0) + 1
                elif kind == "y":
                    c.sendall(agw.pack("y", port, struct.pack("<i", self.queue.get(port, 0))))
        except (EOFError, OSError):
            pass

    def drain(self, port=0):
        self.queue[port] = 0

    def inject(self, frame: bytes, chan=0):
        for c in list(self.raw_rx):
            c.sendall(agw.pack("K", chan, bytes([chan << 4]) + frame))


class FakeKiss(_Server):
    def _serve(self, c):
        dec = KissDecoder()
        try:
            while True:
                d = c.recv(4096)
                if not d:
                    return
                self.frames.extend(dec.feed(d))
        except OSError:
            pass

    def inject(self, frame: bytes, chan=0):
        for c in list(self.clients):
            c.sendall(kiss_frame(frame, chan))
