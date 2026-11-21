# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Find resources in place, read-only: configured folders, Kiwix library.xml files, kiwix-desktop data.

Nothing is created, moved, renamed, chmod/chowned or written in scanned locations. Files are only
opened for reading. Unchanged files (same path, size, mtime) are not re-read."""

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from task_resources import fileinfo
from task_resources.index import DuplicateResource

SCAN_EXT = set(fileinfo.EXTENSIONS)
SPLIT_SUFFIXES = ("zimaa",)       # first part of a split ZIM (".zimaa", ".zimab", ...)
MAX_XML = 16 * 1024 * 1024


@dataclass
class Report:
    seen: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0
    errors: list = field(default_factory=list)      # (path, reason)
    notes: list = field(default_factory=list)


def library_xml_paths(xml_path):
    """ZIM paths listed in a Kiwix library.xml (relative paths resolved against its folder)."""
    p = Path(xml_path)
    try:
        if p.stat().st_size > MAX_XML:
            return []
        data = p.read_bytes()
    except OSError:
        return []
    if b"<!DOCTYPE" in data[:2048] or b"<!ENTITY" in data[:65536]:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    out = []
    for book in root.iter("book"):
        rel = book.get("path", "")
        if rel:
            out.append(str(Path(rel) if rel.startswith("/") else (p.parent / rel)))
    return out


def kiwix_desktop_libraries(base: Path):
    base = Path(base)
    if not base.is_dir():
        return []
    return sorted(str(x) for x in base.glob("*.xml") if x.is_file())


def walk(folder, cancelled=lambda: False):
    folder = Path(folder)
    if not folder.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if cancelled():
                return
            if name.startswith("."):
                continue
            yield Path(dirpath) / name


def candidates(settings, extra=(), cancelled=lambda: False):
    seen = set()
    for f in extra:
        yield Path(f), "import"
    for d in settings.scan_dirs:
        for f in walk(d, cancelled):
            if f.suffix.lower() in SCAN_EXT or f.suffix.lower().lstrip(".") in SPLIT_SUFFIXES:
                if f not in seen:
                    seen.add(f)
                    yield f, "scan"
    xmls = list(settings.library_xml) + kiwix_desktop_libraries(settings.expanded_kiwix_desktop())
    for x in xmls:
        for f in library_xml_paths(x):
            f = Path(f)
            if f not in seen:
                seen.add(f)
                yield f, "library-xml"


def register(index, path, source, report, allow_duplicate=False, keep_duplicate=True, snapshot=None,
             managed=False):
    """Read one file's metadata and register it. Returns resource id or None."""
    report.seen += 1
    try:
        real = os.path.realpath(path)
        st = os.stat(real)
    except OSError as exc:
        report.errors.append((str(path), f"not readable: {exc.strerror or exc}"))
        return None
    if Path(path).suffix.lower() == ".zimaa":
        report.notes.append(f"{path}: split ZIM (.zimaa…) — opening split ZIMs is not supported in this version")
        report.errors.append((str(path), "split ZIM not supported in this version"))
        return None
    if snapshot is not None and real in snapshot:
        rid, size, mtime = snapshot[real]
        if size == st.st_size and mtime == st.st_mtime:
            index.touch_checked(rid)
            report.unchanged += 1
            return rid
    try:
        info = fileinfo.read(real)
        fp = fileinfo.fingerprint(real, info.size)
    except (fileinfo.UnsupportedFile, fileinfo.CorruptFile) as exc:
        report.errors.append((str(path), str(exc)))
        return None
    except OSError as exc:
        report.errors.append((str(path), f"not readable: {exc.strerror or exc}"))
        return None
    try:
        rid, status = index.upsert(info, fp, source, managed=managed, allow_duplicate=allow_duplicate,
                                   keep_duplicate=keep_duplicate)
    except DuplicateResource as exc:
        report.duplicates += 1
        report.errors.append((str(path), f"duplicate: {exc.reason}"))
        return None
    field_name = {"added": "added", "updated": "updated", "unchanged": "unchanged",
                  "duplicate": "duplicates"}[status]
    setattr(report, field_name, getattr(report, field_name) + 1)
    return rid


def scan(index, settings, job=None):
    """Full discovery pass + missing-file check. Cancellable through job."""
    cancelled = (lambda: job.cancelled) if job else (lambda: False)
    report = Report()
    snap = index.snapshot_paths()
    for i, (path, source) in enumerate(candidates(settings, cancelled=cancelled)):
        if job:
            job.progress(done=i, message=str(path))
        register(index, path, source, report, snapshot=snap)
    if job:
        job.check()
    health = index.check_files(cancelled)
    report.notes.append(f"missing files: {health['missing']}, changed: {health['changed']}")
    return report
