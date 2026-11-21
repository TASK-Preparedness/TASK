# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only gpsd client (JSON protocol, https://gpsd.gitlab.io/gpsd/gpsd_json.html).

Connects to 127.0.0.1:2947, sends ``?WATCH={"enable":true,"json":true}`` and reads TPV / SKY
reports. It never opens the GPS serial device and never sends device-configuration commands
(``?DEVICE=`` is never written). Reconnects with bounded backoff. Pure Python (thread); the Qt
layer polls ``state()`` or receives ``on_update``.
"""

import json
import socket
import threading
import time
from dataclasses import dataclass, field, replace

from task_maps.tilemath import haversine_m  # noqa: F401 (used by callers)

HOST, PORT = "127.0.0.1", 2947
WATCH = b'?WATCH={"enable":true,"json":true}\n'
FIX_STALE_S = 5.0
MAX_LINE = 64 * 1024
MODE_TEXT = {0: "unknown", 1: "no fix", 2: "2D fix", 3: "3D fix"}


@dataclass
class GpsState:
    connection: str = "connecting"        # connecting | connected | unavailable
    detail: str = ""
    gpsd_version: str = ""
    devices: list = field(default_factory=list)
    mode: int = 0
    lat: float = None
    lon: float = None
    alt: float = None
    speed: float = None                   # m/s
    track: float = None                   # degrees true
    eph: float = None                     # horizontal error estimate (m), if reported
    epx: float = None
    epy: float = None
    time: str = ""
    sats_used: int = None
    sats_visible: int = None
    hdop: float = None
    last_tpv: float = 0.0                 # monotonic time of last TPV with a fix
    updated: float = 0.0

    @property
    def has_fix(self) -> bool:
        return self.mode >= 2 and self.lat is not None and self.lon is not None

    def fix_fresh(self, now=None) -> bool:
        now = time.monotonic() if now is None else now
        return self.has_fix and now - self.last_tpv <= FIX_STALE_S

    def accuracy_m(self):
        if self.eph is not None:
            return self.eph
        if self.epx is not None and self.epy is not None:
            return max(self.epx, self.epy)
        return None

    def fix_text(self, now=None) -> str:
        if self.connection != "connected":
            return "GPS: " + ({"connecting": "connecting to gpsd…"}.get(self.connection) or f"gpsd unavailable ({self.detail})")
        if not self.has_fix:
            return "No fix"
        if not self.fix_fresh(now):
            return "Fix lost (last position shown)"
        return MODE_TEXT.get(self.mode, "fix")


def _num(d, k):
    v = d.get(k)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def apply_report(st: GpsState, msg: dict, now: float) -> GpsState:
    cls = msg.get("class")
    if cls == "VERSION":
        return replace(st, gpsd_version=str(msg.get("release", ""))[:32], updated=now)
    if cls == "DEVICES":
        devs = [str(d.get("path", ""))[:64] for d in msg.get("devices", []) if isinstance(d, dict)]
        return replace(st, devices=devs, updated=now)
    if cls == "TPV":
        mode = msg.get("mode") if isinstance(msg.get("mode"), int) else 0
        st = replace(st, mode=mode, time=str(msg.get("time", ""))[:32], updated=now)
        if mode >= 2 and _num(msg, "lat") is not None and _num(msg, "lon") is not None:
            st = replace(st, lat=_num(msg, "lat"), lon=_num(msg, "lon"), last_tpv=now,
                         alt=_num(msg, "altMSL") if _num(msg, "altMSL") is not None else _num(msg, "alt"),
                         speed=_num(msg, "speed"), track=_num(msg, "track"), eph=_num(msg, "eph"),
                         epx=_num(msg, "epx"), epy=_num(msg, "epy"))
        return st
    if cls == "SKY":
        sats = msg.get("satellites")
        used = msg.get("uSat") if isinstance(msg.get("uSat"), int) else None
        vis = msg.get("nSat") if isinstance(msg.get("nSat"), int) else None
        if isinstance(sats, list):
            vis = len(sats) if vis is None else vis
            if used is None:
                used = sum(1 for s in sats if isinstance(s, dict) and s.get("used"))
        if used is None and vis is None:
            return replace(st, hdop=_num(msg, "hdop") or st.hdop, updated=now)
        return replace(st, sats_used=used, sats_visible=vis, hdop=_num(msg, "hdop"), updated=now)
    return st


class GpsdClient(threading.Thread):
    def __init__(self, host=HOST, port=PORT, on_update=None, backoff=(1.0, 2.0, 5.0, 10.0, 30.0), clock=time.monotonic,
                 connect_timeout=2.0):
        super().__init__(name="gpsd-client", daemon=True)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("gpsd client is loopback-only")
        self.host, self.port = ("127.0.0.1" if host == "localhost" else host), port
        self.on_update, self.backoff, self.clock = on_update, backoff, clock
        self.connect_timeout = connect_timeout
        self._st = GpsState()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = None
        self.connects = 0
        self.sent = []                      # everything written to gpsd (tests assert it is only ?WATCH)

    def state(self) -> GpsState:
        with self._lock:
            return self._st

    def _set(self, st):
        with self._lock:
            self._st = st
        if self.on_update:
            self.on_update(st)

    def stop(self):
        self._stop.set()
        s = self._sock
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.join(3)

    def run(self):
        attempt = 0
        while not self._stop.is_set():
            s = None
            try:
                fam = socket.AF_INET6 if ":" in self.host else socket.AF_INET
                s = socket.socket(fam, socket.SOCK_STREAM)
                s.settimeout(self.connect_timeout)
                s.connect((self.host, self.port))
            except OSError as exc:
                if s is not None:
                    s.close()
                self._set(replace(self.state(), connection="unavailable", detail=f"no gpsd at {self.host}:{self.port}: "
                                  f"{exc.strerror or exc}"))
                delay = self.backoff[min(attempt, len(self.backoff) - 1)]
                attempt += 1
                if self._stop.wait(delay):
                    return
                continue
            attempt = 0
            self._sock = s
            self.connects += 1
            self._set(replace(self.state(), connection="connected", detail=""))
            try:
                s.sendall(WATCH)
                self.sent.append(WATCH)
                s.settimeout(1.0)
                buf = b""
                while not self._stop.is_set():
                    try:
                        chunk = s.recv(8192)
                    except socket.timeout:
                        self._set(replace(self.state()))     # lets the UI notice a stale fix
                        continue
                    if not chunk:
                        raise ConnectionError("gpsd closed the connection")
                    buf += chunk
                    if len(buf) > MAX_LINE and b"\n" not in buf:
                        buf = b""
                        continue
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            msg = json.loads(line.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        if isinstance(msg, dict):
                            self._set(apply_report(self.state(), msg, self.clock()))
            except OSError as exc:
                if self._stop.is_set():
                    return
                self._set(replace(self.state(), connection="unavailable", detail=str(exc) or "connection lost"))
            finally:
                self._sock = None
                try:
                    s.close()
                except OSError:
                    pass
            if self._stop.wait(self.backoff[0]):
                return
