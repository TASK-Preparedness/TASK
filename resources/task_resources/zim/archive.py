# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Read-only ZIM access on python3-libzim. This is the only code that touches ZIM files.

No HTTP server, no Kiwix: entries are read directly with libzim and handed to the viewers as bytes.
"""

import posixpath
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

try:
    from libzim.reader import Archive as _Archive
    from libzim.search import Query, Searcher
    from libzim.suggestion import SuggestionSearcher
    LIBZIM_ERROR = ""
except ImportError as exc:  # pragma: no cover - reported in the UI
    _Archive = None
    LIBZIM_ERROR = f"python3-libzim is not installed ({exc})"

MAX_REDIRECTS = 10
DEFAULT_MAX_ITEM = 64 * 1024 * 1024
METADATA_KEYS = ("Title", "Description", "LongDescription", "Language", "Creator", "Publisher", "Date",
                 "Name", "Flavour", "Tags", "Source", "License")


class ZimError(Exception):
    pass


class EntryNotFound(ZimError):
    pass


class RedirectLoop(ZimError):
    pass


@dataclass
class Content:
    path: str                 # final path after redirects
    title: str
    mimetype: str
    data: bytes
    redirected_from: list = field(default_factory=list)

    @property
    def is_html(self):
        return self.mimetype.split(";")[0].strip() in ("text/html", "application/xhtml+xml")


@dataclass
class SearchResult:
    mode: str                  # "full-text" | "title-only"
    hits: list                 # [(path, title)]
    estimated: int
    note: str = ""


class ZimArchive:
    kind = "zim"
    scheme = "zim"

    def __init__(self, path, max_item=DEFAULT_MAX_ITEM):
        if _Archive is None:
            raise ZimError(LIBZIM_ERROR)
        self.path = str(path)
        self.max_item = max_item
        self._lock = threading.RLock()   # libzim objects are shared between the UI and worker threads
        try:
            self.a = _Archive(self.path)
            self.uuid = str(self.a.uuid)
        except RuntimeError as exc:
            raise ZimError(f"cannot open ZIM: {exc}") from None

    # ---------------------------------------------------------------- facts
    @property
    def has_fulltext(self):
        return bool(self.a.has_fulltext_index)

    @property
    def has_title_index(self):
        return bool(self.a.has_title_index)

    @property
    def is_multipart(self):
        return bool(self.a.is_multipart)

    def metadata(self):
        out = {}
        with self._lock:
            keys = set(self.a.metadata_keys)
            for k in METADATA_KEYS:
                if k in keys:
                    try:
                        out[k] = bytes(self.a.get_metadata(k)).decode("utf-8", "replace")
                    except RuntimeError:
                        pass
        return out

    def illustration(self, size=48):
        with self._lock:
            try:
                if self.a.has_illustration(size):
                    return bytes(self.a.get_illustration_item(size).content)
            except (RuntimeError, AttributeError):
                pass
        return None

    def main_path(self):
        with self._lock:
            if not self.a.has_main_entry:
                return None
            e = self.a.main_entry
            return self._follow(e)[0].path

    # ---------------------------------------------------------------- entries
    def _lookup(self, path):
        path = path.lstrip("/")
        candidates = [path]
        # old namespace scheme (pre-2021 ZIMs): links like "A/Foo" or "../I/img.png"
        head, _, rest = path.partition("/")
        if len(head) == 1 and head.isalpha() and rest:
            candidates.append(rest)
        if "%" in path:                      # 0.2.4: a still-URL-encoded reference ("A_%28b%29.jpg")
            from urllib.parse import unquote
            candidates += [unquote(c) for c in list(candidates) if unquote(c) != c]
        for p in candidates:
            if p and self.a.has_entry_by_path(p):
                return self.a.get_entry_by_path(p)
        raise EntryNotFound(path)

    def _follow(self, entry):
        chain, seen = [], set()
        while entry.is_redirect:
            if entry.path in seen or len(chain) >= MAX_REDIRECTS:
                raise RedirectLoop(" -> ".join(chain + [entry.path]))
            seen.add(entry.path)
            chain.append(entry.path)
            entry = entry.get_redirect_entry()
        return entry, chain

    def resolve(self, path):
        """Final path after redirects, and the chain of redirect paths."""
        with self._lock:
            e, chain = self._follow(self._lookup(path))
            return e.path, chain

    def get(self, path, max_bytes=None):
        limit = self.max_item if max_bytes is None else max_bytes
        with self._lock:
            e, chain = self._follow(self._lookup(path))
            item = e.get_item()
            if item.size > limit:
                raise ZimError(f"{e.path}: {item.size} bytes is above the {limit} byte limit")
            return Content(e.path, e.title, item.mimetype, bytes(item.content), chain)

    def exists(self, path):
        with self._lock:
            try:
                self._lookup(path)
                return True
            except EntryNotFound:
                return False

    # ---------------------------------------------------------------- search
    def suggest(self, text, limit=25):
        """Title search (libzim title index / title listing)."""
        text = str(text).strip()
        if not text:
            return SearchResult("title-only", [], 0)
        with self._lock:
            s = SuggestionSearcher(self.a).suggest(text)
            est = s.getEstimatedMatches()
            hits = [(p, self._title(p)) for p in s.getResults(0, limit)]
        return SearchResult("title-only", hits, est)

    def search(self, text, limit=25, offset=0):
        """Full-text search when the ZIM has an Xapian index, otherwise an honest title search."""
        text = str(text).strip()
        if not self.has_fulltext:
            r = self.suggest(text, limit)
            r.note = "Title search only — this ZIM has no full-text index."
            return r
        if not text:
            return SearchResult("full-text", [], 0)
        with self._lock:
            s = Searcher(self.a).search(Query().set_query(text))
            est = s.getEstimatedMatches()
            hits = [(p, self._title(p)) for p in s.getResults(offset, limit)]
        return SearchResult("full-text", hits, est)

    def _title(self, path):
        try:
            return self.a.get_entry_by_path(path).title
        except (RuntimeError, KeyError):
            return path

    def check(self):
        """Full integrity check (reads the whole file; use from a background job)."""
        with self._lock:
            return bool(self.a.check()) if self.a.has_checksum else None

    def close(self):
        self.a = None


def join(base_path, href):
    """Resolve a relative link inside an archive against the current entry path (never above the root)."""
    href = href.split("#", 1)[0].split("?", 1)[0]
    if href.startswith("/"):
        joined = posixpath.normpath(href.lstrip("/"))
    else:
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), href))
    while joined.startswith("../") or joined == "..":
        joined = joined[3:]
    return "" if joined == "." else joined.lstrip("/")


class SourcePool:
    """Open sources (ZIM/EPUB/local HTML) by resource id, LRU-limited to bound memory."""

    def __init__(self, opener, capacity=8):
        self.opener, self.capacity = opener, capacity
        self._open = OrderedDict()
        self._lock = threading.Lock()

    def get(self, rid):
        with self._lock:
            if rid in self._open:
                self._open.move_to_end(rid)
                return self._open[rid]
        src = self.opener(rid)
        with self._lock:
            self._open[rid] = src
            while len(self._open) > self.capacity:
                _, old = self._open.popitem(last=False)
                getattr(old, "close", lambda: None)()
        return src

    def drop(self, rid):
        with self._lock:
            self._open.pop(rid, None)

    def clear(self):
        with self._lock:
            self._open.clear()
