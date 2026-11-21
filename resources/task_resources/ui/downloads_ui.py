# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4E UI: "Download from Website" tab, "Online ZIM Catalog" tab and the Downloads window.

Nothing here blocks the GUI thread: network work runs in JobRunner threads (preview, catalog refresh)
or in the DownloadManager worker thread; widgets are refreshed from a QTimer that only reads SQLite."""

import os
import shutil
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTabWidget,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from task_resources import catalog as cat
from task_resources import downloads as dl
from task_resources import managed

ONLINE_ONLY = "needs an Internet connection"


def human(n):
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def human_eta(s):
    if s is None:
        return "—"
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s"


def _btn(text):
    b = QPushButton(text)
    b.setMinimumHeight(40)
    return b


class DestinationRow(QWidget):
    """Managed storage (default) or a user-chosen folder; shows free space."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit()
        self.path.setPlaceholderText("T.A.S.K. managed storage (default)")
        self.pick = QPushButton("Choose folder…")
        self.pick.clicked.connect(self._pick)
        h.addWidget(self.path, 1)
        h.addWidget(self.pick)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Download into folder", os.path.expanduser("~"))
        if d:
            self.path.setText(d)

    def value(self):
        return self.path.text().strip()

    def free_text(self):
        try:
            if self.value():
                d, note = self.value(), ""
            else:
                root, note = managed.resolve_root(self.settings)
                d = str(root)
            probe = d
            while not os.path.exists(probe) and probe != os.path.dirname(probe):
                probe = os.path.dirname(probe)
            free = shutil.disk_usage(probe).free
            return f"Destination: {d} · free {human(free)}" + (f" — {note}" if note else "")
        except OSError as exc:
            return f"Destination not usable: {exc}"


class DownloadTab(QWidget):
    def __init__(self, manager, jobs, categories, parent=None):
        super().__init__(parent)
        self.manager, self.jobs, self.preview_job = manager, jobs, None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Download a ZIM, PDF, EPUB, HTML, TXT or Markdown file from a web address. "
                             f"({ONLINE_ONLY}). The file is checked before it appears in the library."))
        form = QFormLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://example.org/guide.pdf")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(["Downloads"] + [c for c in categories if c != "Downloads"])
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("(optional) more categories, comma separated")
        self.dest = DestinationRow(manager.settings)
        self.sha = QLineEdit()
        self.sha.setPlaceholderText("(optional) published sha256 to verify against")
        form.addRow("Address", self.url)
        form.addRow("Category", self.category)
        form.addRow("Also in", self.extra)
        form.addRow("Destination", self.dest)
        form.addRow("SHA-256", self.sha)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.check = _btn("Check address")
        self.start = _btn("Add to downloads")
        row.addWidget(self.check)
        row.addWidget(self.start)
        lay.addLayout(row)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.free = QLabel(self.dest.free_text())
        lay.addWidget(self.info)
        lay.addWidget(self.free)
        lay.addStretch(1)
        self.check.clicked.connect(self.run_preview)
        self.start.clicked.connect(self.enqueue)
        self.dest.path.textChanged.connect(lambda _: self.free.setText(self.dest.free_text()))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(200)

    def categories(self):
        cats = [self.category.currentText().strip()] + [c.strip() for c in self.extra.text().split(",")]
        return [c for c in dict.fromkeys(cats) if c]

    def run_preview(self):
        url = self.url.text().strip()
        self.info.setText("Checking…")
        self.preview_job = self.jobs.start("preview", lambda job: self.manager.preview(url))
        return self.preview_job

    def _poll(self):
        j = self.preview_job
        if j and not j.active:
            self.preview_job = None
            if j.state == "done":
                p = j.result
                self.info.setText(f"File: <b>{p['filename']}</b> · size {human(p['size'])} · "
                                  f"{'resumable' if p['resume'] else 'no resume support'} · {p['type'] or '?'}")
            else:
                self.info.setText(f"Cannot download: {j.error.split(': ', 1)[-1]}")

    def enqueue(self):
        try:
            tid = self.manager.add(self.url.text().strip(), self.categories(), self.dest.value(),
                                   expected_sha256=self.sha.text().strip())
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.info.setText(f"Not added: {exc}")
            return None
        self.info.setText(f"Added to downloads (#{tid}).")
        return tid


