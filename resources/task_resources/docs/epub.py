# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""EPUB as a read-only source with the same interface as ZimArchive (zipfile; no extra library)."""

import mimetypes
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from task_resources.zim.archive import Content, EntryNotFound, SearchResult, ZimError

OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_ITEM = 32 * 1024 * 1024


def _xml(data):
    if b"<!DOCTYPE" in data[:2048] and b"<!ENTITY" in data or b"<!ENTITY" in data[:65536]:
        raise ZimError("EPUB XML with entity declarations refused")
    return ET.fromstring(data)


class EpubSource:
    kind = "epub"
    scheme = "epub"
    has_fulltext = False

    def __init__(self, path):
        self.path = str(path)
        try:
            self.z = zipfile.ZipFile(self.path)
            names = set(self.z.namelist())
            if any(n.startswith("META-INF/encryption.xml") for n in names):
                enc = self.z.read("META-INF/encryption.xml")
                if b"EncryptedData" in enc and b"obfuscation" not in enc.lower():
                    raise ZimError("this EPUB is DRM-protected (encrypted); it cannot be shown")
            root = _xml(self.z.read("META-INF/container.xml"))
            rf = next(e.get("full-path") for e in root.iter() if e.tag.endswith("rootfile"))
            self.opf_dir = posixpath.dirname(rf)
            opf = _xml(self.z.read(rf))
        except (KeyError, StopIteration, zipfile.BadZipFile, ET.ParseError, OSError) as exc:
            raise ZimError(f"damaged EPUB: {exc}") from None
        self.names = names
        self.manifest = {}
        for item in opf.iter(OPF + "item"):
            href = posixpath.normpath(posixpath.join(self.opf_dir, item.get("href", "")))
            self.manifest[item.get("id")] = (href, item.get("media-type", ""))
        self.spine = [self.manifest[i.get("idref")][0] for i in opf.iter(OPF + "itemref")
                      if i.get("idref") in self.manifest]
        self.meta = {}
        for key, tag in (("Title", "title"), ("Creator", "creator"), ("Language", "language"),
                         ("Publisher", "publisher"), ("Description", "description"), ("Date", "date")):
            el = opf.find(f".//{DC}{tag}")
            if el is not None and (el.text or "").strip():
                self.meta[key] = el.text.strip()
        self.types = {href: mt for href, mt in self.manifest.values()}

    def metadata(self):
        return dict(self.meta)

    def main_path(self):
        return self.spine[0] if self.spine else None

    def resolve(self, path):
        path = path.lstrip("/")
        if path not in self.names:
            raise EntryNotFound(path)
        return path, []

    def exists(self, path):
        return path.lstrip("/") in self.names

    def get(self, path, max_bytes=MAX_ITEM):
        path, _ = self.resolve(path)
        info = self.z.getinfo(path)
        if info.file_size > max_bytes:
            raise ZimError(f"{path}: too large")
        mt = self.types.get(path) or mimetypes.guess_type(path)[0] or "application/octet-stream"
        title = self.meta.get("Title", "") if path == self.main_path() else posixpath.basename(path)
        return Content(path, title, mt, self.z.read(path))

    def chapters(self):
        return list(self.spine)

    def suggest(self, text, limit=25):
        t = str(text).lower()
        hits = [(p, posixpath.basename(p)) for p in self.spine if t and t in p.lower()][:limit]
        return SearchResult("title-only", hits, len(hits), "EPUB: chapter file names only")

    search = suggest

    def close(self):
        self.z.close()
