# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Kiwix / IIAB library discovery and kiwix-serve HTTP API client (read-only, loopback only).

Endpoint discovery never assumes a port. Sources, in order of trust:

1. systemd units ``kiwix*`` / ``iiab*`` (``systemctl list-units`` + ``systemctl show -p ExecStart``):
   their kiwix-serve argv gives port, address, ``--urlRootLocation`` and ``--library`` path;
2. running ``kiwix-serve`` processes (``/proc/<pid>/cmdline``, readable without root);
3. IIAB configuration (``/etc/iiab/local_vars.yml``, ``/etc/iiab/iiab_state.yml``,
   ``/opt/iiab/iiab/vars/default_vars.yml``): ``kiwix_port``, ``kiwix_url``, ``iiab_zim_path``;
4. only if nothing above verified: the documented defaults (IIAB 3000 + ``/kiwix/``; kiwix-serve
   example 8080 + ``/``), labelled "default candidate".

Every candidate is *verified* by fetching ``<root>catalog/v2/entries?count=1`` from 127.0.0.1 and
checking that the reply is an Atom feed. Unverified candidates are never shown as working.

HTTP API (kiwix-tools 3.7.0 / libkiwix 14 in Debian trixie, https://kiwix-tools.readthedocs.io):
``/catalog/v2/entries`` (public, OPDS Atom), ``/search?books.name=..&pattern=..&format=xml``
(public, RSS + OpenSearch), ``/content/<book>/<path>`` (private; we follow the links the server
itself returns rather than constructing paths), ``/catalog/root.xml`` (legacy fallback).

The launcher never starts, stops or reconfigures kiwix-serve.
"""

import html
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

from task_launcher.services import probe

IIAB_CONFIGS = (Path("/etc/iiab/local_vars.yml"), Path("/etc/iiab/iiab_state.yml"),
                Path("/opt/iiab/iiab/vars/default_vars.yml"))
LIBRARY_XML_CANDIDATES = (Path("/library/zims/library.xml"), Path("/library/zims/library_zim.xml"))
DEFAULT_CANDIDATES = ((3000, "/kiwix/", "default candidate: IIAB kiwix_port 3000, kiwix_url /kiwix"),
                      (8080, "/", "default candidate: kiwix-serve documentation example port 8080"))
ATOM = "{http://www.w3.org/2005/Atom}"
CATALOG_COUNT = 500
ANY_ADDRESSES = {"all", "ipv4", "ipv6", "0.0.0.0", "::", "[::]"}


@dataclass
class Candidate:
    port: int
    root: str = "/"
    source: str = ""
    library_xml: list = field(default_factory=list)
    address: str = ""
    verified: bool = False
    error: str = ""
    legacy_catalog: bool = False

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}{self.root}"

    @property
    def label(self):
        return f"localhost:{self.port}{self.root}"


@dataclass
class Book:
    id: str = ""
    name: str = ""
    title: str = ""
    summary: str = ""
    language: str = ""
    category: str = ""
    tags: str = ""
    flavour: str = ""
    articles: int = None
    media: int = None
    size_bytes: int = None
    updated: str = ""
    content_href: str = ""        # server-relative link to the book's main page ("" if unknown)
    file_path: str = ""           # from library XML
    file_present: bool = None
    source: str = "catalog"       # catalog | library-xml


@dataclass
class SearchHit:
    title: str
    href: str
    snippet: str = ""
    book_title: str = ""
    words: int = None


@dataclass
class SearchResult:
    hits: list = field(default_factory=list)
    total: int = None
    error: str = ""


@dataclass
class KiwixStatus:
    endpoint: Candidate = None
    candidates: list = field(default_factory=list)
    units: list = field(default_factory=list)
    processes: list = field(default_factory=list)
    binaries: dict = field(default_factory=dict)
    iiab: dict = field(default_factory=dict)
    library_files: list = field(default_factory=list)   # (path, exists, n_books)
    books: list = field(default_factory=list)
    catalog_error: str = ""

    @property
    def ready(self):
        return self.endpoint is not None

    def summary(self):
        if self.endpoint:
            n = len(self.books)
            return f"Kiwix server ready · {n} collection{'s' if n != 1 else ''} · {self.endpoint.label}"
        offline = [f for f in self.library_files if f[1]]
        if offline:
            return "Kiwix library file found · server not reachable"
        if self.binaries or self.units or self.processes:
            return "kiwix-serve installed · no running server found"
        return "No Kiwix server or library found"


# ---------------------------------------------------------------- kiwix-serve argv

def parse_serve_argv(argv):
    """dict(port, address, root, library (list), zims (list)) from a kiwix-serve argv."""
    out = {"port": None, "address": "", "root": "/", "library": [], "zims": [], "is_library": False}
    if not argv or "kiwix-serve" not in os.path.basename(argv[0]):
        return None
    i, positional = 1, []
    short_val = {"-p": "port", "-i": "address", "-r": "root"}
    long_val = {"--port": "port", "--address": "address", "--urlRootLocation": "root"}
    skip_val = {"-t", "--threads", "-s", "--searchLimit", "-c", "--customIndex", "-L", "--ipConnectionLimit",
                "-a", "--attachToProcess", "--contentServerURL"}
    while i < len(argv):
        a = argv[i]
        key = val = None
        if a == "--library":
            out["is_library"] = True
        elif "=" in a and a.split("=", 1)[0] in long_val:
            key, val = long_val[a.split("=", 1)[0]], a.split("=", 1)[1]
        elif a in long_val or a in short_val:
            key = long_val.get(a) or short_val.get(a)
            i += 1
            val = argv[i] if i < len(argv) else ""
        elif a[:2] in short_val and len(a) > 2:
            key, val = short_val[a[:2]], a[2:]
        elif a.split("=", 1)[0] in skip_val:
            if "=" not in a:
                i += 1                         # option with a separate value we do not need
        elif a.startswith("-"):
            pass
        else:
            positional.append(a)
        if key == "port":
            try:
                out["port"] = int(val)
            except (TypeError, ValueError):
                pass
        elif key == "address":
            out["address"] = val
        elif key == "root":
            out["root"] = normalize_root(val)
        i += 1
    if out["port"] is None:
        out["port"] = 80                      # kiwix-serve documented default
    if out["is_library"]:
        for p in positional:
            out["library"].extend(x for x in p.split(";") if x)
    else:
        out["zims"] = positional
    return out


def normalize_root(root: str) -> str:
    root = (root or "").strip()
    if not root or root == "/":
        return "/"
    return "/" + root.strip("/") + "/"


def _address_reachable(address: str) -> bool:
    if not address or address in ANY_ADDRESSES:
        return True
    try:
        probe.ensure_loopback(address)
        return True
    except probe.NotLoopback:
        return False


def read_iiab(paths=IIAB_CONFIGS):
    """Simple ``key: value`` read of the IIAB YAML files (no YAML dependency, first match wins in
    the order local_vars > iiab_state > default_vars)."""
    found = {}
    files = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:512 * 1024]
        except OSError:
            continue
        files.append(str(p))
        for line in text.splitlines():
            m = re.match(r"^(kiwix_port|kiwix_url|kiwix_install|kiwix_enabled|kiwix_installed|iiab_zim_path|"
                         r"content_base)\s*:\s*(.*?)\s*(#.*)?$", line)
            if m and m.group(1) not in found:
                found[m.group(1)] = m.group(2).strip().strip("'\"")
    if files:
        found["_files"] = files
    return found


# ---------------------------------------------------------------- discovery

def discover(units_fn=None, procs_fn=None, iiab_fn=read_iiab, http=probe.http_get,
             library_candidates=LIBRARY_XML_CANDIDATES, binaries_fn=None, fetch_catalog=True):
    st = KiwixStatus()
    units_fn = units_fn or (lambda: probe.list_units(["kiwix*", "iiab*"]))
    procs_fn = procs_fn or (lambda: probe.processes(["kiwix-serve"]))
    binaries_fn = binaries_fn or (lambda: _kiwix_binaries())
    st.binaries = binaries_fn()
    st.units = units_fn()
    st.processes = procs_fn()
    st.iiab = iiab_fn()
    cands, seen = [], set()

    def add(port, root, source, library=(), address=""):
        key = (port, normalize_root(root))
        if key in seen:
            for c in cands:
                if (c.port, c.root) == key:
                    c.library_xml.extend(x for x in library if x not in c.library_xml)
            return
        seen.add(key)
        cands.append(Candidate(port, normalize_root(root), source, list(library), address))

    for u in st.units:
        args = parse_serve_argv(u.exec_argv)
        if args:
            if _address_reachable(args["address"]):
                add(args["port"], args["root"], f"systemd unit {u.name} ({u.active}/{u.sub})", args["library"],
                    args["address"])
    for p in st.processes:
        args = parse_serve_argv(p.argv)
        if args and _address_reachable(args["address"]):
            add(args["port"], args["root"], f"running kiwix-serve (pid {p.pid})", args["library"], args["address"])
    if st.iiab.get("kiwix_port"):
        try:
            port = int(st.iiab["kiwix_port"])
            zim = st.iiab.get("iiab_zim_path", "").replace("{{ content_base }}", st.iiab.get("content_base", "/library"))
            lib = [os.path.join(zim, "library.xml")] if zim.startswith("/") else []
            add(port, st.iiab.get("kiwix_url", "/kiwix") or "/kiwix", "IIAB configuration (" +
                ", ".join(os.path.basename(f) for f in st.iiab.get("_files", [])) + ")", lib)
        except ValueError:
            pass
    for c in cands:
        verify(c, http)
    if not any(c.verified for c in cands):
        for port, root, source in DEFAULT_CANDIDATES:
            if (port, root) not in seen:
                c = Candidate(port, root, source)
                verify(c, http)
                cands.append(c)
                seen.add((port, root))
    st.candidates = cands
    st.endpoint = next((c for c in cands if c.verified), None)

    libs = []
    for c in cands:
        libs.extend(c.library_xml)
    libs.extend(str(p) for p in library_candidates)
    seen_l = set()
    lib_books = []
    for path in libs:
        if path in seen_l:
            continue
        seen_l.add(path)
        p = Path(path)
        if p.is_file():
            books = parse_library_xml_file(p)
            st.library_files.append((str(p), True, len(books)))
            lib_books.extend(books)
        else:
            st.library_files.append((str(p), False, 0))
    if st.endpoint and fetch_catalog:
        books, err = fetch_books(st.endpoint, http)
        st.books, st.catalog_error = books, err
        if books:
            by_name = {b.name: b for b in lib_books}
            for b in books:
                lb = by_name.get(b.name)
                if lb:
                    b.file_path, b.file_present = lb.file_path, lb.file_present
    elif not st.endpoint:
        st.books = lib_books
    return st


def _kiwix_binaries():
    out = probe.find_program(["kiwix-serve"])
    iiab = "/opt/iiab/kiwix/bin/kiwix-serve"
    if os.path.isfile(iiab) and os.access(iiab, os.X_OK):
        out["kiwix-serve (IIAB)"] = iiab
    return out


def verify(c: Candidate, http=probe.http_get):
    r = http(c.base_url + "catalog/v2/entries?count=1")
    if r.ok and _is_atom(r.body):
        c.verified = True
        return True
    r2 = http(c.base_url + "catalog/root.xml")
    if r2.ok and _is_atom(r2.body):
        c.verified, c.legacy_catalog = True, True
        return True
    c.error = r.error or (f"HTTP {r.status}" if r.status else "no reply") + (
        "" if not r.ok else " (not an OPDS feed)")
    return False


def _is_atom(body: bytes) -> bool:
    try:
        root = _parse_xml(body)
    except ET.ParseError:
        return False
    return root.tag == ATOM + "feed"


def _parse_xml(body: bytes):
    if b"<!DOCTYPE" in body[:2048] or b"<!ENTITY" in body[:65536]:
        raise ET.ParseError("DTD/entities refused")
    return ET.fromstring(body)


# ---------------------------------------------------------------- OPDS catalog

def fetch_books(c: Candidate, http=probe.http_get):
    url = c.base_url + ("catalog/root.xml" if c.legacy_catalog else f"catalog/v2/entries?count={CATALOG_COUNT}")
    r = http(url, timeout=4.0)
    if not r.ok:
        return [], r.error or f"HTTP {r.status}"
    try:
        return parse_opds(r.body), ""
    except ET.ParseError as exc:
        return [], f"catalog could not be parsed: {exc}"


def _local(tag):
    return tag.split("}", 1)[-1]


def _int(text):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def parse_opds(body: bytes):
    root = _parse_xml(body)
    books = []
    for entry in root.iter(ATOM + "entry"):
        b = Book()
        for ch in entry:
            name, text = _local(ch.tag), (ch.text or "").strip()
            if name == "id":
                b.id = text.replace("urn:uuid:", "")
            elif name == "title":
                b.title = text
            elif name in ("summary", "content") and not b.summary:
                b.summary = text
            elif name == "language":
                b.language = text
            elif name == "name":
                b.name = text
            elif name == "category":
                b.category = text or ch.get("term", "")
            elif name == "tags":
                b.tags = text
            elif name == "flavour":
                b.flavour = text
            elif name == "articleCount":
                b.articles = _int(text)
            elif name == "mediaCount":
                b.media = _int(text)
            elif name == "updated":
                b.updated = text
            elif name == "link":
                rel, typ, href = ch.get("rel", ""), ch.get("type", ""), ch.get("href", "")
                if typ.startswith("text/html") and href and not b.content_href:
                    b.content_href = href
                elif typ == "application/x-zim" and ch.get("length"):
                    b.size_bytes = _int(ch.get("length"))
        if b.title or b.name:
            books.append(b)
    return books


def parse_library_xml_file(path: Path, max_bytes=8 * 1024 * 1024):
    try:
        data = path.read_bytes()[:max_bytes]
        return parse_library_xml(data, path.parent)
    except (OSError, ET.ParseError):
        return []


def parse_library_xml(body: bytes, base: Path):
    root = _parse_xml(body)
    books = []
    for el in root.iter("book"):
        a = el.attrib
        b = Book(id=a.get("id", ""), name=a.get("name", ""), title=a.get("title", ""),
                 summary=a.get("description", ""), language=a.get("language", ""), tags=a.get("tags", ""),
                 flavour=a.get("flavour", ""), articles=_int(a.get("articleCount")),
                 media=_int(a.get("mediaCount")), updated=a.get("date", ""), source="library-xml")
        size_kb = _int(a.get("size"))
        b.size_bytes = size_kb * 1024 if size_kb is not None else None
        rel = a.get("path", "")
        if rel:
            p = Path(rel) if rel.startswith("/") else base / rel
            b.file_path = str(p)
            b.file_present = p.is_file()
        if not b.name and rel:
            b.name = re.sub(r"\.zim$", "", os.path.basename(rel)).lower()
        books.append(b)
    return books


# ---------------------------------------------------------------- search and content

def search_url(c: Candidate, book: Book, pattern: str, page_length=25):
    q = {"books.name": book.name, "pattern": pattern, "format": "xml", "pageLength": str(page_length)}
    return c.base_url + "search?" + urlencode(q, quote_via=quote)


def search(c: Candidate, book: Book, pattern: str, http=probe.http_get):
    r = http(search_url(c, book, pattern), timeout=6.0)
    if not r.ok:
        return SearchResult(error=r.error or f"HTTP {r.status}")
    try:
        return parse_search_xml(r.body)
    except ET.ParseError:
        return SearchResult(error="this kiwix-serve did not return XML search results "
                                  "(format=xml unsupported?) — use “Open in browser”")


def parse_search_xml(body: bytes) -> SearchResult:
    root = _parse_xml(body)
    if _local(root.tag) != "rss":
        raise ET.ParseError("not an RSS document")
    res = SearchResult()
    channel = root.find("channel")
    if channel is None:
        return res
    for ch in channel:
        if _local(ch.tag) == "totalResults":
            res.total = _int(ch.text)
    for item in channel.iter("item"):
        title = (item.findtext("title") or "").strip()
        href = (item.findtext("link") or "").strip()
        snippet = strip_tags(item.findtext("description") or "")
        book = item.find("book")
        bt = (book.findtext("title") or "").strip() if book is not None else ""
        res.hits.append(SearchHit(title or href, href, snippet, bt, _int(item.findtext("wordCount"))))
    return res


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def absolute(c: Candidate, href: str) -> str:
    """Resolve a server-returned href against the endpoint; only same-host loopback URLs pass."""
    url = urljoin(c.base_url, href)
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost", "::1") or \
            (parts.port or 80) != c.port:
        return ""
    return url


def browser_url(url: str) -> str:
    """URL handed to the desktop browser: same address with 'localhost' (works in any browser)."""
    return url.replace("http://127.0.0.1:", "http://localhost:", 1)


_DROP = re.compile(r"<(script|style|iframe|object|embed|noscript)\b.*?</\1\s*>", re.S | re.I)


def fetch_page(c: Candidate, url: str, http=probe.http_get, max_redirects=3):
    """(final url, simplified html, error). Follows same-endpoint redirects only."""
    for _ in range(max_redirects + 1):
        if not url:
            return "", "", "link points outside the local Kiwix server — not opened"
        r = http(url, timeout=5.0)
        if r.status in (301, 302, 303, 307, 308) and r.location:
            url = absolute(c, urljoin(url, r.location))
            continue
        if not r.ok:
            return url, "", r.error or f"HTTP {r.status}"
        if "html" not in r.content_type and "xml" not in r.content_type:
            return url, "", f"not a text page ({r.content_type or 'unknown type'}) — use “Open in browser”"
        text = r.body.decode("utf-8", "replace")
        return url, simplify_html(text), ""
    return url, "", "too many redirects"


def simplify_html(text: str) -> str:
    text = _DROP.sub("", text)
    text = re.sub(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text, flags=re.I)
    return text
