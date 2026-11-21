# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Persistent, resumable download queue (Phase 4E). One background worker thread; the UI only polls.

States: queued → running → verifying → done; paused; waiting (network down, retried with backoff);
failed; cancelled. After a crash/power cut, running/verifying come back as paused; the .part stays.

Data path: <dest>/.<name>.part  →  size + sha256 (when the source publishes one) + content-type sniff +
libzim Archive.check() for ZIM  →  os.link() to the final name (never overwrites)  →  registered in the
index. A cancelled, failed or incomplete transfer is never registered. Files are never executed.
"""

import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

from task_resources import catalog as catalog_mod
from task_resources import discovery, fileinfo, managed, paths
from task_resources.net import safehttp

QUEUED, RUNNING, PAUSED, WAITING, VERIFYING, DONE, FAILED, CANCELLED = (
    "queued", "running", "paused", "waiting", "verifying", "done", "failed", "cancelled")
ACTIVE = (RUNNING, VERIFYING)
ALLOWED_EXT = {".zim": "zim", ".pdf": "pdf", ".epub": "epub", ".html": "html", ".htm": "html",
               ".txt": "txt", ".md": "md"}
MIME_EXT = {"application/x-zim": ".zim", "application/pdf": ".pdf", "application/epub+zip": ".epub",
            "text/html": ".html", "text/plain": ".txt", "text/markdown": ".md"}
CHUNK = 256 * 1024
SPACE_RECHECK = 64 * 1024 * 1024
BACKOFF = (30, 60, 120, 300, 600, 900)

DDL = """
CREATE TABLE IF NOT EXISTS transfer(
  id INTEGER PRIMARY KEY, url TEXT NOT NULL, file_url TEXT, title TEXT, categories TEXT NOT NULL DEFAULT '[]',
  dest_dir TEXT, filename TEXT, final_path TEXT, state TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
  total INTEGER, etag TEXT, last_modified TEXT, expected_sha256 TEXT, expected_size INTEGER,
  catalog_uuid TEXT, error TEXT, note TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
  rid INTEGER, speed REAL NOT NULL DEFAULT 0, created REAL, updated REAL);
