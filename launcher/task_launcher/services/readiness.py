# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Readiness lines ("installed" vs "service/hardware ready"), shown under a tile's status.

Two kinds of input:
* task-core state already held by the launcher's Core link (capability.list, device.list when
  signed in) — evaluated on the GUI thread, no I/O;
* local probes (Kiwix, Direwolf, task-mesh, weather, medical, gpsd) — run in a background
  PollWorker with timeouts; results are cached here.

A readiness line never upgrades a tile's status; it is display only. "Ready" is only claimed when a
probe positively observed the thing (e.g. an RTL-SDR 0bda:2838 in task-core's device list).
"""

from dataclasses import dataclass

from task_launcher.services import direwolf, kiwix, medical, mesh, meshbadge, probe, reference, statuscards, weather

GPSD_PORT = 2947
RTL_SDR = ("0bda", "2838")
# Programs that open an RTL-SDR directly (only one can hold the dongle at a time).
SDR_PROGRAMS = ("sdrpp", "gqrx", "rtl_fm", "rtl_tcp", "rtl_433", "rtl_sdr", "rtl_power", "dump1090",
                "dump1090-mutability", "dump1090-fa")
OK, WARN, MUTED = "ok", "warn", "muted"


@dataclass
class Readiness:
    text: str
    level: str = MUTED       # ok | warn | muted


def _cap_text(status):
    return {"available": "available", "no-provider": "device connected, no Core provider",
            "no-device": "no device assigned/connected"}.get(status, status or "—")


def _devices(link):
    d = getattr(link, "devices", None)
    if getattr(link, "signed_in", False) and isinstance(d, dict) and isinstance(d.get("devices"), list):
        return [x for x in d["devices"] if isinstance(x, dict)]
    return None


def sdr_readiness(link, busy=None) -> Readiness:
    r = _sdr_core(link)
    if busy:
        return Readiness(f"{r.text} · in use by {', '.join(busy)}", WARN)
    return r


def _sdr_core(link) -> Readiness:
    if not getattr(link, "live", False):
        return Readiness("RTL-SDR: unknown (task-core not connected)", MUTED)
    devs = _devices(link)
    if devs is None:
        cap = link.capability_status("radio.rx")
        return Readiness(f"RTL-SDR: sign in to check · Core radio.rx: {_cap_text(cap)}", MUTED)
    hits = [d for d in devs if (str(d.get("vid", "")).lower(), str(d.get("pid", "")).lower()) == RTL_SDR]
    if any(d.get("connected") for d in hits):
        return Readiness("RTL-SDR 0bda:2838 present (task-core)", OK)
    if hits:
        return Readiness("RTL-SDR 0bda:2838 known but disconnected", WARN)
    return Readiness("No RTL-SDR (0bda:2838) in task-core device list", WARN)


def gps_readiness(link, gpsd_open) -> Readiness:
    bits, level = [], MUTED
    if getattr(link, "live", False):
        cap = link.capability_status("gps.position")
        bits.append(f"Core gps.position: {_cap_text(cap)}")
    else:
        bits.append("Core: not connected")
    if gpsd_open is True:
        bits.append("gpsd :2947 reachable")
        level = OK
    elif gpsd_open is False:
        bits.append("gpsd not reachable")
        level = WARN
    return Readiness(" · ".join(bits), level)


def mesh_readiness(link, st) -> Readiness:
    """Hardware/service side only; whether task-mesh is installed is the tile's own status."""
    bits = []
    if st is None:
        bits.append("checking…")
    else:
        if st.running:
            bits.append("task-mesh running")
        n = len(st.serial_ports)
        bits.append(f"{n} USB serial device{'s' if n != 1 else ''}" if n else "no USB serial device")
    if getattr(link, "live", False):
        bits.append(f"Core mesh: {_cap_text(link.capability_status('mesh.messaging'))}")
    level = OK if st is not None and st.serial_ports else MUTED
    if st is not None and st.cli_running:
        bits.insert(0, "meshtastic CLI running — serial port conflict" if st.running or st.executable
                    else "meshtastic CLI running (holds the serial port)")
        level = WARN
    return Readiness(" · ".join(bits), level)


class ProbeResults:
    """Thread-safe-enough holder: written by the probe worker via a queued signal on the GUI thread."""

    def __init__(self):
        self.kiwix = None
        self.direwolf = None
        self.mesh = None
        self.weather = None
        self.medical = None
        self.gpsd_open = None
        self.sdr_busy = None
        self.ref_error = ""
        self.cards = {}
        self.mesh_badge = None

    def line(self, probe_name, link) -> Readiness:
        base = self._line(probe_name, link)
        if probe_name == "mesh":
            badge = meshbadge.badge_text(self.mesh_badge)
            if badge:
                base = Readiness(f"{badge} · {base.text}" if base.text else badge, base.level)
        text = statuscards.card_text((self.cards or {}).get(probe_name))
        if text:
            stale = text.startswith("not responding")
            return Readiness(f"{text} · {base.text}" if base.text else text, WARN if stale else base.level)
        return base

    def _line(self, probe_name, link) -> Readiness:
        if probe_name == "rtl-sdr":
            return sdr_readiness(link, self.sdr_busy)
        if probe_name == "gps":
            return gps_readiness(link, self.gpsd_open)
        if probe_name == "mesh":
            return mesh_readiness(link, self.mesh)
        obj = getattr(self, probe_name, None)
        if obj is None:
            return Readiness("checking…", MUTED)
        if probe_name == "kiwix":
            return Readiness(obj.summary(), OK if obj.ready else WARN)
        if probe_name == "direwolf":
            return Readiness(obj.summary(), OK if obj.open_kiss_port() else (MUTED if obj.binary else WARN))
        if probe_name == "weather":
            return Readiness(obj.summary(), OK if obj.newest else MUTED)
        if probe_name == "medical":
            return Readiness(obj.summary(), OK if obj.count else MUTED)
        return Readiness("—", MUTED)


def sdr_busy(procs_fn=None):
    """Names of running programs that hold an RTL-SDR (from /proc; nothing is opened)."""
    procs = (procs_fn or (lambda: probe.processes(SDR_PROGRAMS)))()
    import os
    return sorted({os.path.basename(p.argv[0]) for p in procs})


def collect_all(wanted=("kiwix", "direwolf", "mesh", "weather", "medical", "gps", "rtl-sdr")):
    """Blocking: run in a worker. Returns a dict of probe results."""
    out = {}
    doc, err = reference.load()
    out["ref_error"] = err
    if "kiwix" in wanted or "medical" in wanted:
        out["kiwix"] = kiwix.discover()
    if "direwolf" in wanted:
        out["direwolf"] = direwolf.collect()
    if "mesh" in wanted:
        out["mesh"] = mesh.collect()
        out["mesh_badge"] = meshbadge.collect()
    if "weather" in wanted:
        out["weather"] = weather.collect(reference.dirs("weather", doc))
    if "medical" in wanted:
        out["medical"] = medical.collect(out.get("kiwix"), reference.dirs("medical", doc))
    if "rtl-sdr" in wanted:
        out["sdr_busy"] = sdr_busy()
    out["cards"] = statuscards.collect()
    if "gps" in wanted:
        out["gpsd_open"] = probe.tcp_reachable(GPSD_PORT, timeout=0.8)
    return out