class CatalogTab(QWidget):
    COLS = ["Title", "Language", "Size", "Category", "Publisher", "Format", "Installed", "Description"]

    def __init__(self, catalog, manager, jobs, index, parent=None):
        super().__init__(parent)
        self.catalog, self.manager, self.jobs, self.index = catalog, manager, jobs, index
        self.refresh_job, self.shown = None, []
        lay = QVBoxLayout(self)
        self.state = QLabel("")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search titles and descriptions")
        self.category = QComboBox()
        self.lang = QComboBox()
        self.subject = QComboBox()
        self.maxsize = QComboBox()
        for label, mb in (("Any size", 0), ("≤ 100 MB", 100), ("≤ 1 GB", 1024), ("≤ 10 GB", 10240),
                          ("≤ 50 GB", 51200)):
            self.maxsize.addItem(label, mb)
        self.update = _btn("Update catalog")
        for w in (self.query, self.category, self.lang, self.subject, self.maxsize, self.update):
            row.addWidget(w)
        lay.addLayout(row)
        self.results = QTableWidget(0, len(self.COLS))
        self.results.setHorizontalHeaderLabels(self.COLS)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.itemSelectionChanged.connect(self._details)
        lay.addWidget(self.results, 1)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.setMaximumHeight(110)
        lay.addWidget(self.detail)
        drow = QHBoxLayout()
        self.dest = DestinationRow(manager.settings)
        self.download = _btn("Download and verify")
        drow.addWidget(self.dest, 1)
        drow.addWidget(self.download)
        lay.addLayout(drow)
        self.query.textChanged.connect(lambda _: self.apply_filter())
        for c in (self.category, self.lang, self.subject, self.maxsize):
            c.currentIndexChanged.connect(lambda _: self.apply_filter())
        self.update.clicked.connect(self.refresh_catalog)
        self.download.clicked.connect(self.enqueue)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(200)
        if not catalog.entries:
            catalog.load_cached()
        self._facets()
        self.apply_filter()
        self._state_text()

    def _state_text(self):
        c = self.catalog
        if c.entries:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c.fetched_at)) if c.fetched_at else "?"
            s = f"{len(c.entries)} entries · catalog from {when}"
            if c.online is False:
                s += f" · <b>offline</b> (showing the saved copy; {c.error})"
        elif c.online is False:
            s = f"<b>Offline</b> — no saved catalog yet ({c.error}). Downloading {ONLINE_ONLY}."
        else:
            s = f"No catalog saved yet. Press “Update catalog” ({ONLINE_ONLY})."
        self.state.setText(s)

    def _facets(self):
        cats, langs, _ = self.catalog.facets()
        subjects = sorted({s for e in self.catalog.entries for s in e.subjects})
        for box, items, label in ((self.category, cats, "All categories"), (self.lang, langs, "All languages"),
                                  (self.subject, subjects, "All subjects")):
            cur = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(label, "")
            for i in items:
                box.addItem(i, i)
            ix = box.findData(cur)
            box.setCurrentIndex(max(0, ix))
            box.blockSignals(False)

    def apply_filter(self):
        self.shown = self.catalog.search(self.query.text(), self.lang.currentData() or "",
                                         self.category.currentData() or "", self.subject.currentData() or "",
                                         max_size=(self.maxsize.currentData() or 0) * 1024 * 1024)
        self.results.setRowCount(0)
        for e in self.shown[:500]:
            r = self.results.rowCount()
            self.results.insertRow(r)
            vals = [e.title, ",".join(e.languages), human(e.size), e.category, e.publisher, e.format,
                    "yes" if cat.installed(self.index, e) else "", e.summary]
            for c, v in enumerate(vals):
                self.results.setItem(r, c, QTableWidgetItem(v))
        return self.shown

    def selected(self):
        rows = self.results.selectionModel().selectedRows() if self.results.selectionModel() else []
        return self.shown[rows[0].row()] if rows else None

    def _details(self):
        e = self.selected()
        if e:
            import html as h
            self.detail.setHtml(f"<b>{h.escape(e.title)}</b> ({h.escape(e.name)}) · {e.article_count:,} articles · "
                                f"issued {h.escape(e.issued[:10])} · author {h.escape(e.author)}<br>"
                                f"{h.escape(e.summary)}")

    def refresh_catalog(self):
        if self.refresh_job and self.refresh_job.active:
            return self.refresh_job
        self.state.setText("Updating catalog…")
        self.refresh_job = self.jobs.start("catalog", lambda job: self.catalog.refresh())
        return self.refresh_job

    def _poll(self):
        j = self.refresh_job
        if j and not j.active:
            self.refresh_job = None
            self.manager.set_offline(not bool(j.result))
            self._facets()
            self.apply_filter()
            self._state_text()

    def enqueue(self):
        e = self.selected()
        if e is None:
            self.state.setText("Select an entry first.")
            return None
        try:
            tid = self.manager.add_catalog_entry(e, dest_dir=self.dest.value())
        except Exception as exc:  # noqa: BLE001
            self.state.setText(f"Not added: {exc}")
            return None
        self.state.setText(f"“{e.title}” added to downloads (#{tid}).")
        return tid


