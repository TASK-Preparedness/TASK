# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Library service: index + open sources. The single entry point the UI and both viewers use."""

from pathlib import Path

from task_resources import paths
from task_resources.docs.epub import EpubSource
from task_resources.docs.local import LocalSource
from task_resources.index import Index
from task_resources.zim.archive import SourcePool, ZimArchive, ZimError

READABLE = {"zim": ZimArchive, "epub": EpubSource, "html": LocalSource, "txt": LocalSource, "md": LocalSource}


class NotReadable(ZimError):
    pass


class Library:
    def __init__(self, settings, index_path: Path = None, read_only: bool = False):
        self.settings = settings
        self.read_only = bool(read_only)
        self.index = Index(index_path or paths.data_dir() / "index.sqlite", read_only=self.read_only)
        self.pool = SourcePool(self._open, capacity=max(1, int(settings.open_archive_cache)))

    def _open(self, rid):
        r = self.index.get(rid)
        if r is None:
            raise NotReadable(f"unknown resource {rid}")
        cls = READABLE.get(r["kind"])
        if cls is None:
            raise NotReadable(f"{r['kind'].upper()} files are not shown inside T.A.S.K. Resources")
        if r["missing"] or not Path(r["path"]).is_file():
            raise NotReadable(f"file not found: {r['path']}")
        if cls is ZimArchive:
            return ZimArchive(r["path"], max_item=int(self.settings.max_item_mb) * 1024 * 1024)
        return cls(r["path"])

    def source(self, rid):
        return self.pool.get(rid)

    def scheme_for(self, rid):
        return self.source(rid).scheme

    def close(self):
        self.pool.clear()
        self.index.close()
