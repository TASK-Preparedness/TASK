# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""A single local HTML/TXT/MD file (and the images next to it) as a read-only source.

Only files inside the file's own folder can be read through it: links that climb out are refused."""

import mimetypes
import os
from pathlib import Path

from task_resources.zim.archive import Content, EntryNotFound, SearchResult, ZimError

MAX_ITEM = 32 * 1024 * 1024


class LocalSource:
    kind = "local"
    scheme = "local"
    has_fulltext = False

    def __init__(self, path):
        self.file = Path(path).resolve()
        self.root = self.file.parent

    def metadata(self):
        return {"Title": self.file.stem}

    def main_path(self):
        return self.file.name

    def _safe(self, path):
        p = (self.root / path.lstrip("/")).resolve()
        if self.root not in p.parents and p != self.root:
            raise EntryNotFound(path)
        if not p.is_file():
            raise EntryNotFound(path)
        return p

    def resolve(self, path):
        return str(self._safe(path).relative_to(self.root)), []

    def exists(self, path):
        try:
            self._safe(path)
            return True
        except EntryNotFound:
            return False

    def get(self, path, max_bytes=MAX_ITEM):
        p = self._safe(path)
        if p.stat().st_size > max_bytes:
            raise ZimError(f"{p.name}: too large")
        mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix.lower() in (".md", ".markdown"):
            mt = "text/markdown"
        with open(p, "rb") as f:   # read-only
            data = f.read()
        return Content(str(p.relative_to(self.root)), p.stem, mt, data)

    def suggest(self, text, limit=25):
        return SearchResult("title-only", [], 0, "single file: no search index")

    search = suggest

    def close(self):
        pass
