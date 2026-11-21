# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""In-app URLs: <scheme>://r<resource id>/<entry path>. scheme is zim, epub or local. No network scheme."""

from urllib.parse import quote, unquote, urlsplit

SCHEMES = ("zim", "epub", "local")
SAFE = "/-._~!$&'()*+,;=:@"


def make(scheme, rid, path, fragment=""):
    if scheme not in SCHEMES:
        raise ValueError(scheme)
    url = f"{scheme}://r{int(rid)}/{quote(path.lstrip('/'), safe=SAFE)}"
    return url + (f"#{quote(fragment, safe=SAFE)}" if fragment else "")


def parse(url):
    """-> (scheme, rid, path, fragment) or None for anything that is not an in-app URL."""
    parts = urlsplit(str(url))
    if parts.scheme not in SCHEMES or not (parts.netloc or "").startswith("r"):
        return None
    try:
        rid = int(parts.netloc[1:])
    except ValueError:
        return None
    return parts.scheme, rid, unquote(parts.path.lstrip("/")), unquote(parts.fragment)


def is_external(href):
    s = urlsplit(href).scheme.lower()
    return bool(s) and s not in SCHEMES
