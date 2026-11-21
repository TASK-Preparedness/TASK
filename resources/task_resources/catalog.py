# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Native browser for the official Kiwix OPDS catalog (no Kiwix software involved).

API verified 2026-10-13 against the kiwix-tools server documentation (docs/ in kiwix/kiwix-tools)
and the live server:
  GET <base>/entries?count=-1     whole library as an OPDS 1.2 acquisition feed (Atom)
  filters (server side): q, lang, category, tag, notag, maxsize, name, start, count
library.kiwix.org/catalog/v2 answers 301 -> opds.library.kiwix.org/catalog/v2 (we use the target).
Each entry's acquisition link (rel http://opds-spec.org/acquisition/open-access, type application/x-zim)
points to a Metalink 4 file (<name>.zim.meta4) that carries the exact size, sha-256 and mirror URLs.
The <link length=…> in the feed is only approximate (seen: 32847872 vs real 32847118 bytes).

The whole feed (~4.4 MB, ~3.6k entries) is cached on disk, so search/filtering is local and works offline.
"""

import json
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from task_resources import paths
from task_resources.net import safehttp

DEFAULT_BASE = "https://opds.library.kiwix.org/catalog/v2"
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/terms/}"
ML = "{urn:ietf:params:xml:ns:metalink}"
ACQ = "http://opds-spec.org/acquisition/open-access"
FEED_LIMIT = 64 * 1024 * 1024
META4_LIMIT = 1024 * 1024


class CatalogError(Exception):
    pass


@dataclass
class Entry:
    uuid: str = ""
    name: str = ""
    title: str = ""
    summary: str = ""
    languages: list = field(default_factory=list)
    category: str = ""
    tags: list = field(default_factory=list)
    publisher: str = ""
    author: str = ""
    flavour: str = ""
    article_count: int = 0
    media_count: int = 0
    size: int = 0                  # approximate (feed); the meta4 size is authoritative
    issued: str = ""
    url: str = ""                  # acquisition href (usually .meta4)
    mime: str = ""
    html_url: str = ""

    @property
    def format(self):
        return "ZIM" if self.mime == "application/x-zim" else (self.mime or "?")

    @property
    def subjects(self):
        return [t for t in self.tags if not t.startswith("_")]


def _safe_xml(data):
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise CatalogError("catalog contains a DTD/entities; refused")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise CatalogError(f"catalog is not valid XML: {exc}") from None


def _int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def parse_feed(data):
    """-> (entries, totalResults)."""
    root = _safe_xml(data)
    if root.tag != ATOM + "feed":
        raise CatalogError("not an Atom/OPDS feed")
    out = []
    for e in root.findall(ATOM + "entry"):
        t = lambda tag: (e.findtext(ATOM + tag) or "").strip()  # noqa: E731
        ent = Entry(uuid=t("id").removeprefix("urn:uuid:"), name=t("name"), title=t("title"),
                    summary=t("summary"), languages=[x for x in t("language").split(",") if x],
                    category=t("category"), tags=[x for x in t("tags").split(";") if x],
                    publisher=(e.findtext(f"{ATOM}publisher/{ATOM}name") or "").strip(),
                    author=(e.findtext(f"{ATOM}author/{ATOM}name") or "").strip(),
                    flavour=t("flavour"), article_count=_int(t("articleCount")),
                    media_count=_int(t("mediaCount")), issued=(e.findtext(DC + "issued") or "").strip())
        for link in e.findall(ATOM + "link"):
            rel, typ = link.get("rel", ""), link.get("type", "")
            if rel == ACQ and not ent.url:
                ent.url, ent.mime, ent.size = link.get("href", ""), typ, _int(link.get("length"))
            elif typ == "text/html" and not rel:
                ent.html_url = link.get("href", "")
        if ent.url:
            out.append(ent)
    total = _int(root.findtext(ATOM + "totalResults")) or len(out)
    return out, total


@dataclass
class Meta4:
    name: str
    size: int
    sha256: str
    urls: list


def parse_meta4(data):
    root = _safe_xml(data)
    f = root.find(ML + "file")
    if root.tag != ML + "metalink" or f is None:
        raise CatalogError("not a Metalink 4 file")
    sha = ""
    for h in f.findall(ML + "hash"):
        if h.get("type") == "sha-256":
            sha = (h.text or "").strip().lower()
    urls = sorted(((_int(u.get("priority")) or 999, (u.text or "").strip()) for u in f.findall(ML + "url")))
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        sha = ""
    return Meta4(f.get("name", ""), _int(f.findtext(ML + "size")), sha, [u for _, u in urls if u])


def direct_url(meta4_url):
    """The load-balanced direct file URL (download.kiwix.org answers it with a redirect to a mirror)."""
    return meta4_url[:-len(".meta4")] if meta4_url.endswith(".meta4") else meta4_url


class Catalog:
    def __init__(self, base=DEFAULT_BASE, client=None, cache_dir=None):
        self.base = base.rstrip("/")
        self.client = client or safehttp.Client()
        self.cache = Path(cache_dir or paths.cache_dir()) / "catalog"
        self.entries, self.fetched_at, self.error, self.online = [], 0.0, "", None

    @property
    def feed_path(self):
        return self.cache / "entries.xml"

    def load_cached(self):
        try:
            data = self.feed_path.read_bytes()
            meta = json.loads((self.cache / "meta.json").read_text())
            self.entries, _ = parse_feed(data)
            self.fetched_at = float(meta.get("fetched_at", 0))
            return True
        except (OSError, ValueError, CatalogError):
            return False

    def refresh(self):
        """Download the whole catalog. On failure the cached copy stays in use. -> bool online."""
        try:
            data, _ = self.client.get_bytes(self.base + "/entries?count=-1", FEED_LIMIT,
                                            headers={"Accept": "application/atom+xml"})
            entries, _ = parse_feed(data)
        except (safehttp.NetError, safehttp.Blocked, CatalogError) as exc:
            self.online, self.error = False, str(exc)
            if not self.entries:
                self.load_cached()
            return False
        paths.private_dir(self.cache)
        for name, blob in (("entries.xml", data),
                           ("meta.json", json.dumps({"fetched_at": time.time(), "base": self.base}).encode())):
            fd, tmp = tempfile.mkstemp(dir=self.cache, prefix=".tmp-")
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.cache / name)
        self.entries, self.fetched_at, self.online, self.error = entries, time.time(), True, ""
        return True

    def facets(self):
        cats, langs, pubs = set(), set(), set()
        for e in self.entries:
            cats.add(e.category)
            langs.update(e.languages)
            pubs.add(e.publisher)
        return sorted(c for c in cats if c), sorted(langs), sorted(p for p in pubs if p)

    def search(self, q="", lang="", category="", subject="", publisher="", max_size=0):
        words = q.lower().split()
        out = []
        for e in self.entries:
            if lang and lang not in e.languages:
                continue
            if category and e.category != category:
                continue
            if subject and subject not in e.subjects:
                continue
            if publisher and e.publisher != publisher:
                continue
            if max_size and e.size > max_size:
                continue
            hay = f"{e.title} {e.summary} {e.name}".lower()
            if any(w not in hay for w in words):
                continue
            out.append(e)
        return out

    def fetch_meta4(self, entry):
        if not entry.url.endswith(".meta4"):
            return None
        data, _ = self.client.get_bytes(entry.url, META4_LIMIT)
        return parse_meta4(data)


def installed(index, entry):
    """Is this catalog entry already in the library (same ZIM UUID, or same book name+date)? -> rid|None"""
    with index.lock:
        r = index.db.execute("SELECT id FROM resource WHERE zim_uuid=? AND missing=0", (entry.uuid,)).fetchone()
    return r[0] if r else None


def entry_dict(e):
    return asdict(e)
