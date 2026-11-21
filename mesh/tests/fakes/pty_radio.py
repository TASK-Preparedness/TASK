# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""A fake Meshtastic radio on a Linux pseudo-terminal, speaking the real serial framing.

Used by contract/integration tests and the screenshot tool to drive the REAL vendored meshtastic
library without hardware. A symlink (like /dev/serial/by-id/...) points at the pty slave so
"unplug" (close master + remove link) and "replug" (new pty, same link) can be simulated.
"""

from __future__ import annotations

import os
import pty
import select
import threading
import time
import tty
from pathlib import Path
from typing import Callable, Optional

from meshtastic.protobuf import channel_pb2, config_pb2, mesh_pb2, portnums_pb2, telemetry_pb2

MY = 0xA1B2C3D4
OTHER = 0x11223344
NUMBER_ONLY = 0x55667788


def frame(msg) -> bytes:
    b = msg.SerializeToString()
    return bytes([0x94, 0xC3, len(b) >> 8, len(b) & 0xFF]) + b


def default_nodes() -> list[Callable[[mesh_pb2.NodeInfo], None]]:
    def local(ni):
        ni.num = MY
        ni.user.id = f"!{MY:08x}"
        ni.user.long_name = "TASK Base"
        ni.user.short_name = "TASK"
        ni.user.hw_model = mesh_pb2.HardwareModel.HELTEC_V3
        ni.device_metrics.battery_level = 101
        ni.device_metrics.voltage = 4.9

    def other(ni):
        ni.num = OTHER
        ni.user.id = f"!{OTHER:08x}"
        ni.user.long_name = "Ridge Relay"
        ni.user.short_name = "RDG"
        ni.user.hw_model = mesh_pb2.HardwareModel.RAK4631
        ni.user.role = config_pb2.Config.DeviceConfig.Role.ROUTER
        ni.position.latitude_i = 401234567
        ni.position.longitude_i = -1051234567
        ni.snr = 6.25
        ni.last_heard = 1759600000
        ni.hops_away = 2
        ni.device_metrics.battery_level = 87

    def number_only(ni):
        ni.num = NUMBER_ONLY

    return [local, other, number_only]


class PtyRadio:
    def __init__(self, link_dir: Path, link_name: str = "usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
                 nodes: Optional[list] = None, my_num: int = MY, silent: bool = False) -> None:
        self.link = Path(link_dir) / link_name
        self.my_num = my_num
        self.nodes = nodes if nodes is not None else default_nodes()
        self.silent = silent
        self.config_requests = 0
        self.received: list[mesh_pb2.ToRadio] = []
        self._master: Optional[int] = None
        self._slave: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.slave_path = ""

    # ----- lifecycle ------------------------------------------------------------------------------
    def plug(self) -> "PtyRadio":
        master, slave = pty.openpty()
        tty.setraw(master)
        tty.setraw(slave)
        self._master, self._slave = master, slave
        self.slave_path = os.ttyname(slave)
        self.link.parent.mkdir(parents=True, exist_ok=True)
        if self.link.is_symlink() or self.link.exists():
            self.link.unlink()
        self.link.symlink_to(self.slave_path)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pty-radio", daemon=True)
        self._thread.start()
        return self

    def unplug(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        for fd in (self._master, self._slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._master = self._slave = None
        if self.link.is_symlink():
            self.link.unlink()

    close = unplug

    @property
    def plugged(self) -> bool:
        return self._master is not None

    # ----- radio behaviour ------------------------------------------------------------------------
    def send(self, msg) -> None:
        self.write(frame(msg))

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._master is not None:
                os.write(self._master, data)

    def _run(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([self._master], [], [], 0.1)
                if not r:
                    continue
                buf += os.read(self._master, 4096)
            except (OSError, TypeError, ValueError):
                return
            while True:
                i = buf.find(b"\x94\xc3")
                if i < 0 or len(buf) < i + 4:
                    break
                n = (buf[i + 2] << 8) | buf[i + 3]
                if len(buf) < i + 4 + n:
                    break
                tr = mesh_pb2.ToRadio()
                try:
                    tr.ParseFromString(buf[i + 4:i + 4 + n])
                except Exception:  # noqa: BLE001
                    buf = buf[i + 2:]
                    continue
                buf = buf[i + 4 + n:]
                self.received.append(tr)
                if tr.want_config_id:
                    self.config_requests += 1
                    if not self.silent:
                        self._config(tr.want_config_id)

    def _config(self, cid: int) -> None:
        f = mesh_pb2.FromRadio()
        f.my_info.my_node_num = self.my_num
        self.send(f)
        f = mesh_pb2.FromRadio()
        f.metadata.firmware_version = "2.7.15.567b8ea"
        self.send(f)
        for build in self.nodes:
            f = mesh_pb2.FromRadio()
            build(f.node_info)
            self.send(f)
        f = mesh_pb2.FromRadio()
        f.config.lora.hop_limit = 3
        self.send(f)
        f = mesh_pb2.FromRadio()
        f.channel.index = 0
        f.channel.role = channel_pb2.Channel.Role.PRIMARY
        self.send(f)
        f = mesh_pb2.FromRadio()
        f.config_complete_id = cid
        self.send(f)

    def send_channel_with_psk(self, psk: bytes) -> None:
        f = mesh_pb2.FromRadio()
        f.channel.index = 1
        f.channel.role = channel_pb2.Channel.Role.SECONDARY
        f.channel.settings.psk = psk
        f.channel.settings.name = "Secret"
        self.send(f)

    def _packet(self, frm: int, rx_time: int, snr: Optional[float], rssi: Optional[int],
                hop_start: Optional[int] = None, hop_limit: Optional[int] = None):
        f = mesh_pb2.FromRadio()
        p = f.packet
        setattr(p, "from", frm)
        p.to = 0xFFFFFFFF
        p.id = int(time.time() * 1000) & 0x7FFFFFFF
        if rx_time:
            p.rx_time = rx_time
        if snr is not None:
            p.rx_snr = snr
        if rssi is not None:
            p.rx_rssi = rssi
        if hop_start is not None:
            p.hop_start = hop_start
        if hop_limit is not None:
            p.hop_limit = hop_limit
        return f, p

    def send_position(self, frm: int, lat_i: int, lon_i: int, rx_time: int = 0, snr: Optional[float] = None,
                      rssi: Optional[int] = None, hop_start: Optional[int] = None,
                      hop_limit: Optional[int] = None) -> None:
        f, p = self._packet(frm, rx_time, snr, rssi, hop_start, hop_limit)
        p.decoded.portnum = portnums_pb2.POSITION_APP
        p.decoded.payload = mesh_pb2.Position(latitude_i=lat_i, longitude_i=lon_i).SerializeToString()
        self.send(f)

    def send_telemetry(self, frm: int, battery: int, voltage: Optional[float] = None, rx_time: int = 0,
                       snr: Optional[float] = None, rssi: Optional[int] = None) -> None:
        f, p = self._packet(frm, rx_time, snr, rssi)
        t = telemetry_pb2.Telemetry()
        t.device_metrics.battery_level = battery
        if voltage is not None:
            t.device_metrics.voltage = voltage
        p.decoded.portnum = portnums_pb2.TELEMETRY_APP
        p.decoded.payload = t.SerializeToString()
        self.send(f)

    def send_nodeinfo_packet(self, frm: int, long_name: str, short_name: str, hw: int,
                             rssi: Optional[int] = None) -> None:
        f, p = self._packet(frm, 0, None, rssi)
        u = mesh_pb2.User(id=f"!{frm:08x}", long_name=long_name, short_name=short_name, hw_model=hw)
        p.decoded.portnum = portnums_pb2.NODEINFO_APP
        p.decoded.payload = u.SerializeToString()
        self.send(f)

    def send_rebooted(self) -> None:
        f = mesh_pb2.FromRadio()
        f.rebooted = True
        self.send(f)

    def send_malformed_suite(self) -> None:
        self.write(bytes([0x94, 0xC3, 0x00, 0x05]) + b"\xff\xff\xff\xff\xff")      # corrupt protobuf
        self.write(bytes([0x94, 0xC3, 0x7F, 0xFF]) + os.urandom(64))              # length > 512
        self.write(b"INFO | some device log line \xe2\x82\r\n")                    # split UTF-8 + log noise
        self.write(bytes([0x94, 0xC3, 0x00, 0x10]) + b"\x0a\x02")                  # truncated frame...
        f = mesh_pb2.FromRadio()
        f.my_info.my_node_num = self.my_num
        self.send(f)                                                               # ...then a valid one
        self.write(os.urandom(256))                                                # noise
        # Valid FromRadio with an unknown future field number (field 999, varint) appended.
        g = mesh_pb2.FromRadio()
        g.my_info.my_node_num = self.my_num
        body = g.SerializeToString() + bytes([0xB8, 0x3E, 0x01])
        self.write(bytes([0x94, 0xC3, len(body) >> 8, len(body) & 0xFF]) + body)
