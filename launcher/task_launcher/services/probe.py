# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Low-level, bounded, read-only probe helpers (loopback TCP/HTTP, read-only systemctl, /proc)."""

import http.client
import ipaddress
import os
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SYSTEMCTL = "/usr/bin/systemctl"
LOOPBACK_NAMES = {"127.0.0.1", "::1", "localhost"}
DEFAULT_TIMEOUT = 1.5
MAX_HTTP_BYTES = 4 * 1024 * 1024
PROC = Path("/proc")


class NotLoopback(ValueError):
    pass


def ensure_loopback(host: str) -> str:
    """Return a numeric loopback address for ``host`` or raise NotLoopback. "localhost" maps to
    127.0.0.1 without a resolver call."""
    if host == "localhost":
        return "127.0.0.1"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        raise NotLoopback(f"not a loopback address: {host!r}") from None
    if not ip.is_loopback:
        raise NotLoopback(f"not a loopback address: {host!r}")
    return str(ip)


def tcp_reachable(port: int, host: str = "127.0.0.1", timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Connect-only check (the connection is closed immediately, nothing is sent)."""
    addr = ensure_loopback(host)
    fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
    s = socket.socket(fam, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((addr, int(port))) == 0
    except OSError:
        return False
    finally:
        s.close()


@dataclass
class HttpResult:
    status: int = 0
    body: bytes = b""
    content_type: str = ""
    location: str = ""
    error: str = ""

    @property
    def ok(self):
        return 200 <= self.status < 300 and not self.error


def http_get(url: str, timeout: float = DEFAULT_TIMEOUT, max_bytes: int = MAX_HTTP_BYTES) -> HttpResult:
    """GET a loopback http:// URL. Redirects are not followed (returned in ``location``)."""
    parts = urlsplit(url)
    if parts.scheme != "http":
        return HttpResult(error="only http:// loopback URLs are fetched")
    try:
        host = ensure_loopback(parts.hostname or "")
    except NotLoopback as exc:
        return HttpResult(error=str(exc))
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    conn = http.client.HTTPConnection(host, parts.port or 80, timeout=timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": "task-launcher", "Accept-Encoding": "identity"})
        resp = conn.getresponse()
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            return HttpResult(resp.status, b"", error=f"response larger than {max_bytes} bytes")
        return HttpResult(resp.status, body, resp.getheader("Content-Type", "") or "",
                          resp.getheader("Location", "") or "")
    except (OSError, http.client.HTTPException) as exc:
        return HttpResult(error=type(exc).__name__ + (f": {exc}" if str(exc) else ""))
    finally:
        conn.close()


def run_readonly(argv: list, timeout: float = 3.0, max_bytes: int = 256 * 1024):
    """(returncode or None, stdout text). Absolute program path, no shell, C locale, bounded."""
    if not argv or not argv[0].startswith("/") or not os.path.isfile(argv[0]):
        return None, ""
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"}
    try:
        cp = subprocess.run(list(argv), shell=False, capture_output=True, timeout=timeout, env=env,
                            stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return cp.returncode, cp.stdout[:max_bytes].decode("utf-8", "replace")


# ---------------------------------------------------------------- systemd (read-only queries)

@dataclass
class Unit:
    name: str
    active: str = ""
    sub: str = ""
    description: str = ""
    exec_argv: list = field(default_factory=list)
    scope: str = "system"


def list_units(patterns, user=False, systemctl=SYSTEMCTL, runner=run_readonly):
    """Units (loaded or not running) matching glob patterns. Read-only: list-units/show only."""
    base = [systemctl] + (["--user"] if user else [])
    code, out = runner(base + ["list-units", "--all", "--plain", "--no-legend", "--no-pager", "--full",
                               *patterns])
    if code is None:
        return []
    units = []
    for line in out.splitlines():
        cols = line.split(None, 4)
        if len(cols) < 4 or not cols[0].endswith((".service", ".socket")):
            continue
        u = Unit(cols[0], active=cols[2], sub=cols[3], description=cols[4] if len(cols) > 4 else "",
                 scope="user" if user else "system")
        code2, show = runner(base + ["show", "--no-pager", "-p", "ExecStart", u.name])
        if code2 == 0:
            u.exec_argv = parse_exec_start(show)
        units.append(u)
    return units


def parse_exec_start(show_text: str) -> list:
    """argv from ``systemctl show -p ExecStart`` output:
    ``ExecStart={ path=/usr/bin/x ; argv[]=/usr/bin/x --port 3000 ; ignore_errors=no ; ... }``."""
    for line in show_text.splitlines():
        if not line.startswith("ExecStart="):
            continue
        value = line[len("ExecStart="):]
        start = value.find("argv[]=")
        if start < 0:
            continue
        rest = value[start + len("argv[]="):]
        end = rest.find(" ; ")
        text = rest if end < 0 else rest[:end]
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()
    return []


# ---------------------------------------------------------------- /proc (no root needed)

@dataclass
class ProcInfo:
    pid: int
    argv: list
    uid: int = -1


def processes(names, proc_root: Path = PROC, limit: int = 4096):
    """Processes whose argv[0] basename is in ``names``. Reads /proc/<pid>/cmdline only."""
    wanted = set(names)
    found = []
    try:
        entries = [e for e in os.listdir(proc_root) if e.isdigit()][:limit]
    except OSError:
        return []
    for e in entries:
        try:
            raw = (proc_root / e / "cmdline").read_bytes()[:65536]
        except OSError:
            continue
        if not raw:
            continue
        argv = [a.decode("utf-8", "replace") for a in raw.rstrip(b"\0").split(b"\0")]
        if os.path.basename(argv[0]) in wanted:
            try:
                uid = (proc_root / e).stat().st_uid
            except OSError:
                uid = -1
            found.append(ProcInfo(int(e), argv, uid))
    return found


def find_program(names, dirs=("/usr/bin", "/usr/local/bin", "/bin", "/usr/sbin", "/usr/games")):
    """{name: absolute path} for executables that exist (no PATH search, fixed directories)."""
    out = {}
    for n in names:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                out[n] = p
                break
    return out


def file_age_text(mtime: float, now: float = None) -> str:
    now = time.time() if now is None else now
    age = max(0, now - mtime)
    if age < 90:
        return f"{int(age)} s old"
    if age < 5400:
        return f"{int(age // 60)} min old"
    if age < 172800:
        return f"{age / 3600:.1f} h old"
    return f"{int(age // 86400)} days old"
