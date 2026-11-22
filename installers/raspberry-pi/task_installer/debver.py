# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Debian version comparison (deb-version(7) algorithm), pure Python, so plans can detect
downgrades without running dpkg. Cross-checked against ``dpkg --compare-versions`` in the tests."""
from __future__ import annotations

import re


def _split(v: str):
    v = v.strip()
    epoch, _, rest = v.partition(":") if ":" in v else ("0", "", v)
    if "-" in rest:
        upstream, _, revision = rest.rpartition("-")
    else:
        upstream, revision = rest, "0"
    return int(epoch or 0), upstream, revision


def _order(c: str) -> int:
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    return ord(c) + 256


def _cmp_part(a: str, b: str) -> int:
    while a or b:
        na = re.match(r"[^0-9]*", a).group(0)
        nb = re.match(r"[^0-9]*", b).group(0)
        a, b = a[len(na):], b[len(nb):]
        for i in range(max(len(na), len(nb))):
            ca = _order(na[i]) if i < len(na) else 0
            cb = _order(nb[i]) if i < len(nb) else 0
            if ca != cb:
                return -1 if ca < cb else 1
        da = re.match(r"[0-9]*", a).group(0)
        db = re.match(r"[0-9]*", b).group(0)
        a, b = a[len(da):], b[len(db):]
        ia, ib = int(da or 0), int(db or 0)
        if ia != ib:
            return -1 if ia < ib else 1
    return 0


def compare(a: str, b: str) -> int:
    """-1 if a < b, 0 if equal, 1 if a > b (Debian ordering)."""
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return -1 if ea < eb else 1
    return _cmp_part(ua, ub) or _cmp_part(ra, rb)
