# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""System window data: read from /proc, /sys, /etc and statvfs as the desktop user (no root, no
hardware access, no subprocess). Unreadable values are None and shown as '—'. CPU usage is
*calculated* from two /proc/stat samples and labelled so."""

import os
import socket
from pathlib import Path


def os_release(path="/etc/os-release"):
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except (OSError, UnicodeDecodeError):
        pass
    return None


def cpu_times(path="/proc/stat"):
    try:
        with open(path) as fh:
            parts = fh.readline().split()
        if parts[0] != "cpu":
            return None
        values = [int(x) for x in parts[1:9]]
        idle = values[3] + values[4]
        return sum(values), idle
    except (OSError, ValueError, IndexError):
        return None


def cpu_percent(prev, cur):
    if not prev or not cur:
        return None
    dt, di = cur[0] - prev[0], cur[1] - prev[1]
    if dt <= 0:
        return None
    return round(100.0 * (dt - di) / dt, 1)


def loadavg(path="/proc/loadavg"):
    try:
        a, b, c = open(path).read().split()[:3]
        return float(a), float(b), float(c)
    except (OSError, ValueError):
        return None


def meminfo(path="/proc/meminfo"):
    try:
        data = {}
        for line in open(path):
            k, v = line.split(":", 1)
            data[k] = int(v.split()[0]) * 1024
        total, avail = data.get("MemTotal"), data.get("MemAvailable")
        if total is None or avail is None:
            return None
        return {"total": total, "available": avail, "used": total - avail}
    except (OSError, ValueError):
        return None


def uptime(path="/proc/uptime"):
    try:
        return float(open(path).read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def storage(paths_to_check=None):
    """[{mount, total, used, free}] for / and the mounts holding $HOME and /var/lib/task (legacy /var/lib/rain) (if different)."""
    candidates = paths_to_check or ["/", os.path.expanduser("~"), "/var/lib/task", "/var/lib/rain"]
    seen, out = set(), []
    for p in candidates:
        if not os.path.exists(p):
            continue
        mount = _mount_point(p)
        try:
            st = os.statvfs(mount)
            dev = os.stat(mount).st_dev
        except OSError:
            continue
        if dev in seen:
            continue
        seen.add(dev)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        out.append({"mount": mount, "total": total, "free": free, "used": total - st.f_bfree * st.f_frsize})
    return out


def _mount_point(path):
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def cpu_temperature(root="/sys/class/thermal"):
    """(celsius, zone type) from the first readable thermal zone, preferring a CPU zone."""
    try:
        zones = sorted(z for z in os.listdir(root) if z.startswith("thermal_zone"))
    except OSError:
        return None
    readings = []
    for z in zones:
        try:
            ztype = Path(root, z, "type").read_text().strip()
            milli = int(Path(root, z, "temp").read_text().strip())
        except (OSError, ValueError):
            continue
        readings.append((milli / 1000.0, ztype))
    if not readings:
        return None
    for r in readings:
        if "cpu" in r[1].lower() or "soc" in r[1].lower():
            return r
    return readings[0]


class Collector:
    def __init__(self, proc="/proc", etc="/etc", thermal="/sys/class/thermal"):
        self.proc, self.etc, self.thermal = proc, etc, thermal
        self._prev = cpu_times(f"{proc}/stat")

    def __call__(self):
        cur = cpu_times(f"{self.proc}/stat")
        pct = cpu_percent(self._prev, cur)
        self._prev = cur
        u = os.uname()
        return {
            "hostname": socket.gethostname() or None,
            "os": os_release(f"{self.etc}/os-release"),
            "kernel": f"{u.sysname} {u.release}",
            "arch": u.machine,
            "cpu_percent": pct,
            "load": loadavg(f"{self.proc}/loadavg"),
            "memory": meminfo(f"{self.proc}/meminfo"),
            "uptime": uptime(f"{self.proc}/uptime"),
            "storage": storage(),
            "temperature": cpu_temperature(self.thermal),
        }


def fmt_bytes(n):
    if n is None:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0


def fmt_duration(seconds):
    if seconds is None:
        return "—"
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return (f"{d} d " if d else "") + f"{h} h {m:02d} min"
