# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Simulated MeshCore companion radio at the serial-frame level.

SimCompanion subclasses meshcore_py's real SerialConnection and replaces only the transport: commands written
by the library are decoded here and answered with '>' len16 frames fed through the library's own framing
parser (handle_rx), reader and dispatcher. Every command byte string written is recorded (self.writes) so tests
can prove what was sent. No hardware, no radio."""

import asyncio
import struct

from task_mesh.protocols.meshcore.compat import import_meshcore

import_meshcore()
from meshcore.serial_cx import SerialConnection  # noqa: E402

PUBKEY = bytes(range(32))
ALICE_KEY = bytes.fromhex("a1b2c3d4e5f6") + bytes(26)
RPT_KEY = bytes.fromhex("0badc0ffee00") + bytes(26)


def contact_frame(key, typ, name, last_advert=1760000000, lat=0, lon=0, code=3):
    return (bytes([code]) + key + bytes([typ, 0, 1]) + bytes(64) + name.encode().ljust(32, b"\0")
            + struct.pack("<IiiI", last_advert, int(lat * 1e6), int(lon * 1e6), last_advert))


def dm_v3(prefix_hex, text, ts, snr=7.5):
    return (bytes([16, int(snr * 4) & 0xFF, 0, 0]) + bytes.fromhex(prefix_hex) + bytes([2, 0])
            + struct.pack("<I", ts) + text.encode())


def chan_v3(idx, text, ts, snr=-3.0):
    return bytes([17, int(snr * 4) & 0xFF, 0, 0, idx, 1, 0]) + struct.pack("<I", ts) + text.encode()


class SimCompanion(SerialConnection):
    def __init__(self, queued=(), contacts=None, answer=True):
        super().__init__("/dev/sim-meshcore", 115200)
        self.queued = list(queued)
        self.contacts = contacts if contacts is not None else [
            contact_frame(ALICE_KEY, 1, "Alice", lat=45.5, lon=-122.6), contact_frame(RPT_KEY, 2, "Hilltop RPT")]
        self.answer = answer
        self.writes = []
        self.open = False

    async def connect(self, timeout=10.0):
        self.open = True
        self.transport = object()
        return self.port

    async def disconnect(self):
        self.open = False
        self.transport = None

    def _reply(self, frame):
        self.handle_rx(b">" + struct.pack("<H", len(frame)) + frame)   # real framing parser

    async def send(self, data):
        data = bytes(data)
        self.writes.append(data)
        if not self.answer:
            return
        await asyncio.sleep(0)
        c = data[0]
        if c == 0x01:      # APP_START -> SELF_INFO
            self._reply(bytes([5, 1, 20, 22]) + PUBKEY + struct.pack("<ii", 0, 0) + bytes([0, 0, 0, 0])
                        + struct.pack("<II", 910525, 62500) + bytes([7, 5]) + b"SimNode")
        elif c == 0x16:    # DEVICE_QUERY -> DEVICE_INFO (with a BLE PIN that must never be stored)
            self._reply(bytes([13, 9, 50, 8]) + struct.pack("<I", 123456) + b"14-Oct-2026\0"
                        + b"Heltec V3 (simulated)".ljust(40, b"\0") + b"v1.9.1".ljust(20, b"\0") + b"\0")
        elif c == 0x14:    # GET_BAT
            self._reply(bytes([12]) + struct.pack("<HII", 87, 10, 100))
        elif c == 0x04:    # GET_CONTACTS
            self._reply(bytes([2]) + struct.pack("<I", len(self.contacts)))
            for f in self.contacts:
                self._reply(f)
            self._reply(bytes([4]) + struct.pack("<I", 1760000001))
        elif c == 0x0A:    # SYNC_NEXT_MESSAGE
            self._reply(self.queued.pop(0) if self.queued else bytes([10]))
        elif c == 0x02:    # SEND_TXT_MSG -> MSG_SENT
            self._reply(bytes([6, 0]) + b"\x01\x02\x03\x04" + struct.pack("<I", 5000))
        elif c == 0x03:    # SEND_CHANNEL_TXT_MSG -> OK
            self._reply(bytes([0]))
        else:
            self._reply(bytes([1, 1]))   # ERROR for anything unexpected

    # test helpers (call from the adapter's loop thread via call_soon_threadsafe)
    def push_waiting(self, *frames):
        self.queued.extend(frames)
        self._reply(bytes([0x83]))

    def drop(self):
        self.transport = None
        if self._disconnect_callback:
            asyncio.ensure_future(self._disconnect_callback("serial_disconnect"))


def sim_connect_factory(sims):
    """connect(path) for MeshCoreAdapter: next simulated companion from the list per session."""
    async def connect(path):
        from meshcore import MeshCore
        sim = sims.pop(0) if len(sims) > 1 else sims[0]
        mc = MeshCore(sim, default_timeout=3)
        res = await mc.connect()
        return mc if res is not None else None
    return connect