"""


class DownloadError(Exception):
    pass


class Duplicate(DownloadError):
    pass


class _Stop(Exception):
    def __init__(self, why):
        super().__init__(why)
        self.why = why


def sanitize_filename(name, fallback="download"):
    name = urllib.parse.unquote(str(name)).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w .()+-]", "_", name).strip(" .")
    if not name or name in (".", ".."):
        name = fallback
    stem, ext = os.path.splitext(name)
    return (stem[:120] or fallback) + ext[:10].lower()


def _cd_filename(header):
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.I) or re.search(r'filename="?([^";]+)"?', header, re.I)
    return m.group(1).strip() if m else ""


def choose_filename(url, content_disposition="", content_type=""):
    """-> sanitized name with an allowed extension. Raises DownloadError for other types."""
    name = _cd_filename(content_disposition) or urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    name = sanitize_filename(name)
    ext = os.path.splitext(name)[1]
    if ext not in ALLOWED_EXT:
        mext = MIME_EXT.get(content_type.split(";")[0].strip().lower())
        if not mext:
            raise DownloadError(f"unsupported file type ({ext or content_type or 'unknown'}); "
                                "allowed: ZIM, PDF, EPUB, HTML, TXT, Markdown")
        name = (name if ext == "" else os.path.splitext(name)[0]) + mext
    return name


def eta(done, total, speed):
    if not total or speed <= 0:
        return None
    return max(0.0, (total - done) / speed)


class DownloadManager:
    def __init__(self, library, client=None, db_path=None, clock=time.time, catalog=None, autostart=True):
        self.library, self.settings, self.index = library, library.settings, library.index
        self.client = client or safehttp.Client()
        self.catalog = catalog
        self.clock = clock
        db_path = Path(db_path or paths.data_dir() / "downloads.sqlite")
        paths.private_dir(db_path.parent)
        os.close(os.open(db_path, os.O_RDWR | os.O_CREAT, 0o600))
        os.chmod(db_path, 0o600)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock, self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(DDL)
        self.flags = {}                 # id -> "pause" | "cancel"
        self.completed = []             # ids that became DONE (UI drains this to refresh)
        self.offline = False
        self._wake = threading.Event()
        self._quit = threading.Event()
        self._thread = None
        self.recover()
        if autostart:
            self.start()

    # ------------------------------------------------------------------ persistence
    def _set(self, tid, **kw):
        kw["updated"] = self.clock()
        with self.lock, self.db:
            self.db.execute(f"UPDATE transfer SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), tid))

    def get(self, tid):
        with self.lock:
            r = self.db.execute("SELECT * FROM transfer WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None

    def list(self, states=None):
        with self.lock:
            rows = self.db.execute("SELECT * FROM transfer ORDER BY id").fetchall()
        return [dict(r) for r in rows if not states or r["state"] in states]

    def recover(self):
        """Power-loss / crash recovery: nothing can be running at start-up."""
        with self.lock, self.db:
            self.db.execute("UPDATE transfer SET state=?, note='interrupted (program closed or power loss); "
                            "resume to continue' WHERE state IN (?, ?)", (PAUSED, RUNNING, VERIFYING))

    # ------------------------------------------------------------------ API
    def add(self, url, categories=(), dest_dir="", title="", expected_sha256="", expected_size=0,
            catalog_uuid=""):
        safehttp.check_url(url, self.client.policy)
        with self.lock:
            dup = self.db.execute("SELECT id, state FROM transfer WHERE url=? AND state NOT IN (?, ?, ?)",
                                  (url, DONE, CANCELLED, FAILED)).fetchone()
            if dup:
                raise Duplicate(f"already in the download list (#{dup['id']}, {dup['state']})")
        if catalog_uuid:
            with self.index.lock:
                r = self.index.db.execute("SELECT path FROM resource WHERE zim_uuid=? AND missing=0",
                                          (catalog_uuid,)).fetchone()
            if r:
                raise Duplicate(f"already in the library: {r[0]}")
        if dest_dir and not os.path.isabs(dest_dir):
            raise DownloadError("destination must be an absolute folder")
        if dest_dir and managed.is_protected(dest_dir, self.settings):
            raise DownloadError(f"{dest_dir} is a protected location (e.g. the existing /library); "
                                "T.A.S.K. never writes there")
        now = self.clock()
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO transfer(url, title, categories, dest_dir, state, expected_sha256, expected_size, "
                "catalog_uuid, created, updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (url, title, json.dumps([c for c in categories if c]), dest_dir, QUEUED,
                 (expected_sha256 or "").lower(), int(expected_size or 0), catalog_uuid, now, now))
        self._wake.set()
        return cur.lastrowid

    def add_catalog_entry(self, entry, categories=(), dest_dir=""):
        return self.add(entry.url, categories or [entry.category or "Kiwix"], dest_dir, entry.title,
                        catalog_uuid=entry.uuid)

    def preview(self, url):
        """HEAD (falls back to a GET whose body is not read): name, size, type. Nothing is written."""
        r = None
        try:
            r = self.client.request(url, "HEAD")
            if r.status >= 400:
                r.close()
                r = self.client.request(url, "GET")
            if r.status >= 400:
                raise DownloadError(f"server answered HTTP {r.status}")
            ctype = r.header("content-type")
            name = choose_filename(r.url, r.header("content-disposition"), ctype)
            size = r.header("content-length")
            return {"filename": name, "size": int(size) if size.isdigit() else None, "type": ctype,
                    "final_url": safehttp.redact(r.url), "resume": r.header("accept-ranges") == "bytes"}
        finally:
            if r:
                r.close()

    def pause(self, tid):
        t = self.get(tid)
        if t and t["state"] in ACTIVE:
            self.flags[tid] = "pause"
        elif t and t["state"] in (QUEUED, WAITING):
            self._set(tid, state=PAUSED)

    def resume(self, tid):
        t = self.get(tid)
        if t and t["state"] in (PAUSED, WAITING):
            self._set(tid, state=QUEUED, next_try=0, error="")
            self._wake.set()

    def retry(self, tid):
        t = self.get(tid)
        if t and t["state"] in (FAILED, CANCELLED):
            self._set(tid, state=QUEUED, next_try=0, attempts=0, error="", note="")
            self._wake.set()

    def cancel(self, tid):
        t = self.get(tid)
        if not t:
            return
        if t["state"] in ACTIVE:
            self.flags[tid] = "cancel"
        elif t["state"] not in (DONE, CANCELLED):
            self._discard_part(t)
            self._set(tid, state=CANCELLED, note="cancelled; partial data deleted")

    def forget(self, tid):
        """Remove a finished/cancelled/failed row from the list (the resource, if any, stays)."""
        t = self.get(tid)
        if t and t["state"] in (DONE, FAILED, CANCELLED):
            with self.lock, self.db:
                self.db.execute("DELETE FROM transfer WHERE id=?", (tid,))

    def set_offline(self, offline):
        self.offline = bool(offline)
        if not offline:
            with self.lock, self.db:
                self.db.execute("UPDATE transfer SET next_try=0 WHERE state=?", (WAITING,))
            self._wake.set()

    # ------------------------------------------------------------------ worker
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._quit.clear()
        self._thread = threading.Thread(target=self._loop, name="task-downloads", daemon=True)
        self._thread.start()

    def stop(self, timeout=10):
        self._quit.set()
        for tid in [t["id"] for t in self.list((RUNNING, VERIFYING))]:
            self.flags[tid] = "pause"
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def close(self):
        self.stop()
        with self.lock:
            self.closed = True
            self.db.close()

    def _next(self):
        now = self.clock()
        with self.lock:
            r = self.db.execute("SELECT id FROM transfer WHERE (state=? OR (state=? AND next_try<=?)) "
                                "ORDER BY id LIMIT 1", (QUEUED, WAITING, now)).fetchone()
        return r[0] if r else None

    def _loop(self):
        while not self._quit.is_set():
            tid = None if self.offline else self._next()
            if tid is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            self.run_one(tid)

    def run_one(self, tid):
        """Process one transfer synchronously (the worker calls this; tests may too)."""
        self.flags.pop(tid, None)
        self._set(tid, state=RUNNING, error="")
        try:
            self._transfer(tid)
        except _Stop as s:
            t = self.get(tid)
            if s.why == "cancel":
                self._discard_part(t)
                self._set(tid, state=CANCELLED, speed=0, note="cancelled; partial data deleted")
            else:
                self._set(tid, state=PAUSED, speed=0, note="paused")
        except safehttp.NetError as exc:
            t = self.get(tid)
            n = t["attempts"] + 1
            delay = BACKOFF[min(n - 1, len(BACKOFF) - 1)]
            self._set(tid, state=WAITING, attempts=n, next_try=self.clock() + delay, speed=0,
                      error=str(exc), note=f"network unavailable; retry {n} in {delay}s (partial data kept)")
        except OSError as exc:
            msg = "disk full" if exc.errno == errno.ENOSPC else f"file error: {exc.strerror or exc}"
            self._set(tid, state=FAILED, speed=0, error=msg, note="partial data kept; free space and retry")
        except (DownloadError, safehttp.Blocked, catalog_mod.CatalogError) as exc:
            self._set(tid, state=FAILED, speed=0, error=str(exc))
        finally:
            self.flags.pop(tid, None)

    # ------------------------------------------------------------------ transfer
    def _check_flag(self, tid):
        f = self.flags.get(tid)
        if f:
            raise _Stop(f)

    def _dest_dir(self, t):
        cats = json.loads(t["categories"] or "[]")
        if t["dest_dir"]:
            d = Path(t["dest_dir"])
            note = ""
            if managed.is_protected(d, self.settings):
                raise DownloadError(f"{d} is a protected location; never written")
        else:
            root, note = managed.resolve_root(self.settings)
            d = root / managed._safe_part(cats[0] if cats else "Uncategorised")
        d.mkdir(parents=True, exist_ok=True)
        if not os.access(d, os.W_OK | os.X_OK):
            raise DownloadError(f"destination {d} is not writable")
        return d, note

    def _discard_part(self, t):
        if t and not t.get("final_path") and t.get("filename"):
            for d in filter(None, [t.get("dest_dir")] + [str(p) for p in self._known_dirs(t)]):
                p = Path(d) / f".{t['filename']}.part"
                if p.is_file():
                    p.unlink()

    def _known_dirs(self, t):
        try:
            root, _ = managed.resolve_root(self.settings)
        except OSError:
            return []
        cats = json.loads(t["categories"] or "[]")
        return [root / managed._safe_part(cats[0] if cats else "Uncategorised")]

    def _space_ok(self, d, remaining):
        reserve = int(self.settings.free_space_reserve_mb) * 1024 * 1024
        free = shutil.disk_usage(d).free
        if remaining is not None and free - remaining < reserve:
            raise DownloadError(f"not enough free space in {d}: {remaining} bytes needed + {reserve} reserve, "
                                f"{free} free")

    def _transfer(self, tid):
        t = self.get(tid)
        url = t["file_url"] or t["url"]
        if not t["file_url"] and t["url"].endswith(".meta4"):       # Kiwix catalog entry
            data, _ = self.client.get_bytes(t["url"], catalog_mod.META4_LIMIT)
            m4 = catalog_mod.parse_meta4(data)
            url = catalog_mod.direct_url(t["url"])
            self._set(tid, file_url=url, expected_sha256=m4.sha256 or t["expected_sha256"],
                      expected_size=m4.size or t["expected_size"],
                      filename=sanitize_filename(m4.name) if m4.name else None)
            t = self.get(tid)
        d, note = self._dest_dir(t)
        limit = int(getattr(self.settings, "max_download_gb", 256)) * 1024 ** 3
        part_name = t["filename"]
        offset = 0
        if part_name:
            part = d / f".{part_name}.part"
            offset = part.stat().st_size if part.is_file() else 0
        hdrs = {}
        validator = t["etag"] if t["etag"] and not t["etag"].startswith("W/") else t["last_modified"]
        if offset and validator:      # If-Range needs a strong validator; otherwise restart from 0
            hdrs = {"Range": f"bytes={offset}-", "If-Range": validator}
        self._check_flag(tid)
        r = self.client.request(url, headers=hdrs)
        try:
            if r.status == 416 and offset and t["total"] and offset >= t["total"]:
                r.close()
                return self._finalize(tid, d, note)
            if r.status not in (200, 206):
                raise (safehttp.NetError if r.status >= 500 or r.status == 429 else DownloadError)(
                    f"server answered HTTP {r.status}")
            ctype = r.header("content-type")
            if not part_name:
                part_name = choose_filename(r.url, r.header("content-disposition"), ctype)
                self._set(tid, filename=part_name)
            part = d / f".{part_name}.part"
            clen = r.header("content-length")
            clen = int(clen) if clen.isdigit() else None
            restart_note = ""
            if r.status == 206:
                m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", r.header("content-range"))
                if not m or int(m.group(1)) != offset:
                    raise DownloadError("server sent an unexpected byte range")
                total = int(m.group(3)) if m.group(3) != "*" else None
                mode = "ab"
            else:
                if offset:
                    restart_note = "server did not resume (no range support or file changed); restarted from 0"
                offset, total, mode = 0, clen, "wb"
            total = total or t["expected_size"] or None
            if t["expected_size"] and total and total != t["expected_size"]:
                raise DownloadError(f"server size {total} differs from the published size {t['expected_size']}")
            if total and total > limit:
                raise DownloadError(f"file is larger than the size limit ({limit} bytes)")
            self._space_ok(d, (total - offset) if total else None)
            self._set(tid, total=total, done=offset, etag=r.header("etag") or None,
                      last_modified=r.header("last-modified") or None,
                      note=restart_note or note or ("resumed" if offset else ""), dest_dir=t["dest_dir"] or "")
            done, since_check = offset, 0
            last_t, last_done = time.monotonic(), done
            flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "ab" else os.O_TRUNC)
            fd = os.open(part, flags | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                while True:
                    self._check_flag(tid)
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    since_check += len(chunk)
                    if total and done > total or done > limit:
                        raise DownloadError("server sent more data than announced")
                    if since_check >= SPACE_RECHECK:
                        f.flush()
                        self._space_ok(d, (total - done) if total else 0)
                        since_check = 0
                    now = time.monotonic()
                    if now - last_t >= 0.5:
                        self._set(tid, done=done, speed=(done - last_done) / (now - last_t))
                        last_t, last_done = now, done
                f.flush()
                os.fsync(f.fileno())
            self._set(tid, done=done)
            if total and done < total:
                raise safehttp.NetError(f"connection closed early ({done} of {total} bytes)")
            if not total:
                self._set(tid, total=done)
        finally:
            r.close()
        self._finalize(tid, d, note)

    def _finalize(self, tid, d, note):
        t = self.get(tid)
        part = d / f".{t['filename']}.part"
        self._set(tid, state=VERIFYING, speed=0)
        try:
            size = part.stat().st_size
            if t["expected_size"] and size != t["expected_size"]:
                raise DownloadError(f"size mismatch: {size} bytes, expected {t['expected_size']}")
            h = hashlib.sha256()
            with open(part, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    self._check_flag(tid)
                    h.update(chunk)
            digest = h.hexdigest()
            if t["expected_sha256"] and digest != t["expected_sha256"]:
                raise DownloadError(f"sha256 mismatch: got {digest[:16]}…, expected {t['expected_sha256'][:16]}…")
            want = ALLOWED_EXT[os.path.splitext(t["filename"])[1]]
            try:
                got = fileinfo.detect(part, os.path.splitext(t["filename"])[1])
            except (fileinfo.UnsupportedFile, fileinfo.CorruptFile) as exc:
                raise DownloadError(f"content check failed: {exc}") from None
            if got != want and not (want in ("txt", "md") and got in ("txt", "md")):
                raise DownloadError(f"content is {got.upper()}, not the expected {want.upper()}")
            if want == "zim":
                zim_check(part)
        except DownloadError as exc:
            failed = part.with_name(part.name + "-failed")
            os.replace(part, failed)
            self._set(tid, state=FAILED, error=str(exc), note=f"not added to the library; data kept as {failed.name}")
            return
        final = d / t["filename"]
        stem, ext = os.path.splitext(t["filename"])
        n = 1
        while True:
            try:
                os.link(part, final)          # atomic, never overwrites
                break
            except FileExistsError:
                final = d / f"{stem} ({n}){ext}"
                n += 1
        os.unlink(part)
        os.chmod(final, 0o644)
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        rep = discovery.Report()
        rid = discovery.register(self.index, str(final), "download", rep, allow_duplicate=False,
                                 keep_duplicate=False, managed=True)
        if rid is None:
            reason = rep.errors[-1][1] if rep.errors else "not registered"
            os.unlink(final)
            self._set(tid, state=FAILED, error=reason, note="the downloaded copy was removed (duplicate)")
            return
        for c in json.loads(t["categories"] or "[]"):
            self.index.add_to_category(rid, c)
        if t["title"] and t["catalog_uuid"] == "":
            self.index.set_override(rid, "title", t["title"])
        self.index.set_sha256(rid, digest)
        prior = t["note"] if t["note"] and "restarted" in t["note"] else ""
        note = "; ".join(x for x in (note, prior) if x)
        self._set(tid, state=DONE, final_path=str(final), rid=rid, done=size, total=size,
                  note=(note + "; " if note else "") + ("sha256 verified" if t["expected_sha256"] else
                                                       "no published checksum; content checked"))
        with self.lock:
            self.completed.append(rid)


def zim_check(path):
    """libzim integrity check (header, checksum, dirents, clusters). Raises DownloadError."""
    try:
        from libzim.reader import Archive
    except ImportError:
        raise DownloadError("python3-libzim is not installed; cannot verify the ZIM") from None
    try:
        a = Archive(str(path))
        ok = a.check()
    except Exception as exc:  # noqa: BLE001 - libzim raises RuntimeError on malformed files
        raise DownloadError(f"ZIM is damaged: {exc}") from None
    if not ok:
        raise DownloadError("ZIM integrity check (libzim Archive.check) failed")
