# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Direwolf status (read-only): binary, running processes, systemd units, configuration files and
local KISS/AGW TCP ports. The launcher never starts, stops or configures Direwolf and never guesses
audio, PTT or callsign settings."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from task_launcher.services import probe

DEFAULT_KISS = 8001     # Direwolf defaults when KISSPORT / AGWPORT are not configured
DEFAULT_AGW = 8000
BEACONS = ("PBEACON", "TBEACON", "OBEACON", "CBEACON", "IBEACON")


@dataclass
class DirewolfConfig:
    path: str
    readable: bool = True
    error: str = ""
    adevice: list = field(default_factory=list)
    achannels: str = ""
    mycall: list = field(default_factory=list)
    modem: list = field(default_factory=list)
    ptt: list = field(default_factory=list)
    kiss_ports: list = field(default_factory=list)   # ints; 0 = disabled
    agw_port: int = None
    digipeat: int = 0
    beacons: int = 0
    igserver: str = ""
    iglogin: str = ""                                 # callsign only; passcode redacted
    igtx: bool = False

    @property
    def effective_kiss_ports(self):
        if not self.kiss_ports:
            return [DEFAULT_KISS]
        return [p for p in self.kiss_ports if p > 0]

    @property
    def effective_agw_port(self):
        return DEFAULT_AGW if self.agw_port is None else (self.agw_port or None)

    @property
    def transmit_capable(self):
        return bool(self.ptt) or self.beacons > 0 or self.digipeat > 0 or self.igtx


def parse_config(text: str, path: str = "") -> DirewolfConfig:
    c = DirewolfConfig(path)
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        kw, args = parts[0].upper(), parts[1:]
        if kw == "ADEVICE":
            c.adevice.append(" ".join(args))
        elif kw == "ACHANNELS":
            c.achannels = " ".join(args)
        elif kw == "MYCALL":
            c.mycall.append(" ".join(args))
        elif kw == "MODEM":
            c.modem.append(" ".join(args))
        elif kw == "PTT":
            c.ptt.append(" ".join(args))
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
            c.igserver = " ".join(args)
        elif kw == "IGLOGIN":
            c.iglogin = (args[0] + " (passcode hidden)") if args else ""
        elif kw == "IGTXVIA":
            c.igtx = True
    return c


@dataclass
class DirewolfStatus:
    binary: str = ""
    processes: list = field(default_factory=list)
    units: list = field(default_factory=list)
    configs: list = field(default_factory=list)
    kiss_open: dict = field(default_factory=dict)   # port -> bool
    agw_open: dict = field(default_factory=dict)

    @property
    def running(self):
        return bool(self.processes) or any(u.active == "active" for u in self.units)

    def open_kiss_port(self):
        for port, ok in self.kiss_open.items():
            if ok:
                return port
        return None

    def summary(self):
        if not self.binary and not self.processes:
            return "Direwolf not installed"
        k = self.open_kiss_port()
        if self.running:
            return f"Direwolf running · KISS TCP {k} open (receive monitor available)" if k else \
                "Direwolf running · no KISS TCP port reachable"
        if k:
            return f"KISS TCP {k} open · Direwolf process not visible to this user"
        return "Direwolf installed · not running (not started by the launcher)"


def _config_paths(procs, units, home: Path):
    paths = []
    for argv in [p.argv for p in procs] + [u.exec_argv for u in units]:
        for i, a in enumerate(argv):
            if a == "-c" and i + 1 < len(argv):
                paths.append(argv[i + 1])
            elif a.startswith("-c") and len(a) > 2:
                paths.append(a[2:])
    for p in procs:                                   # direwolf reads ./direwolf.conf by default
        try:
            cwd = os.readlink(f"/proc/{p.pid}/cwd")
            paths.append(os.path.join(cwd, "direwolf.conf"))
        except OSError:
            pass
    paths += [str(home / "direwolf.conf"), "/etc/direwolf.conf"]
    out = []
    for p in paths:
        if p not in out:
            out.append(p)
    return out


def collect(home: Path = None, procs_fn=None, units_fn=None, binary_fn=None, port_fn=probe.tcp_reachable):
    home = home or Path.home()
    st = DirewolfStatus()
    st.binary = (binary_fn or (lambda: probe.find_program(["direwolf"]).get("direwolf", "")))()
    st.processes = (procs_fn or (lambda: probe.processes(["direwolf"])))()
    st.units = (units_fn or (lambda: probe.list_units(["direwolf*"]) + probe.list_units(["direwolf*"], user=True)))()
    for path in _config_paths(st.processes, st.units, home):
        p = Path(path)
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:512 * 1024]
            st.configs.append(parse_config(text, str(p)))
        except OSError as exc:
            st.configs.append(DirewolfConfig(str(p), readable=False, error=exc.strerror or str(exc)))
    if not st.binary and not st.processes:
        return st                                     # nothing to look for: no port probes at all
    kiss, agw = set(), set()
    for c in st.configs:
        if c.readable:
            kiss.update(c.effective_kiss_ports)
            if c.effective_agw_port:
                agw.add(c.effective_agw_port)
    if not st.configs:
        kiss.add(DEFAULT_KISS)
        agw.add(DEFAULT_AGW)
    for port in sorted(kiss):
        st.kiss_open[port] = port_fn(port)
    for port in sorted(agw):
        st.agw_open[port] = port_fn(port)
    return st