class DownloadsWindow(QWidget):
    TABS = (("Active", (dl.RUNNING, dl.VERIFYING)), ("Queued", (dl.QUEUED, dl.WAITING)),
            ("Paused", (dl.PAUSED,)), ("Completed", (dl.DONE,)), ("Failed", (dl.FAILED, dl.CANCELLED)))
    COLS = ["#", "Name", "State", "Progress", "Bytes", "Speed", "ETA", "Note"]

    def __init__(self, manager, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.manager = manager
        self.setWindowTitle("Downloads — T.A.S.K. Resources")
        self.resize(980, 460)
        v = QVBoxLayout(self)
        self.offline = QLabel("")
        v.addWidget(self.offline)
        self.tabs = QTabWidget()
        self.tables = {}
        for name, _ in self.TABS:
            t = QTableWidget(0, len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.tables[name] = t
            self.tabs.addTab(t, name)
        v.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        self.pause, self.resume, self.cancel = _btn("Pause"), _btn("Resume"), _btn("Cancel")
        self.retry, self.forget = _btn("Retry"), _btn("Remove from list")
        for b, fn in ((self.pause, manager.pause), (self.resume, manager.resume), (self.cancel, self._cancel),
                      (self.retry, manager.retry), (self.forget, manager.forget)):
            b.clicked.connect(lambda _=False, fn=fn: self._act(fn))
            row.addWidget(b)
        v.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _cancel(self, tid):
        if QMessageBox.question(self, "Cancel download", "Cancel and delete the partial data?") == \
                QMessageBox.StandardButton.Yes:
            self.manager.cancel(tid)

    def selected_id(self):
        t = self.tabs.currentWidget()
        rows = t.selectionModel().selectedRows() if t.selectionModel() else []
        return int(t.item(rows[0].row(), 0).text()) if rows else None

    def _act(self, fn):
        tid = self.selected_id()
        if tid is not None:
            fn(tid)
            self.refresh()

    def counts(self):
        return {name: self.tables[name].rowCount() for name, _ in self.TABS}

    def refresh(self):
        if getattr(self.manager, "closed", False):     # 4F.3: no polling of a closed manager's database
            self.timer.stop()
            return
        rows = self.manager.list()
        self.offline.setText("<b>Offline mode</b>: transfers wait and continue when the network returns."
                             if self.manager.offline else "")
        for name, states in self.TABS:
            t = self.tables[name]
            sel = self.selected_id() if self.tabs.currentWidget() is t else None
            mine = [r for r in rows if r["state"] in states]
            t.setRowCount(len(mine))
            for i, r in enumerate(mine):
                pct = f"{100 * r['done'] / r['total']:.1f}%" if r["total"] else "—"
                vals = [str(r["id"]), r["filename"] or r["title"] or r["url"], r["state"], pct,
                        f"{human(r['done'])} / {human(r['total'])}",
                        f"{human(r['speed'])}/s" if r["speed"] else "—",
                        human_eta(dl.eta(r["done"], r["total"], r["speed"])) if r["state"] == dl.RUNNING else "—",
                        r["error"] or r["note"] or ""]
                for c, val in enumerate(vals):
                    t.setItem(i, c, QTableWidgetItem(val))
                if sel == r["id"]:
                    t.selectRow(i)
            self.tabs.setTabText(self.tabs.indexOf(t), f"{name} ({len(mine)})")
