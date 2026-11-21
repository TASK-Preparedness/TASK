# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Reusable, embeddable Resources browser + reader (Phase 4F.3).

``ResourceBrowser`` is the same browse / metadata / search / read / navigate / bookmark UI that the T.A.S.K.
Resources window uses, packaged as a plain QWidget so another program (the launcher's Medical view) can embed it
in-process. It takes an existing ``Library`` (open it with ``read_only=True`` when embedding), an optional
``Scope`` that filters what is listed (e.g. medical), and a bookmark store. It never scans, imports, downloads,
edits or deletes; hosts add such actions themselves (task-resources' MainWindow does).

Exactly one reader (one viewer per engine, reused) exists per browser; switching engines parks the previous
viewer instead of destroying it (destroying a QWebEngineView with a live page deadlocked processEvents in the
Phase 4F.2 test runs).
"""

import html
import json
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from task_resources import viewer
from task_resources.index import UNCATEGORISED
from task_resources.viewer.pdf import PdfViewer

ALL = "__all__"
BOOKMARKS = "__bookmarks__"
EVERYTHING = "__everything__"


def _btn(text):
    b = QPushButton(text)
    b.setMinimumHeight(40)
    return b


@dataclass
class Scope:
    """Restricts the browser to resources for which ``reason(resource_dict)`` returns a non-empty string."""
    key: str
    label: str
    reason: object          # callable(dict) -> str
    allow_everything: bool = True   # offer an "everything in the library" entry (off by default)


# ---------------------------------------------------------------------- bookmark stores
class IndexBookmarks:
    """Bookmarks kept in the Resources index (standalone task-resources)."""

    def __init__(self, index):
        self.index = index

    def add(self, rid, path, title, resource_path=""):
        self.index.add_bookmark(rid, path, title)

    def remove(self, rid, path):
        self.index.remove_bookmark(rid, path)

    def list(self):
        return [{"resource_id": b["resource_id"], "path": b["path"], "title": b["title"] or b["path"],
                 "missing": bool(b["missing"])} for b in self.index.bookmarks()]


class JsonBookmarks:
    """Bookmarks in a private JSON file owned by the embedder (the Resources index stays untouched).
    Entries are keyed by the resource FILE path so they survive a reindex; ids are resolved on listing."""

    def __init__(self, path, index):
        self.path, self.index = Path(path), index

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [d for d in data if isinstance(d, dict) and {"resource_path", "path"} <= d.keys()]
        except (OSError, ValueError):
            return []

    def _save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".bm-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def add(self, rid, path, title, resource_path=""):
        rp = resource_path or (self.index.get(rid) or {}).get("path", "")
        items = [d for d in self._load() if not (d["resource_path"] == rp and d["path"] == path)]
        items.insert(0, {"resource_path": rp, "path": path, "title": title or path, "created": time.time()})
        self._save(items[:500])

    def remove(self, rid, path):
        rp = (self.index.get(rid) or {}).get("path", "")
        self._save([d for d in self._load() if not (d["resource_path"] == rp and d["path"] == path)])

    def list(self):
        out = []
        for d in self._load():
            rid = self.index.id_for_path(d["resource_path"])
            r = self.index.get(rid) if rid is not None else None
            out.append({"resource_id": rid, "path": d["path"], "title": d.get("title") or d["path"],
                        "missing": r is None or bool(r["missing"])})
        return out


# ---------------------------------------------------------------------- reader
class ReaderPane(QWidget):
    closed = Signal()

    def __init__(self, library, engine="lightweight", bookmarks=None, parent=None, guard=None):
        super().__init__(parent)
        self.library = library
        self.bookmarks = bookmarks
        self.guard = guard
        self.guard_note = ""
        if engine == "webengine" and guard is not None and guard.known_crash():
            # 0.2.4 crash guard: never auto-retry a configuration that crashed this host
            engine, self.guard_note = viewer.choose_guarded("webengine", guard)
        self.engine = engine
        self._viewers = {}
        rv = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.back_btn, self.fwd_btn, self.home_btn = _btn("◀ Back"), _btn("Forward ▶"), _btn("Main page")
        self.bm_btn, self.close_btn = _btn("☆ Bookmark"), _btn("Close")
        self.inside = QLineEdit()
        self.inside.returnPressed.connect(self.search_inside)
        self.mode = QLabel("")
        self.mode.setWordWrap(True)
        for w in (self.back_btn, self.fwd_btn, self.home_btn, self.bm_btn, self.inside, self.close_btn):
            bar.addWidget(w)
        rv.addLayout(bar)
        self.guard_bar = QWidget()
        gb = QHBoxLayout(self.guard_bar)
        gb.setContentsMargins(0, 0, 0, 0)
        self.guard_label = QLabel(self.guard_note)
        self.guard_label.setWordWrap(True)
        self.try_web_btn = _btn("Try enhanced reader")
        self.try_web_btn.setToolTip("Open this page in the WebEngine reader once more. If it stops the application "
                                    "again, the lightweight reader stays in use.")
        self.try_web_btn.clicked.connect(self.try_enhanced)
        gb.addWidget(self.guard_label, 1)
        gb.addWidget(self.try_web_btn)
        self.guard_bar.setVisible(bool(self.guard_note))
        rv.addWidget(self.guard_bar)
        rv.addWidget(self.mode)
        self.hits = QListWidget()
        self.hits.setMaximumHeight(140)
        self.hits.hide()
        self.hits.itemActivated.connect(self._hit)
        rv.addWidget(self.hits)
        self.reader_stack = QStackedWidget()
        self._pdf = None                 # created on first PDF (QtPdf is optional and not needed for ZIMs)
        rv.addWidget(self.reader_stack, 1)
        self.view = None
        self.set_engine(engine)
        self.back_btn.clicked.connect(self.view_back)
        self.fwd_btn.clicked.connect(self.view_forward)
        self.home_btn.clicked.connect(lambda: self.view.home())
        self.bm_btn.clicked.connect(self.bookmark)
        self.close_btn.clicked.connect(self.closed.emit)
        self.status_cb = lambda text, ms=5000: None

    @property
    def pdf(self):
        if self._pdf is None:
            self._pdf = PdfViewer()
            self.reader_stack.addWidget(self._pdf)
        return self._pdf

    def set_engine(self, engine):
        v = self._viewers.get(engine)
        if v is None:
            v = viewer.make_viewer(engine, self.library, guard=self.guard)
            v.listeners.append(self._viewer_event)
            self._viewers[engine] = v
            self.reader_stack.addWidget(v)
        was_current = self.view is not None and self.reader_stack.currentWidget() is self.view
        self.view, self.engine = v, engine
        if was_current or self._pdf is None or self.reader_stack.currentWidget() is not self._pdf:
            self.reader_stack.setCurrentWidget(v)
        return v

    def try_enhanced(self):
        """Manual opt-in after a guarded fallback: switch to WebEngine and re-open the current page. The guard
        arms again; a second crash keeps the lightweight reader as the automatic choice."""
        if not viewer.webengine_available()[0]:
            return False
        cur = self.view.nav.current if self.view is not None else None
        self.guard_bar.hide()
        v = self.set_engine("webengine")
        if cur is not None:
            return v.open(cur.rid, cur.path, cur.fragment)
        return True

    def open_resource(self, rid, path=None):
        r = self.library.index.get(rid)
        self.hits.hide()
        if r is None:
            self.mode.setText("This resource is no longer in the index.")
            return False
        if r["missing"] or not Path(r["path"]).is_file():
            self.reader_stack.setCurrentWidget(self.view)
            msg = f"File missing: {r['path']} was not found. Nothing was changed; reconnect the drive or rescan."
            self.view.last_error = msg
            self.view._show_error(msg)
            self.mode.setText(msg)
            return False
        if r["kind"] == "pdf":
            self.reader_stack.setCurrentWidget(self.pdf)
            ok, msg = self.pdf.open(r["path"])
            self.mode.setText(msg)
            return ok
        self.reader_stack.setCurrentWidget(self.view)
        if r["kind"] == "zim":
            self.inside.setPlaceholderText("Search inside this ZIM")
            self.mode.setText("Full-text search available" if r["has_fulltext"]
                              else "Title search only — this ZIM has no full-text index")
        else:
            self.inside.setPlaceholderText("Search chapter names")
            self.mode.setText("")
        if r["kind"] in ("odt", "docx"):
            self.view.last_error = f"{r['kind'].upper()} documents are listed but cannot be shown in this version"
            self.view._show_error(self.view.last_error)
            return False
        ok = self.view.open(rid, path)
        if not ok and r["kind"] == "zim":
            self.mode.setText(f"This ZIM could not be read ({self.view.last_error}). The file may be damaged or "
                              "incomplete; it was not modified. Try another copy or re-download it in "
                              "T.A.S.K. Resources.")
        return ok

    def view_back(self):
        return self.view.back()

    def view_forward(self):
        return self.view.forward()

    def _viewer_event(self, event, **d):
        if event == "blocked":
            self.status_cb(f"External address not opened (offline reader): {d['url']}", 8000)
        elif event == "error":
            self.status_cb(d["message"], 8000)
        self.back_btn.setEnabled(self.view.nav.can_back())
        self.fwd_btn.setEnabled(self.view.nav.can_forward())

    def search_inside(self):
        cur = self.view.nav.current
        if cur is None:
            return None
        try:
            res = self.library.source(cur.rid).search(self.inside.text())
        except Exception as exc:  # noqa: BLE001
            self.mode.setText(f"Search failed: {exc}")
            return None
        self.hits.clear()
        for path, title in res.hits:
            it = QListWidgetItem(title or path)
            it.setData(Qt.ItemDataRole.UserRole, (cur.rid, path))
            self.hits.addItem(it)
        mode = "Full-text results" if res.mode == "full-text" else "Title matches"
        self.mode.setText(f"{mode}: {res.estimated} · {res.note}".rstrip(" ·"))
        self.hits.setVisible(True)
        return res

    def _hit(self, item):
        rid, path = item.data(Qt.ItemDataRole.UserRole)
        self.view.open(rid, path)

    def bookmark(self):
        cur = self.view.nav.current
        if cur and self.bookmarks is not None:
            try:
                self.bookmarks.add(cur.rid, cur.path, self.view.last_title)
                self.status_cb("Bookmarked", 3000)
                return True
            except Exception as exc:  # noqa: BLE001
                self.status_cb(f"Bookmark not saved: {exc}", 8000)
        return False

    def shutdown(self):
        """Stop every viewer's loads. Child views get no closeEvent when their window closes, so WebEngine pages
        were left loading; this is called from the host's closeEvent."""
        for v in self._viewers.values():
            stop = getattr(v, "stop", None)
            if stop is not None:
                stop()
            v.close()            # WebViewer.closeEvent releases its page before the shared profile

    def clear(self):
        """Blank the reader (used when a host locks)."""
        self.view._show_error("")
        self.hits.clear()
        self.hits.hide()
        self.mode.setText("")


# ---------------------------------------------------------------------- browser
class ResourceBrowser(QWidget):
    def __init__(self, library, engine="lightweight", scope=None, bookmarks=None, parent=None, guard=None):
        super().__init__(parent)
        self.library, self.index = library, library.index
        self.scope = scope
        self.bookmarks = bookmarks if bookmarks is not None else IndexBookmarks(self.index)
        self.on_details = lambda r: None            # host hook (e.g. enable Delete)
        self.status_cb = lambda text, ms=5000: None
        self._cq = queue.Queue()
        self._cgen = 0
        v = QVBoxLayout(self)
        self.toolbar = QHBoxLayout()
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a resource — searches titles and metadata in the T.A.S.K. index")
        self.find.textChanged.connect(lambda _: self.refresh_list())
        self.contents = QCheckBox("Search inside ZIMs")
        self.contents.setToolTip("Also search the article text of the listed ZIMs (full-text where the ZIM has an "
                                 "index, titles otherwise). Press Enter in the search box.")
        self.find.returnPressed.connect(self.search_contents)
        self.toolbar.addWidget(self.find, 1)
        self.toolbar.addWidget(self.contents)
        v.addLayout(self.toolbar)
        split = QSplitter()
        self.cats = QListWidget()
        self.cats.currentItemChanged.connect(lambda *_: self.refresh_list())
        self.items = QListWidget()
        self.items.currentItemChanged.connect(lambda *_: self.show_details())
        self.items.itemActivated.connect(lambda *_: self.open_current())
        self.stack = QStackedWidget()
        split.addWidget(self.cats)
        split.addWidget(self.items)
        split.addWidget(self.stack)
        split.setSizes([180, 300, 620])
        v.addWidget(split, 1)
        det = QWidget()
        dv = QVBoxLayout(det)
        self.details = QTextBrowser()
        dv.addWidget(self.details)
        self.details_row = QHBoxLayout()
        self.open_btn = _btn("Open")
        self.open_btn.clicked.connect(self.open_current)
        self.details_row.addWidget(self.open_btn)
        dv.addLayout(self.details_row)
        self.stack.addWidget(det)
        self.reader = ReaderPane(library, engine, self.bookmarks, guard=guard)
        self.reader.closed.connect(lambda: self.stack.setCurrentIndex(0))
        self.reader.status_cb = lambda t, ms=5000: self.status_cb(t, ms)
        self.stack.addWidget(self.reader)
        self.empty = QLabel("")
        self.empty.setWordWrap(True)
        self.empty.hide()
        v.addWidget(self.empty)
        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._drain_contents)
        self._ctimer.start(100)

    # reader passthroughs (keep the pre-4F.3 MainWindow attribute names working)
    view = property(lambda self: self.reader.view)
    pdf = property(lambda self: self.reader.pdf)
    mode = property(lambda self: self.reader.mode)
    inside = property(lambda self: self.reader.inside)
    hits = property(lambda self: self.reader.hits)
    reader_stack = property(lambda self: self.reader.reader_stack)

    # ------------------------------------------------------------------ data
    def _scoped(self, rows):
        if self.scope is None or self._category() == EVERYTHING:
            return rows
        return [r for r in rows if self.scope.reason(r)]

    def scoped_resources(self):
        return self._scoped(self.index.list())

    def refresh(self):
        cur = self._category()
        self.cats.blockSignals(True)
        self.cats.clear()
        if self.scope is None:
            c = self.index.counts()
            entries = [(ALL, f"All resources ({c['total']})"), (UNCATEGORISED, "Uncategorised")]
            entries += [(name, f"{name} ({n})") for name, n in self.index.categories()]
        else:
            rows = [r for r in self.index.list() if self.scope.reason(r)]
            entries = [(ALL, f"{self.scope.label} — all ({len(rows)})")]
            counts = {}
            for r in rows:
                for c in r["categories"]:
                    counts[c] = counts.get(c, 0) + 1
            entries += [(name, f"{name} ({n})") for name, n in sorted(counts.items(), key=lambda x: x[0].casefold())]
        entries.append((BOOKMARKS, f"☆ Bookmarks ({len(self._bookmarks())})"))
        if self.scope is not None and self.scope.allow_everything:
            entries.append((EVERYTHING, "Everything in the library (unfiltered)"))
        for key, label in entries:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.cats.addItem(it)
        sel = 0
        for i in range(self.cats.count()):
            if self.cats.item(i).data(Qt.ItemDataRole.UserRole) == (cur or ALL):
                sel = i
        self.cats.setCurrentRow(sel)
        self.cats.blockSignals(False)
        self.refresh_list()

    def _bookmarks(self):
        try:
            return self.bookmarks.list()
        except Exception:  # noqa: BLE001
            return []

    def _category(self):
        it = self.cats.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def refresh_list(self):
        cat = self._category()
        self.items.clear()
        if cat == BOOKMARKS:
            for b in self._bookmarks():
                it = QListWidgetItem(f"☆ {b['title']}" + ("  — file missing" if b["missing"] else ""))
                it.setData(Qt.ItemDataRole.UserRole, ("bm", b["resource_id"], b["path"]))
                self.items.addItem(it)
            self._update_empty()
            return
        rows = self.index.list(category=None if cat in (None, ALL, EVERYTHING) else cat,
                               query=self.find.text() or None)
        for r in self._scoped(rows):
            label = f"{r['title'] or Path(r['path']).name}  [{r['kind'].upper()}]"
            if r["missing"]:
                label += "  — file missing"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.items.addItem(it)
        self._update_empty()

    def _update_empty(self):
        if self.items.count() or self.scope is None:
            self.empty.hide()
            return
        if self._category() == BOOKMARKS:
            self.empty.setText("No bookmarks yet. Open an article and press ☆ Bookmark.")
        elif self.find.text():
            self.empty.setText("Nothing matches that search here. Tick “Search inside ZIMs” and press Enter to "
                               "search article text.")
        else:
            self.empty.setText(f"No {self.scope.label.lower()} resources are in the T.A.S.K. Resources index. Add "
                               f"them in T.A.S.K. Resources (or give items the category “{self.scope.label}”).")
        self.empty.show()

    def current_id(self):
        it = self.items.currentItem()
        d = it.data(Qt.ItemDataRole.UserRole) if it else None
        return d[1] if isinstance(d, tuple) else d

    def show_details(self):
        it = self.items.currentItem()
        d = it.data(Qt.ItemDataRole.UserRole) if it else None
        self.stack.setCurrentIndex(0)
        if isinstance(d, tuple):                      # bookmark / content hit
            self.details.setHtml(f"<b>{html.escape(it.text())}</b><br>{html.escape(str(d[2]))}")
            self.open_btn.setEnabled(d[1] is not None)
            return
        if d is None:
            self.details.clear()
            return
        r = self.index.get(d)
        e = html.escape
        rows = [("Title", r["title"]), ("Kind", r["kind"].upper()), ("File", r["path"]),
                ("Storage", "T.A.S.K. managed" if r["managed"] else "external (protected, never deleted)"),
                ("Size", f"{r['size']:,} bytes" if r["size"] is not None else "—"),
                ("Description", r["description"]), ("Language", r["language"]),
                ("Creator", r["creator"]), ("Publisher", r["publisher"]), ("Date", r["date"]),
                ("Categories", ", ".join(r["categories"]) or "—"), ("Notes", r["notes"])]
        if self.scope is not None:
            rows.append(("Listed because", self.scope.reason(r) or "unfiltered view"))
        if r["kind"] == "zim":
            rows += [("Articles", r["article_count"]),
                     ("Search", "full-text index" if r["has_fulltext"] else "title search only (no full-text index)")]
        if r["missing"]:
            rows.insert(0, ("Status", "FILE MISSING — the entry is kept; the file was not found"))
        if r["copies"]:
            rows.append(("Other copies", "<br>".join(e(p) for p in r["copies"])))
        if r["overrides"]:
            rows.append(("Edited", ", ".join(sorted(r["overrides"]))))
        self.details.setHtml("<table>" + "".join(
            f"<tr><td><b>{e(k)}</b></td><td>{v if k == 'Other copies' else e(str(v if v is not None else ''))}</td></tr>"
            for k, v in rows) + "</table>")
        self.open_btn.setEnabled(not r["missing"])
        self.on_details(r)

    # ------------------------------------------------------------------ reading
    def open_current(self):
        it = self.items.currentItem()
        d = it.data(Qt.ItemDataRole.UserRole) if it else None
        if d is None:
            return False
        if isinstance(d, tuple):
            if d[1] is None:
                self.status_cb("That bookmark's file is no longer in the index.", 6000)
                return False
            return self.open_resource(d[1], d[2])
        return self.open_resource(d)

    def open_resource(self, rid, path=None):
        self.stack.setCurrentWidget(self.reader)
        return self.reader.open_resource(rid, path)

    def search_inside(self):
        return self.reader.search_inside()

    def view_back(self):
        return self.reader.view_back()

    def view_forward(self):
        return self.reader.view_forward()

    def bookmark(self):
        ok = self.reader.bookmark()
        if ok and self._category() == BOOKMARKS:
            self.refresh_list()
        return ok

    def set_engine(self, engine):
        return self.reader.set_engine(engine)

    # ------------------------------------------------------------------ content (article) search, background
    def search_contents(self, wait=False):
        """Search article text across the listed ZIMs in a worker thread; results are appended as they come."""
        q = self.find.text().strip()
        if not (self.contents.isChecked() and q):
            return None
        self._cgen += 1
        gen = self._cgen
        zims = [r for r in self._scoped(self.index.list()) if r["kind"] == "zim" and not r["missing"]]
        self.items.clear()
        self.status_cb(f"Searching inside {len(zims)} ZIM(s)…", 3000)

        def work():
            for r in zims:
                try:
                    res = self.library.source(r["id"]).search(q, limit=15)
                    self._cq.put((gen, r, res, ""))
                except Exception as exc:  # noqa: BLE001
                    self._cq.put((gen, r, None, str(exc) or type(exc).__name__))
            self._cq.put((gen, None, None, "done"))

        t = threading.Thread(target=work, name="task-resources-contents", daemon=True)
        t.start()
        if wait:
            t.join(60)
            self._drain_contents()
        return t

    def _drain_contents(self):
        while True:
            try:
                gen, r, res, err = self._cq.get_nowait()
            except queue.Empty:
                return
            if gen != self._cgen:
                continue
            if r is None:
                if not self.items.count():
                    self.empty.setText("No article matches inside the listed ZIMs.")
                    self.empty.setVisible(self.scope is not None)
                continue
            if err:
                it = QListWidgetItem(f"⚠ {r['title']}: search failed ({err})")
                self.items.addItem(it)
                continue
            kind = "full-text" if res.mode == "full-text" else "title"
            for path, title in res.hits:
                it = QListWidgetItem(f"{title or path}  — in {r['title']} ({kind})")
                it.setData(Qt.ItemDataRole.UserRole, ("hit", r["id"], path))
                self.items.addItem(it)
            self.empty.hide()

    def shutdown(self):
        self._ctimer.stop()
        self._cgen += 1
        self.reader.shutdown()

    def clear_for_lock(self):
        self.stack.setCurrentIndex(0)
        self.reader.clear()
        self.details.clear()
