# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. Resources main window."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget

from task_resources import __version__, discovery, importer, managed, settings as settings_mod, viewer
from task_resources import catalog as catalog_mod
from task_resources import downloads as downloads_mod
from task_resources.jobs import JobRunner
from task_resources.ui.add_dialog import AddResourceDialog
from task_resources.ui.browser import ResourceBrowser
from task_resources.ui.edit_dialog import EditDialog

VIEWER_LABELS = {"auto": "Viewer: automatic", "webengine": "Viewer: WebEngine", "lightweight": "Viewer: lightweight"}


def _btn(text):
    b = QPushButton(text)
    b.setMinimumHeight(40)
    return b


class MainWindow(QMainWindow):
    def __init__(self, library, settings_path=None, scan_on_start=True, manager=None, catalog=None, guard=None):
        super().__init__()
        self.library, self.index, self.settings = library, library.index, library.settings
        # Phase 4E: nothing is contacted at start; the cached catalog is read from disk only.
        self.catalog = catalog or catalog_mod.Catalog(self.settings.catalog_url)
        self.manager = manager or downloads_mod.DownloadManager(library, catalog=self.catalog)
        self.downloads_window = None
        self.settings_path = settings_path
        self.jobs = JobRunner()
        self.scan_job = None
        self._handled = set()
        self.setWindowTitle(f"T.A.S.K. Resources {__version__}")
        self.resize(1100, 680)
        self.guard = guard                 # 0.2.4 WebEngine crash guard (None in tests unless given)
        self.engine, note = viewer.choose_guarded(self.settings.viewer, guard)
        self._build()
        self.viewer_note.setText(note)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(250)
        if scan_on_start:
            self.rescan()

    def __getattr__(self, name):
        # Phase 4F.3: browsing/reading moved into the shared ResourceBrowser; keep the old attribute names.
        b = self.__dict__.get("browser")
        if b is None or name.startswith("__"):
            raise AttributeError(name)
        return getattr(b, name)

    # explicit for names that Qt already defines (QWidget.find) — __getattr__ would never be reached
    find = property(lambda self: self.browser.find)

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        v = QVBoxLayout(root)
        self.browser = ResourceBrowser(self.library, self.engine, guard=self.guard)
        self.browser.status_cb = lambda t, ms=5000: self.statusBar().showMessage(t, ms)
        self.browser.on_details = self._details_shown
        top = self.browser.toolbar
        self.add = _btn("Add Resource")
        self.add.clicked.connect(self.open_add_dialog)
        self.rescan_btn = _btn("Rescan")
        self.rescan_btn.clicked.connect(self.rescan)
        self.dl_btn = _btn("Downloads")
        self.dl_btn.clicked.connect(self.open_downloads)
        self.viewer_choice = QComboBox()
        for k in viewer.CHOICES:
            self.viewer_choice.addItem(VIEWER_LABELS[k], k)
        self.viewer_choice.setCurrentIndex(max(0, viewer.CHOICES.index(self.settings.viewer)
                                               if self.settings.viewer in viewer.CHOICES else 0))
        self.viewer_choice.currentIndexChanged.connect(self._viewer_changed)
        for w in (self.add, self.rescan_btn, self.dl_btn, self.viewer_choice):
            top.addWidget(w)
        self.viewer_note = QLabel("")
        self.viewer_note.setWordWrap(True)
        v.addWidget(self.viewer_note)
        v.addWidget(self.browser, 1)
        self.edit_btn, self.remove_btn = _btn("Edit…"), _btn("Forget")
        self.delete_btn = _btn("Delete file…")
        self.delete_btn.setToolTip("Only for files T.A.S.K. downloaded or copied into managed storage.")
        self.delete_btn.clicked.connect(self.delete_current)
        self.edit_btn.clicked.connect(self.edit_current)
        self.remove_btn.clicked.connect(self.forget_current)
        self.remove_btn.setToolTip("Remove from the T.A.S.K. index only. The file is not deleted.")
        for b in (self.edit_btn, self.remove_btn, self.delete_btn):
            self.browser.details_row.addWidget(b)
        self.setCentralWidget(root)
        self.status = QLabel("")
        self.statusBar().addWidget(self.status, 1)

    def _details_shown(self, r):
        self.delete_btn.setEnabled(bool(r["managed"]) and managed.is_managed_path(r["path"], self.settings))

    # ------------------------------------------------------------------ data
    def refresh(self):
        self.browser.refresh()
        c = self.index.counts()
        self.status.setText(f"{c['total']} resources · {c['missing']} missing · {c['duplicates']} duplicate copies"
                            + self._storage_text())

    def show_details(self):
        self.delete_btn.setEnabled(False)
        return self.browser.show_details()

    def edit_current(self):
        rid = self.current_id()
        if rid is None:
            return
        d = EditDialog(self.index.get(rid), self)
        if d.exec():
            d.apply(self.index)
            self.refresh()

    def forget_current(self):
        rid = self.current_id()
        if rid is None:
            return
        if QMessageBox.question(self, "Forget resource", "Remove it from the T.A.S.K. index? The file stays "
                                "where it is.") == QMessageBox.StandardButton.Yes:
            self.index.remove(rid)
            self.library.pool.drop(rid)
            self.refresh()

    def delete_current(self, confirm=True):
        rid = self.current_id()
        if rid is None:
            return None
        r = self.index.get(rid)
        if confirm and QMessageBox.question(
                self, "Delete file", f"Delete {r['path']} from disk and remove it from the library?\n"
                "This cannot be undone.") != QMessageBox.StandardButton.Yes:
            return None
        try:
            self.library.pool.drop(rid)
            path = managed.remove_managed(self.index, self.settings, rid)
        except (OSError, managed.ManagedError) as exc:
            self.statusBar().showMessage(f"Not deleted: {exc}", 10000)
            return None
        self.statusBar().showMessage(f"Deleted {path}", 8000)
        self.refresh()
        return path

    def make_add_dialog(self):
        return AddResourceDialog([n for n, _ in self.index.categories()], self, manager=self.manager,
                                 catalog=self.catalog, jobs=self.jobs, index=self.index)

    def open_add_dialog(self):
        d = self.make_add_dialog()
        if d.exec() and d.tabs.currentIndex() == 0:
            self.run_import(d.request())

    def open_downloads(self):
        from task_resources.ui.downloads_ui import DownloadsWindow
        if self.downloads_window is None:
            self.downloads_window = DownloadsWindow(self.manager, self)
        self.downloads_window.show()
        self.downloads_window.raise_()
        return self.downloads_window

    def run_import(self, req):
        job = self.jobs.start("import", lambda job: importer.import_paths(self.library, job=job, **req))
        return job

    def rescan(self):
        if self.scan_job and self.scan_job.active:
            return self.scan_job
        self.scan_job = self.jobs.start("scan", lambda job: discovery.scan(self.index, self.settings, job))
        return self.scan_job

    def _viewer_changed(self):
        self.settings.viewer = self.viewer_choice.currentData()
        try:
            settings_mod.save(self.settings, self.settings_path)
        except OSError as exc:
            self.statusBar().showMessage(f"settings not saved: {exc}", 8000)
        engine, note = viewer.choose(self.settings.viewer)
        if engine != self.engine:
            self.engine = engine
            self.browser.set_engine(engine)       # viewers are reused, never destroyed (4F.3 hang fix)
        self.viewer_note.setText(note)

    def _storage_text(self):
        try:
            u = managed.usage(self.settings, self.index)
        except OSError:
            return ""
        return (f" · managed: {u['managed_count']} files, {u['managed_bytes'] / 1e9:.2f} GB · "
                f"free {u['free'] / 1e9:.1f} GB in {u['root']}" + (f" ({u['note']})" if u["note"] else ""))

    def _poll(self):
        with self.manager.lock:
            new = list(self.manager.completed)
            self.manager.completed.clear()
        n_act = len(self.manager.list((downloads_mod.RUNNING, downloads_mod.VERIFYING, downloads_mod.QUEUED,
                                        downloads_mod.WAITING)))
        self.dl_btn.setText(f"Downloads ({n_act})" if n_act else "Downloads")
        if new:                                   # new resources appear without a restart
            self.refresh()
            self.statusBar().showMessage(f"{len(new)} download(s) verified and added to the library", 8000)
        act = self.jobs.active()
        if act:
            j = act[0]
            self.statusBar().showMessage(f"{j.name}: {j.done}{'/' + str(j.total) if j.total else ''} {j.message}"[:160])
        finished = [j for j in self.jobs.jobs if not j.active and id(j) not in self._handled]
        for j in finished:
            self._handled.add(id(j))
            if j.state == "failed":
                self.statusBar().showMessage(f"{j.name} failed: {j.error}", 10000)
            elif j.state == "done" and j.name == "import":
                bad = [r for r in j.result if r.status in ("error", "duplicate")]
                notes = {r.message for r in j.result if "not writable" in r.message}
                msg = f"import: {len(j.result) - len(bad)} added, {len(bad)} not added"
                self.statusBar().showMessage(" · ".join([msg, *notes, *(f"{r.path}: {r.message}" for r in bad[:3])]),
                                             15000)
        if finished:
            self.refresh()

    def closeEvent(self, e):
        self.timer.stop()
        self.browser.shutdown()
        if self.downloads_window is not None:
            self.downloads_window.timer.stop()
            self.downloads_window.close()
        self.jobs.cancel_all()
        self.manager.stop()          # running transfers are paused; the .part files are kept
        super().closeEvent(e)
