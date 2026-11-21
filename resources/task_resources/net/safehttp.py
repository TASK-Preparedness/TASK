# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SSRF-safe HTTP(S) client (stdlib only). Every network access of task-resources goes through here.

* Only http/https, no credentials in URLs, default ports 80/443 only (Policy.any_port is for tests).
* The host is resolved ONCE per hop; if ANY address is loopback, private (RFC 1918), CGNAT 100.64/10,
  link-local, ULA, multicast, reserved, unspecified or an IPv4-mapped/6to4 form of those, the hop is
  refused. The TCP connection goes to the vetted IP; TLS uses SNI + certificate verification for the
  host name, so DNS rebinding cannot redirect the connection afterwards.
* Redirects (301/302/303/307/308) are followed manually, max Policy.max_redirects, every hop validated
  the same way; an https -> http downgrade is refused.
* No cookies, no proxies from the environment, no auth. Logged URLs drop the query string.
"""

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass, field

USER_AGENT = "task-resources/0.2.1 (+offline library; T.A.S.K.)"
REDIRECTS = (301, 302, 303, 307, 308)
CGNAT = ipaddress.ip_network("100.64.0.0/10")


class Blocked(Exception):
    """The request was refused by policy (not a network error)."""


class NetError(Exception):
    """Network problem (DNS, connect, TLS, timeout). Retryable; usually means offline."""


@dataclass
class Policy:
    max_redirects: int = 5
    any_port: bool = False                       # tests only
    allow_ips: frozenset = field(default_factory=frozenset)   # tests only: explicit loopback test servers
    timeout: float = 30.0


def redact(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.hostname or "", p.path, "", ""))


def ip_is_public(ip):
    ip = ipaddress.ip_address(ip)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return ip_is_public(ip.ipv4_mapped)
        if ip.sixtofour:
            return ip_is_public(ip.sixtofour)
        if ip.teredo:
            return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or not ip.is_global)


def check_url(url, policy):
    """-> (scheme, host, port, path_with_query). Raises Blocked."""
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError as exc:
        raise Blocked(f"invalid address: {exc}") from None
    if p.scheme not in ("http", "https"):
        raise Blocked(f"only http/https addresses are allowed (got {p.scheme or 'none'}:)")
    if p.username or p.password:
        raise Blocked("addresses with user names/passwords are not allowed")
    if not p.hostname:
        raise Blocked("address has no host")
    port = port or (443 if p.scheme == "https" else 80)
    if not policy.any_port and port not in (80, 443):
        raise Blocked(f"port {port} is not allowed (only 80/443)")
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    return p.scheme, p.hostname, port, path


def resolve(host, port, policy, resolver=None):
    """-> vetted IP string. Raises Blocked / NetError."""
    try:
        infos = (resolver or socket.getaddrinfo)(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetError(f"cannot resolve {host}: {exc.strerror or exc}") from None
    ips = []
    for info in infos:
        ip = info[4][0].split("%")[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise NetError(f"cannot resolve {host}")
    for ip in ips:
        if ip in policy.allow_ips:
            continue
        if not ip_is_public(ip):
            raise Blocked(f"{host} resolves to a local/private address ({ip}); refused")
    return ips[0]


class _Conn(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _TLSConn(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class Response:
    def __init__(self, conn, resp, url, history):
        self._conn, self._resp = conn, resp
        self.status, self.url, self.history = resp.status, url, history
        self.headers = {k.lower(): v for k, v in resp.getheaders()}

    def header(self, name, default=""):
        return self.headers.get(name.lower(), default)

    def read(self, n=-1):
        try:
            return self._resp.read(n) if n >= 0 else self._resp.read()
        except (OSError, http.client.HTTPException) as exc:
            raise NetError(f"connection lost: {exc}") from None

    def close(self):
        try:
            self._resp.close()
        finally:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Client:
    def __init__(self, policy=None, ssl_context=None, resolver=None):
        self.policy = policy or Policy()
        self.ctx = ssl_context or ssl.create_default_context()
        self.ctx.check_hostname = True
        self.ctx.verify_mode = ssl.CERT_REQUIRED
        self.resolver = resolver

    def request(self, url, method="GET", headers=None):
        history = []
        for _ in range(self.policy.max_redirects + 1):
            scheme, host, port, path = check_url(url, self.policy)
            ip = resolve(host, port, self.policy, self.resolver)
            conn = (_TLSConn(host, port, ip, self.policy.timeout, self.ctx) if scheme == "https"
                    else _Conn(host, port, ip, self.policy.timeout))
            hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})}
            try:
                conn.request(method, path, headers=hdrs)
                resp = conn.getresponse()
            except ssl.SSLCertVerificationError as exc:
                conn.close()
                raise Blocked(f"TLS certificate of {host} could not be verified: {exc.verify_message}") from None
            except (OSError, http.client.HTTPException) as exc:
                conn.close()
                raise NetError(f"{host}: {exc}") from None
            if resp.status in REDIRECTS:
                loc = resp.getheader("Location", "")
                resp.close()
                conn.close()
                if not loc:
                    raise Blocked("redirect without a Location")
                nxt = urllib.parse.urljoin(url, loc)
                if scheme == "https" and nxt.startswith("http:"):
                    raise Blocked("redirect from https to plain http refused")
                history.append(redact(url))
                url = nxt
                continue
            return Response(conn, resp, url, history)
        raise Blocked(f"too many redirects (> {self.policy.max_redirects})")

    def get_bytes(self, url, limit, headers=None):
        with self.request(url, headers=headers) as r:
            if r.status != 200:
                raise NetError(f"HTTP {r.status} for {redact(url)}")
            n = r.header("content-length")
            if n.isdigit() and int(n) > limit:
                raise Blocked(f"response too large ({n} bytes > {limit})")
            data = r.read(limit + 1)
            if len(data) > limit:
                raise Blocked(f"response too large (> {limit} bytes)")
            return data, r
