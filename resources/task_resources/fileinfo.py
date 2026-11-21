# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Identify a file by content (not only by extension) and read its metadata. Read-only.

Supported kinds: zim, pdf, epub, odt, docx, txt, md, html. Anything else raises UnsupportedFile.
A file whose extension promises a format its bytes do not match, or that its parser rejects, raises
CorruptFile. ZIM metadata comes from python3-libzim when it is importable; otherwise only the
documented ZIM header (magic, version, UUID, entry count) is read and that is reported.
"""

import hashlib
import html.parser
import os
import re
import struct
import uuid as uuidlib
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

try:  # python3-libzim (Debian trixie 3.6.0)
    from libzim.reader import Archive as _Archive
except ImportError:  # pragma: no cover - exercised by the fallback test via monkeypatch
    _Archive = None

ZIM_MAGIC = b"ZIM\x04"   # 72173914 little-endian, openZIM file format header
KINDS = ("zim", "pdf", "epub", "odt", "docx", "txt", "md", "html")
EXTENSIONS = {".zim": "zim", ".pdf": "pdf", ".epub": "epub", ".odt": "odt", ".docx": "docx",
              ".txt": "txt", ".text": "txt", ".md": "md", ".markdown": "md", ".html": "html", ".htm": "html"}
TEXT_PROBE = 64 * 1024
FP_CHUNK = 1 << 20


class UnsupportedFile(ValueError):
    pass


class CorruptFile(ValueError):
    pass


@dataclass
class Info:
    path: str
    kind: str
    size: int
    mtime: float
    title: str = ""
    description: str = ""
    language: str = ""
    creator: str = ""
    publisher: str = ""
    date: str = ""
    name: str = ""
    zim_uuid: str = ""
    article_count: int = None
    media_count: int = None
    has_fulltext: bool = None
    metadata_source: str = ""      # libzim | zim-header | epub-opf | html-title | filename
    warnings: list = field(default_factory=list)


def fingerprint(path, size=None) -> str:
    """Quick content fingerprint: size + sha256 of the first and last MiB. Used for duplicate hints;
    a full sha256 is only computed by the explicit verify job."""
    size = os.path.getsize(path) if size is None else size
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(FP_CHUNK))
        if size > 2 * FP_CHUNK:
            f.seek(size - FP_CHUNK)
            h.update(f.read(FP_CHUNK))
    return h.hexdigest()


def full_sha256(path, cancelled=lambda: False, block=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            if cancelled():
                raise InterruptedError("cancelled")
            h.update(chunk)
    return h.hexdigest()


def _head(path, n):
    with open(path, "rb") as f:
        return f.read(n)


def detect(path, suffix=None) -> str:
    """suffix: the extension the file will have (used for .part files during download verification)."""
    path = Path(path)
    if not path.is_file():
        raise UnsupportedFile(f"not a regular file: {path}")
    ext = EXTENSIONS.get((suffix or path.suffix).lower())
    head = _head(path, TEXT_PROBE)
    if head.startswith(ZIM_MAGIC):
        return "zim"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        kind = _zip_kind(path)
        if kind:
            return kind
        if ext in ("epub", "odt", "docx"):
            raise CorruptFile(f"{path.name}: ZIP container without a valid {ext} structure")
        raise UnsupportedFile(f"{path.name}: ZIP archive is not a supported document type")
    if ext in ("zim", "pdf", "epub", "odt", "docx"):
        raise CorruptFile(f"{path.name}: content does not match the {ext.upper()} format")
    if ext in ("txt", "md", "html"):
        if b"\x00" in head:
            raise CorruptFile(f"{path.name}: binary data in a text file")
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < len(head) - 4:  # a multibyte char cut at the probe boundary is fine
                try:
                    head.decode("latin-1")
                except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes everything
                    raise CorruptFile(f"{path.name}: not text") from None
        return ext
    raise UnsupportedFile(f"{path.name}: unsupported file type ({path.suffix or 'no extension'})")


def _zip_kind(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "mimetype" in names:
                mt = z.read("mimetype")[:100].strip()
                if mt == b"application/epub+zip":
                    return "epub"
                if mt == b"application/vnd.oasis.opendocument.text":
                    return "odt"
            if "[Content_Types].xml" in names and "word/document.xml" in names:
                return "docx"
    except (zipfile.BadZipFile, OSError, KeyError):
        if Path(path).suffix.lower() in (".epub", ".odt", ".docx"):
            raise CorruptFile(f"{Path(path).name}: damaged ZIP container") from None
        raise UnsupportedFile(f"{Path(path).name}: damaged ZIP archive") from None
    return None


def read(path) -> Info:
    path = Path(path)
    kind = detect(path)
    st = path.stat()
    info = Info(path=str(path), kind=kind, size=st.st_size, mtime=st.st_mtime)
    {"zim": _zim, "epub": _epub, "html": _html}.get(kind, _plain)(path, info)
    if not info.title:
        info.title = _title_from_name(path)
        info.metadata_source = info.metadata_source or "filename"
    return info


def _title_from_name(path: Path) -> str:
    return re.sub(r"[_]+", " ", path.stem).strip() or path.name


def _plain(path, info):
    info.metadata_source = "filename"


def _meta(a, key):
    try:
        return bytes(a.get_metadata(key)).decode("utf-8", "replace").strip()
    except (RuntimeError, KeyError):
        return ""


def _zim(path, info):
    if _Archive is None:
        _zim_header(path, info)
        info.warnings.append("python3-libzim not installed: only the ZIM header was read")
        return
    try:
        a = _Archive(str(path))
        info.zim_uuid = str(a.uuid)
        info.article_count = a.article_count
        info.media_count = a.media_count
        info.has_fulltext = bool(a.has_fulltext_index)
        keys = set(a.metadata_keys)
    except RuntimeError as exc:
        raise CorruptFile(f"{path.name}: libzim cannot open it ({exc})") from None
    for attr, key in (("title", "Title"), ("description", "Description"), ("language", "Language"),
                      ("creator", "Creator"), ("publisher", "Publisher"), ("date", "Date"), ("name", "Name")):
        if key in keys:
            setattr(info, attr, _meta(a, key))
    info.metadata_source = "libzim"


def _zim_header(path, info):
    head = _head(path, 80)
    if len(head) < 80 or not head.startswith(ZIM_MAGIC):
        raise CorruptFile(f"{path.name}: truncated ZIM header")
    info.zim_uuid = str(uuidlib.UUID(bytes=head[8:24]))
    info.article_count = None                    # the header only has the entry count, not articles
    (entries,) = struct.unpack_from("<I", head, 24)
    info.warnings.append(f"ZIM header: {entries} entries (all namespaces)")
    info.metadata_source = "zim-header"


def _epub(path, info):
    try:
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            rootfile = next((e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile")), None)
            if not rootfile:
                raise CorruptFile(f"{path.name}: EPUB without a package document")
            data = z.read(rootfile)
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise CorruptFile(f"{path.name}: damaged EPUB ({exc})") from None
    if b"<!DOCTYPE" in data[:2048] or b"<!ENTITY" in data:
        raise CorruptFile(f"{path.name}: EPUB package with DTD/entities refused")
    opf = ET.fromstring(data)
    dc = "{http://purl.org/dc/elements/1.1/}"
    for attr, key in (("title", "title"), ("creator", "creator"), ("language", "language"),
                      ("publisher", "publisher"), ("description", "description"), ("date", "date")):
        el = opf.find(f".//{dc}{key}")
        if el is not None and (el.text or "").strip():
            setattr(info, attr, el.text.strip())
    info.metadata_source = "epub-opf"


class _TitleParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title, self.title = False, ""

    def handle_starttag(self, tag, attrs):
        self.in_title = tag == "title"

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def _html(path, info):
    p = _TitleParser()
    p.feed(_head(path, TEXT_PROBE).decode("utf-8", "replace"))
    t = " ".join(p.title.split())
    if t:
        info.title, info.metadata_source = t[:300], "html-title"
