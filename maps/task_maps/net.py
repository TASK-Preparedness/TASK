# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""HTTP tile fetch (stdlib urllib; no extra dependency). Identifying User-Agent on every
request; no cache-busting headers; body size capped; HTTP errors returned as status codes and
connection-level failures raised as ``NetworkError``."""

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

from task_maps import USER_AGENT
from task_maps.mbtiles import MAX_TILE_BYTES

MAX_RETRY_AFTER = 900.0


class NetworkError(Exception):
    """No HTTP response at all (DNS failure, refused, unreachable, timeout, reset)."""


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class _NoRedirectToOtherScheme(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith(("http://", "https://")):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_NoRedirectToOtherScheme)


def user_agent(contact: str = "") -> str:
    contact = "".join(c for c in contact if c.isprintable())[:120]
    return f"{USER_AGENT[:-1]}; {contact})" if contact else USER_AGENT


def fetch(url: str, ua: str = USER_AGENT, timeout: float = 20.0) -> Response:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "image/png,image/jpeg,image/webp,image/*;q=0.8"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            body = r.read(MAX_TILE_BYTES + 1)
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, body)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(4096)
        except Exception:   # noqa: BLE001
            body = b""
        return Response(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body)
    except urllib.error.URLError as exc:
        raise NetworkError(str(exc.reason)) from None
    except (socket.timeout, TimeoutError) as exc:
        raise NetworkError(f"timeout: {exc}") from None
    except (ConnectionError, OSError) as exc:
        raise NetworkError(str(exc)) from None


def retry_after(headers: dict, now: float = None, default: float = 30.0) -> float:
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP-date), capped."""
    v = (headers or {}).get("retry-after")
    if not v:
        return default
    v = v.strip()
    if v.isdigit():
        return min(MAX_RETRY_AFTER, float(v))
    try:
        dt = parsedate_to_datetime(v)
        delta = dt.timestamp() - (now if now is not None else time.time())
        return min(MAX_RETRY_AFTER, max(0.0, delta))
    except (TypeError, ValueError, OverflowError):
        return default
