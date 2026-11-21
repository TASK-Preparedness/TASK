# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only Direwolf configuration inspection (per channel). task-aprs never writes direwolf.conf,
never starts/stops Direwolf and never opens its audio device or PTT port."""

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_KISS = 8001
DEFAULT_AGW = 8000
BEACONS = ("PBEACON", "TBEACON", "OBEACON", "CBEACON", "IBEACON")
CANDIDATES = (Path.home() / "direwolf.conf", Path("/etc/direwolf.conf"), Path("/etc/direwolf/direwolf.conf"))
MAX_BYTES = 512 * 1024


@dataclass
class Channel:
    number: int
    mycall: str = ""
    modem: str = ""
    ptt: str = ""
    txdelay: str = ""
    txtail: str = ""


@dataclass
class DirewolfConfig:
    path: str = ""
    error: str = ""
    adevice: list = field(default_factory=list)
    achannels: int = 1
    channels: dict = field(default_factory=dict)       # int -> Channel
    kiss_ports: list = field(default_factory=list)
    agw_port: int = None
    digipeat: int = 0
    beacons: int = 0
    igate: bool = False
    igtx: bool = False

    @property
    def effective_agw_port(self):
        return DEFAULT_AGW if self.agw_port is None else (self.agw_port or None)

    @property
    def effective_kiss_ports(self):
        return [DEFAULT_KISS] if not self.kiss_ports else [p for p in self.kiss_ports if p > 0]

    def channel(self, n) -> Channel:
        return self.channels.get(n) or Channel(n)

    def warnings(self, callsign: str = "", channel: int = 0):
        out = []
        ch = self.channel(channel)
        if not ch.ptt:
            out.append(f"Channel {channel}: no PTT configured — Direwolf cannot key a radio")
        if callsign and ch.mycall and ch.mycall.upper() != callsign.upper():
            out.append(f"Channel {channel}: Direwolf MYCALL {ch.mycall} differs from the configured callsign")
        if self.beacons:
            out.append(f"Direwolf itself has {self.beacons} beacon line(s) (Direwolf's, not T.A.S.K.'s)")
        if self.digipeat:
            out.append("Direwolf digipeating is configured (Direwolf's, not T.A.S.K.'s)")
        if self.igate:
            out.append("Direwolf IGate is configured (Direwolf's, not T.A.S.K.'s)")
        if self.effective_agw_port is None:
            out.append("AGW is disabled: transmit falls back to KISS with only 'submitted' / 'acked' states")
        return out


def parse(text: str, path: str = "") -> DirewolfConfig:
    c = DirewolfConfig(path)
    cur = 0
    c.channels[0] = Channel(0)
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        kw, args = parts[0].upper(), parts[1:]
        val = " ".join(args)
        if kw == "ADEVICE" or (kw.startswith("ADEVICE") and kw[7:].isdigit()):
            c.adevice.append(val)
        elif kw == "ACHANNELS" and args and args[0].isdigit():
            c.achannels = int(args[0])
        elif kw == "CHANNEL" and args and args[0].isdigit():
            cur = int(args[0])
            c.channels.setdefault(cur, Channel(cur))
        elif kw in ("MYCALL", "MODEM", "PTT", "TXDELAY", "TXTAIL"):
            setattr(c.channels.setdefault(cur, Channel(cur)), kw.lower(), val)
        elif kw == "KISSPORT" and args:
            try:
                c.kiss_ports.append(int(args[0]))
            except ValueError:
                pass
        elif kw == "AGWPORT" and args:
            try:
                c.agw_port = int(args[0])
            except ValueError:
                pass
        elif kw == "DIGIPEAT":
            c.digipeat += 1
        elif kw in BEACONS:
            c.beacons += 1
        elif kw == "IGSERVER":
            c.igate = True
        elif kw == "IGTXVIA":
            c.igtx = True
    return c


def load(paths=CANDIDATES) -> DirewolfConfig:
    for p in paths:
        p = Path(p)
        try:
            if p.is_file():
                with open(p, "rb") as f:
                    return parse(f.read(MAX_BYTES).decode("utf-8", "replace"), str(p))
        except OSError as exc:
            return DirewolfConfig(str(p), error=f"cannot read: {exc.strerror}")
    return DirewolfConfig("", error="no direwolf.conf found")
