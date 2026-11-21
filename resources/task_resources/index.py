# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""SQLite catalogue of *references* to files that stay where they are.

Removing a resource removes only its row; files are never deleted, moved or modified by the index.
User edits live in ``meta_override`` so a rescan never overwrites them. Categories are many-to-many.
Title/metadata search uses FTS5 over the effective (edited) values; full-text search inside ZIM files is
a different feature (see search.py).
"""

import os
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 1
EDITABLE = ("title", "description", "language", "creator", "publisher", "date", "notes")
EXTRACTED = ("title", "description", "language", "creator", "publisher", "date")
UNCATEGORISED = "__uncategorised__"

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS resource(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    size INTEGER, mtime REAL, fingerprint TEXT, sha256 TEXT,
    title TEXT, description TEXT, language TEXT, creator TEXT, publisher TEXT, date TEXT, name TEXT,
    zim_uuid TEXT, article_count INTEGER, media_count INTEGER, has_fulltext INTEGER,
    metadata_source TEXT, source TEXT NOT NULL, managed INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0, changed INTEGER NOT NULL DEFAULT 0,
    duplicate_of INTEGER REFERENCES resource(id) ON DELETE SET NULL,
    added_at REAL, checked_at REAL);
CREATE INDEX IF NOT EXISTS resource_uuid ON resource(zim_uuid);
CREATE INDEX IF NOT EXISTS resource_fp ON resource(fingerprint);
CREATE TABLE IF NOT EXISTS category(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS resource_category(
    resource_id INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
    PRIMARY KEY(resource_id, category_id));
CREATE TABLE IF NOT EXISTS meta_override(
    resource_id INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    field TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(resource_id, field));
CREATE TABLE IF NOT EXISTS bookmark(
    id INTEGER PRIMARY KEY, resource_id INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    path TEXT NOT NULL, title TEXT, created REAL, UNIQUE(resource_id, path));
CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY, resource_id INTEGER NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
    path TEXT NOT NULL, title TEXT, visited REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS titles_fts USING fts5(
    title, description, creator, publisher, language, categories, filename, notes, tokenize='unicode61');
"""


class DuplicateResource(Exception):
    def __init__(self, existing_id, reason):
        super().__init__(reason)
        self.existing_id, self.reason = existing_id, reason


class ReadOnlyIndex(Exception):
    """A write was attempted on an index opened with read_only=True."""


