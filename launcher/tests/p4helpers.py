# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A test helpers: a fake local kiwix-serve and a fake KISS TNC (loopback only), plus a
TEST-ONLY AX.25/KISS encoder (production code contains no encoder)."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DATA = Path(__file__).parent / "p4data"


class FakeKiwix:
    """Serves TESTDATA shaped like kiwix-serve 3.7 under ``root`` on 127.0.0.1:<ephemeral>."""

    def __init__(self, root="/kiwix/"):
        self.root = root
        self.requests = []
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                parts = urlsplit(self.path)
                path, q = parts.path, parse_qs(parts.query)
                r = owner.root
                if not path.startswith(r):
                    return self._send(404, b"not found", "text/plain")
                sub = path[len(r):]
                if sub == "catalog/v2/entries":
                    return self._send(200, (DATA / "opds_entries.xml").read_bytes(), "application/atom+xml")
                if sub == "search":
                    if q.get("format") != ["xml"]:
                        return self._send(200, b"<html>html results</html>", "text/html")
                    return self._send(200, (DATA / "search.xml").read_bytes(), "application/rss+xml")
                if sub == "content/testwiki_en_mini":
                    return self._redirect(r + "content/testwiki_en_mini/A/Main_Page")
                if sub == "content/testwiki_en_mini/A/Main_Page":
                    body = (b"<html><head><script>alert('x')</script><style>p{}</style></head><body>"
                            b"<h1>TESTDATA Main Page</h1><p onclick=\"evil()\">Welcome.</p>"
                            b"<img src='/kiwix/content/testwiki_en_mini/I/logo.png' alt='logo'>"
                            b"<a href='A/Water_purification'>Water purification</a> "
                            b"<a href='https://example.invalid/out'>external</a></body></html>")
                    return self._send(200, body, "text/html; charset=utf-8")
                if sub.startswith("content/testwiki_en_mini/A/"):
                    title = sub.rsplit("/", 1)[-1].replace("_", " ")
                    return self._send(200, f"<html><body><h1>{title}</h1><p>TESTDATA article.</p></body></html>"
                                      .encode(), "text/html; charset=utf-8")
                if sub == "goes-external":
                    return self._redirect("http://example.invalid/")
                return self._send(404, b"not found", "text/plain")

            def _redirect(self, loc):
                self.send_response(302)
                self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------- TEST-ONLY encoder

def enc_addr(call, last=False, repeated=False):
    base, _, ssid = call.partition("-")
    b = bytes((ord(c) << 1) for c in base.ljust(6)[:6])
    s = 0x60 | ((int(ssid or 0) & 0x0F) << 1) | (0x80 if repeated else 0) | (0x01 if last else 0)
    return b + bytes([s])


def ax25_ui(src, dest, info, path=()):
    addrs = [dest, src] + list(path)
    out = b""
    for i, a in enumerate(addrs):
        rep = a.endswith("*")
        out += enc_addr(a.rstrip("*"), last=(i == len(addrs) - 1), repeated=rep)
    return out + b"\x03\xf0" + (info.encode("latin-1") if isinstance(info, str) else info)


def kiss(payload, port=0):
    esc = payload.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc")
    return b"\xc0" + bytes([port << 4]) + esc + b"\xc0"


class FakeTnc:
    """Accepts one client, sends ``frames``, then records every byte the client sends."""

    def __init__(self, frames=()):
        self.frames = list(frames)
        self.received = bytearray()
        self.client_closed = threading.Event()
        self.sent = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            for f in self.frames:
                conn.sendall(f)
            self.sent.set()
            conn.settimeout(10)
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    break
                if not data:
                    break
                self.received.extend(data)
        self.client_closed.set()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.sock.close()
