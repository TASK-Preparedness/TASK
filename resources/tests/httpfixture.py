# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Mocked local HTTP(S) server for download/catalog tests. Behaviour per route:
data, ctype, etag, ranges (honour Range/If-Range), cut_after (close the socket after N body bytes, once
or always), redirect (Location), status, delay (seconds per chunk)."""

import http.server
import re
import ssl
import subprocess
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Route:
    data: bytes = b""
    ctype: str = "application/octet-stream"
    etag: str = '"v1"'
    ranges: bool = True
    cut_after: int = None
    cut_times: int = 1
    redirect: str = ""
    status: int = 200
    delay: float = 0.0
    disposition: str = ""
    hits: list = field(default_factory=list)


class Server:
    def __init__(self, tls_cert=None):
        self.routes = {}
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _go(self, body):
                r = srv.routes.get(self.path)
                if r is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                r.hits.append(dict(self.headers))
                if r.redirect:
                    self.send_response(r.status if r.status in (301, 302, 303, 307, 308) else 302)
                    self.send_header("Location", r.redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if r.status != 200:
                    self.send_response(r.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data, start = r.data, 0
                rng, ifr = self.headers.get("Range"), self.headers.get("If-Range")
                m = re.match(r"bytes=(\d+)-$", rng or "")
                if r.ranges and m and (ifr is None or ifr == r.etag):
                    start = int(m.group(1))
                    if start >= len(data):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(data)}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                else:
                    self.send_response(200)
                if r.ranges:
                    self.send_header("Accept-Ranges", "bytes")
                if r.etag:
                    self.send_header("ETag", r.etag)
                if r.disposition:
                    self.send_header("Content-Disposition", r.disposition)
                self.send_header("Content-Type", r.ctype)
                self.send_header("Content-Length", str(len(data) - start))
                self.end_headers()
                if not body:
                    return
                payload = data[start:]
                cut = r.cut_after if (r.cut_after is not None and r.cut_times > 0) else None
                if cut is not None:
                    r.cut_times -= 1
                    payload = payload[:cut]
                for i in range(0, len(payload), 65536):
                    if r.delay:
                        time.sleep(r.delay)
                    try:
                        self.wfile.write(payload[i:i + 65536])
                    except OSError:
                        return
                if cut is not None:
                    self.wfile.flush()
                    self.close_connection = True
                    self.connection.shutdown(2)

            def do_GET(self):
                self._go(True)

            def do_HEAD(self):
                self._go(False)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.scheme = "http"
        if tls_cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls_cert)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
            self.scheme = "https"
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path, host="127.0.0.1"):
        return f"{self.scheme}://{host}:{self.port}{path}"

    def add(self, path, **kw):
        self.routes[path] = Route(**kw)
        return self.routes[path]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def self_signed(tmpdir, cn="localhost"):
    key, crt = f"{tmpdir}/key.pem", f"{tmpdir}/crt.pem"
    subprocess.run(["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
                    "-out", crt, "-days", "2", "-subj", f"/CN={cn}",
                    "-addext", f"subjectAltName=DNS:{cn},IP:127.0.0.1"], check=True, capture_output=True)
    return crt, key