class Index:
    def __init__(self, path: Path, read_only: bool = False):
        """read_only=True (Phase 4F.3, used by embedders such as the launcher's Medical view): the file must
        already exist; it is opened through task_resources.rosnap (0.2.3: snapshot copy when nobody has the
        index open, live ``mode=ro`` when a writer is active - nothing is created next to the index) with
        ``PRAGMA query_only``. No directory/file is
        created, no chmod, no DDL, no journal-mode change, no meta insert. Writes raise ReadOnlyIndex
        (history is silently skipped)."""
        self.path = Path(path)
        self.read_only = bool(read_only)
        self.lock = threading.RLock()
        self._ro = None
        self.closed = False
        if self.read_only:
            from task_resources.rosnap import ReadOnlyHandle
            self._ro = ReadOnlyHandle(self.path)       # FileNotFoundError if absent; creates nothing beside it
            self.ro_mode = self._ro.mode               # 'snapshot' (as of open; reopen to refresh) | 'live'
            self.db = self._ro.conn
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            try:
                row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            except sqlite3.DatabaseError as exc:
                self.close()
                raise RuntimeError(f"index unreadable: {exc}") from None
            if row is not None and int(row[0]) > SCHEMA_VERSION:
                self.close()
                raise RuntimeError(f"index schema {row[0]} is newer than this program ({SCHEMA_VERSION})")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        os.close(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600))
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self.lock, self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript(DDL)
            row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row is None:
                self.db.execute("INSERT INTO meta VALUES('schema', ?)", (str(SCHEMA_VERSION),))
            elif int(row[0]) > SCHEMA_VERSION:
                raise RuntimeError(f"index schema {row[0]} is newer than this program ({SCHEMA_VERSION})")
        for side in ("-wal", "-shm"):
            p = Path(str(self.path) + side)
            if p.exists():
                os.chmod(p, 0o600)

    def ro_stale(self):
        """Read-only snapshot older than the index on disk (True) -> re-open to see changes."""
        return self._ro is not None and self._ro.stale()

    def _writable(self):
        if self.read_only:
            raise ReadOnlyIndex("this index was opened read-only")

    def close(self):
        """Idempotent. Read-only: closes the connection and removes OUR snapshot copy (never index side files)."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self._ro is not None:
                self._ro.close()
            else:
                self.db.close()

    # ------------------------------------------------------------------ resources
    def find_duplicate(self, info, fingerprint, exclude_path=None):
        with self.lock:
            if info.zim_uuid:
                r = self.db.execute("SELECT id, path FROM resource WHERE zim_uuid=? AND path!=? "
                                    "AND duplicate_of IS NULL", (info.zim_uuid, exclude_path or "")).fetchone()
                if r:
                    return r["id"], f"same ZIM (UUID {info.zim_uuid}) already registered at {r['path']}"
            if fingerprint:
                r = self.db.execute("SELECT id, path FROM resource WHERE fingerprint=? AND size=? AND path!=? "
                                    "AND duplicate_of IS NULL", (fingerprint, info.size, exclude_path or "")).fetchone()
                if r:
                    return r["id"], f"identical file already registered at {r['path']}"
        return None

    def upsert(self, info, fingerprint, source, managed=False, allow_duplicate=False, keep_duplicate=False):
        """Register or refresh a reference. Returns (id, status): added | updated | unchanged | duplicate.

        A different path with the same ZIM UUID or content fingerprint raises DuplicateResource, unless
        allow_duplicate (independent entry) or keep_duplicate (stored, linked via duplicate_of, hidden)."""
        self._writable()
        path = os.path.realpath(info.path)
        now = time.time()
        vals = dict(kind=info.kind, size=info.size, mtime=info.mtime, fingerprint=fingerprint,
                    title=info.title, description=info.description, language=info.language,
                    creator=info.creator, publisher=info.publisher, date=info.date, name=info.name,
                    zim_uuid=info.zim_uuid or None, article_count=info.article_count,
                    media_count=info.media_count,
                    has_fulltext=None if info.has_fulltext is None else int(info.has_fulltext),
                    metadata_source=info.metadata_source)
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM resource WHERE path=?", (path,)).fetchone()
            if row is not None:
                if all(row[k] == v for k, v in vals.items()) and not row["missing"] and not row["changed"]:
                    self.db.execute("UPDATE resource SET checked_at=? WHERE id=?", (now, row["id"]))
                    return row["id"], "unchanged"
                sets = ", ".join(f"{k}=?" for k in vals)
                self.db.execute(f"UPDATE resource SET {sets}, missing=0, changed=0, sha256=NULL, checked_at=? "
                                "WHERE id=?", (*vals.values(), now, row["id"]))
                self._refresh_fts(row["id"])
                return row["id"], "updated"
            dup = self.find_duplicate(info, fingerprint, exclude_path=path)
            if dup and not (allow_duplicate or keep_duplicate):
                raise DuplicateResource(*dup)
            cols = ["path", "source", "managed", "added_at", "checked_at", "duplicate_of", *vals]
            args = [path, source, int(managed), now, now, dup[0] if (dup and keep_duplicate) else None,
                    *vals.values()]
            cur = self.db.execute(f"INSERT INTO resource({', '.join(cols)}) "
                                  f"VALUES({', '.join('?' * len(cols))})", args)
            rid = cur.lastrowid
            self._refresh_fts(rid)
            return rid, "duplicate" if dup else "added"

    def remove(self, rid):
        """Forget a reference. The file itself is not touched."""
        self._writable()
        with self.lock, self.db:
            self.db.execute("DELETE FROM titles_fts WHERE rowid=?", (rid,))
            self.db.execute("DELETE FROM resource WHERE id=?", (rid,))

    def id_for_path(self, path):
        with self.lock:
            r = self.db.execute("SELECT id FROM resource WHERE path=?", (str(path),)).fetchone()
            return r["id"] if r else None

    def snapshot_paths(self):
        with self.lock:
            return {r["path"]: (r["id"], r["size"], r["mtime"])
                    for r in self.db.execute("SELECT id, path, size, mtime FROM resource")}

    def touch_checked(self, rid):
        self._writable()
        with self.lock, self.db:
            self.db.execute("UPDATE resource SET checked_at=?, missing=0 WHERE id=?", (time.time(), rid))

    def get(self, rid):
        with self.lock:
            r = self.db.execute("SELECT * FROM resource WHERE id=?", (rid,)).fetchone()
            if r is None:
                return None
            d = dict(r)
            d["extracted"] = {k: r[k] or "" for k in EXTRACTED}
            d["overrides"] = {o["field"]: o["value"] for o in
                              self.db.execute("SELECT field, value FROM meta_override WHERE resource_id=?", (rid,))}
            for k in EDITABLE:
                d[k] = d["overrides"].get(k, d.get(k) or "")
            d["categories"] = [c["name"] for c in self.db.execute(
                "SELECT c.name FROM category c JOIN resource_category rc ON rc.category_id=c.id "
                "WHERE rc.resource_id=? ORDER BY c.name COLLATE NOCASE", (rid,))]
            d["copies"] = [x["path"] for x in self.db.execute(
                "SELECT path FROM resource WHERE duplicate_of=?", (rid,))]
            return d

    def list(self, category=None, query=None, include_missing=True, include_duplicates=False, kind=None):
        sql = "SELECT r.id FROM resource r"
        where, args = [], []
        if query:
            match = fts_query(query)
            if not match:
                return []
            sql += " JOIN titles_fts f ON f.rowid=r.id"
            where.append("titles_fts MATCH ?")
            args.append(match)
        if category == UNCATEGORISED:
            where.append("NOT EXISTS (SELECT 1 FROM resource_category rc WHERE rc.resource_id=r.id)")
        elif category:
            where.append("EXISTS (SELECT 1 FROM resource_category rc JOIN category c ON c.id=rc.category_id "
                         "WHERE rc.resource_id=r.id AND c.name=?)")
            args.append(category)
        if kind:
            where.append("r.kind=?")
            args.append(kind)
        if not include_missing:
            where.append("r.missing=0")
        if not include_duplicates:
            where.append("r.duplicate_of IS NULL")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY bm25(titles_fts)" if query else (
            " ORDER BY COALESCE((SELECT value FROM meta_override WHERE resource_id=r.id AND field='title'),"
            " r.title) COLLATE NOCASE")
        with self.lock:
            return [self.get(r["id"]) for r in self.db.execute(sql, args).fetchall()]

    def counts(self):
        with self.lock:
            q = lambda s: self.db.execute(s).fetchone()[0]  # noqa: E731
            return {"total": q("SELECT COUNT(*) FROM resource WHERE duplicate_of IS NULL"),
                    "missing": q("SELECT COUNT(*) FROM resource WHERE missing=1"),
                    "duplicates": q("SELECT COUNT(*) FROM resource WHERE duplicate_of IS NOT NULL")}

    # ------------------------------------------------------------------ metadata edits
    def set_override(self, rid, field, value):
        self._writable()
        if field not in EDITABLE:
            raise ValueError(f"{field!r} is not editable")
        with self.lock, self.db:
            self.db.execute("INSERT INTO meta_override VALUES(?,?,?) ON CONFLICT(resource_id, field) "
                            "DO UPDATE SET value=excluded.value", (rid, field, str(value)))
            self._refresh_fts(rid)

    def clear_override(self, rid, field):
        self._writable()
        with self.lock, self.db:
            self.db.execute("DELETE FROM meta_override WHERE resource_id=? AND field=?", (rid, field))
            self._refresh_fts(rid)

    # ------------------------------------------------------------------ categories
    def categories(self):
        with self.lock:
            return [(r["name"], r["n"]) for r in self.db.execute(
                "SELECT c.name, COUNT(rc.resource_id) n FROM category c LEFT JOIN resource_category rc "
                "ON rc.category_id=c.id GROUP BY c.id ORDER BY c.name COLLATE NOCASE")]

    @staticmethod
    def _clean(name):
        name = " ".join(str(name).split())
        if not name or name == UNCATEGORISED or len(name) > 80:
            raise ValueError("category names must be 1-80 characters")
        return name

    def create_category(self, name):
        self._writable()
        name = self._clean(name)
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO category(name) VALUES(?)", (name,))
            return self.db.execute("SELECT id FROM category WHERE name=?", (name,)).fetchone()[0]

    def rename_category(self, old, new):
        self._writable()
        new = self._clean(new)
        with self.lock, self.db:
            self.db.execute("UPDATE category SET name=? WHERE name=?", (new, old))
            self._refresh_all_fts()

    def delete_category(self, name):
        """Delete the category; resources stay (only the assignments go)."""
        self._writable()
        with self.lock, self.db:
            self.db.execute("DELETE FROM category WHERE name=?", (name,))
            self._refresh_all_fts()

    def set_categories(self, rid, names):
        self._writable()
        with self.lock, self.db:
            ids = [self.create_category(n) for n in names]
            self.db.execute("DELETE FROM resource_category WHERE resource_id=?", (rid,))
            self.db.executemany("INSERT OR IGNORE INTO resource_category VALUES(?,?)", [(rid, c) for c in ids])
            self._refresh_fts(rid)

    def add_to_category(self, rid, name):
        self._writable()
        with self.lock, self.db:
            cid = self.create_category(name)
            self.db.execute("INSERT OR IGNORE INTO resource_category VALUES(?,?)", (rid, cid))
            self._refresh_fts(rid)

    # ------------------------------------------------------------------ health
    def check_files(self, cancelled=lambda: False):
        """Mark missing / changed files. Never deletes rows. Returns counts."""
        self._writable()
        out = {"missing": 0, "changed": 0, "ok": 0}
        with self.lock:
            rows = self.db.execute("SELECT id, path, size, mtime FROM resource").fetchall()
        for r in rows:
            if cancelled():
                break
            try:
                st = os.stat(r["path"])
                missing = 0
                changed = int(st.st_size != r["size"] or abs(st.st_mtime - (r["mtime"] or 0)) > 1e-6)
            except OSError:
                missing, changed = 1, 0
            with self.lock, self.db:
                self.db.execute("UPDATE resource SET missing=?, changed=?, checked_at=? WHERE id=?",
                                (missing, changed, time.time(), r["id"]))
            out["missing" if missing else "changed" if changed else "ok"] += 1
        return out

    def set_sha256(self, rid, digest):
        self._writable()
        with self.lock, self.db:
            self.db.execute("UPDATE resource SET sha256=? WHERE id=?", (digest, rid))

    # ------------------------------------------------------------------ bookmarks / history
    HISTORY_MAX = 500

    def add_bookmark(self, rid, path, title=""):
        self._writable()
        with self.lock, self.db:
            self.db.execute("INSERT INTO bookmark(resource_id, path, title, created) VALUES(?,?,?,?) "
                            "ON CONFLICT(resource_id, path) DO UPDATE SET title=excluded.title",
                            (rid, path, title, time.time()))

    def remove_bookmark(self, rid, path):
        self._writable()
        with self.lock, self.db:
            self.db.execute("DELETE FROM bookmark WHERE resource_id=? AND path=?", (rid, path))

    def bookmarks(self):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT b.resource_id, b.path, b.title, b.created, r.missing FROM bookmark b "
                "JOIN resource r ON r.id=b.resource_id ORDER BY b.created DESC")]

    def add_history(self, rid, path, title=""):
        if self.read_only:
            return          # reading never writes history into a read-only index
        with self.lock, self.db:
            self.db.execute("INSERT INTO history(resource_id, path, title, visited) VALUES(?,?,?,?)",
                            (rid, path, title, time.time()))
            self.db.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                            (self.HISTORY_MAX,))

    def history(self, limit=100):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT resource_id, path, title, visited FROM history ORDER BY id DESC LIMIT ?", (limit,))]

    def clear_history(self):
        self._writable()
        with self.lock, self.db:
            self.db.execute("DELETE FROM history")

    # ------------------------------------------------------------------ FTS
    def _refresh_fts(self, rid):
        d = self.get(rid)
        self.db.execute("DELETE FROM titles_fts WHERE rowid=?", (rid,))
        if d:
            self.db.execute("INSERT INTO titles_fts(rowid, title, description, creator, publisher, language, "
                            "categories, filename, notes) VALUES(?,?,?,?,?,?,?,?,?)",
                            (rid, d["title"], d["description"], d["creator"], d["publisher"], d["language"],
                             " ".join(d["categories"]), Path(d["path"]).name.replace("_", " "), d["notes"]))

    def _refresh_all_fts(self):
        for (rid,) in self.db.execute("SELECT id FROM resource").fetchall():
            self._refresh_fts(rid)


def fts_query(text):
    """User text -> safe FTS5 query: each word quoted with prefix match, AND-ed. No FTS syntax passes."""
    words = "".join(c if c.isalnum() else " " for c in str(text)).split()[:12]
    return " ".join(f'"{w}"*' for w in words)
