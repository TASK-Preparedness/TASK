# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Native Medical view inside the launcher window (Phase 4F.3): T.A.S.K. Resources' own browser and ZIM reader,
embedded in-process, filtered to medical resources by default.

* Resources index opened READ-ONLY (task-resources >= 0.2.2 Index(read_only=True)): no scan, no schema setup,
  no journal change, no history writes. ZIMs are only read (libzim). With task-resources 0.2.3 nothing is
  created next to the index: a verified private snapshot when Resources is closed, a live read-only connection
  when Resources is running (launcher 0.3.6: Refresh re-opens, so a snapshot is renewed).
* Failure paths close what they opened (no orphaned DB connection or reader).
* Bookmarks go to a private launcher file (~/.local/state/task-launcher/medical-bookmarks.json, 0600).
* One browser / one reader per launcher; reopening reuses it. Locking clears and hides the content.
* Reference only; no patient data.
"""

import logging

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from task_launcher import paths
from task_launcher.services import medical, resources_embed

log = logging.getLogger("task_launcher")
LIBRARY_TILE = "app:task.library"


class MedicalView(QWidget):
    view_name = "medical"

    def __init__(self, mw, loader=resources_embed.load, index_path=None):
        super().__init__()
        self.mw, self.loader, self.index_path = mw, loader, index_path
        self.setObjectName("medicalView")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.back_btn = QPushButton("‹ Back")
        self.back_btn.setAccessibleName("Back")
        self.home_btn = QPushButton("Home")
        self.back_btn.clicked.connect(mw.go_back)
        self.home_btn.clicked.connect(mw.go_home)
        self.heading = QLabel("Medical — offline reference")
        self.heading.setProperty("role", "heading")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.resources_btn = QPushButton("Open T.A.S.K. Resources")
        self.resources_btn.clicked.connect(self.open_resources)
        for w in (self.back_btn, self.home_btn):
            top.addWidget(w)
        top.addWidget(self.heading, 1)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.resources_btn)
        lay.addLayout(top)
        banner = QLabel(medical.DISCLAIMER + " Patient records are not part of T.A.S.K.")
        banner.setProperty("role", "warn")
        banner.setWordWrap(True)
        lay.addWidget(banner)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.hide()
        lay.addWidget(self.message)
        self.body = QVBoxLayout()
        lay.addLayout(self.body, 1)
        self.browser = self.library = None
        self.error = ""
        self.guard = None                       # one crash guard per launcher process (0.3.7)
        self._build_browser()

    # ------------------------------------------------------------------
    def _build_browser(self):
        try:
            tr = self.loader()
        except resources_embed.EmbedUnavailable as exc:
            return self._show_error(str(exc))
        from task_resources import classify, paths as rpaths, settings as rsettings
        from task_resources.library import Library
        from task_resources.ui.browser import JsonBookmarks, ResourceBrowser, Scope
        ip = self.index_path or rpaths.data_dir() / "index.sqlite"
        library = None
        try:
            library = Library(rsettings.load(), ip, read_only=True)
        except FileNotFoundError:
            return self._show_error("T.A.S.K. Resources has no index yet. Open T.A.S.K. Resources, add your "
                                    "library folders (or let it scan), then press Refresh here.")
        except Exception as exc:  # noqa: BLE001 - corrupt/newer index, permissions
            return self._show_error(f"The T.A.S.K. Resources index could not be read: {exc}")
        try:
            bm = JsonBookmarks(paths.state_dir() / "medical-bookmarks.json", library.index)
            scope = Scope("medical", "Medical", classify.medical_reason)
            if self.guard is None:
                self.guard = resources_embed.make_guard()
            if self.guard is not None:          # task-resources >= 0.2.4
                browser = ResourceBrowser(library, resources_embed.engine(), scope, bm, guard=self.guard)
            else:
                browser = ResourceBrowser(library, resources_embed.engine(), scope, bm)
        except Exception as exc:  # noqa: BLE001 - never leave a connection/snapshot open on failure
            self._close_library(library)
            log.exception("medical view: browser failed")
            return self._show_error(f"The Medical reader could not start: {exc}")
        self.library, self.browser = library, browser
        self.browser.status_cb = lambda t, ms=5000: self.mw.home.show_notice("info", t)
        self.body.addWidget(self.browser, 1)
        self.message.hide()
        self.error = ""
        self.browser.refresh()
        log.info("medical view: embedded T.A.S.K. Resources %s reader (read-only index)", tr.__version__)

    def _show_error(self, text):
        self.error = text
        self.message.setText(text)
        self.message.show()

    def refresh(self):
        """Re-open the index (a snapshot shows the index as of opening; a live view needs no re-open)."""
        ix = self.library.index if self.library is not None else None
        if self.browser is not None and getattr(ix, "ro_mode", None) == "snapshot" and not ix.ro_stale():
            self.browser.refresh()             # snapshot still current: keep the one reader
            return
        # stale snapshot, or a live connection (re-opened so it is never held longer than needed: while
        # Medical holds it, Resources is not the last connection and cannot remove its own -wal/-shm)
        self._teardown()
        self._build_browser()

    @staticmethod
    def _close_library(library):
        if library is not None:
            library.close()
            library.index.close()        # idempotent in task-resources >= 0.2.3

    def _teardown(self):
        b, lib = self.browser, self.library
        self.browser = self.library = None
        if b is not None:
            b.shutdown()
            self.body.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self._close_library(lib)

    def probes_updated(self):
        pass

    def lock_hide(self):
        """Lock privacy: drop what was on screen (open article, details, search hits)."""
        if self.browser is not None:
            self.browser.clear_for_lock()

    def shutdown(self):
        """Idempotent: stops the reader (WebEngine pages), closes the DB connection, removes the snapshot."""
        self._teardown()

    def _resources_tile(self):
        reg = getattr(self.mw, "registry", None)
        t = reg.get(LIBRARY_TILE) if reg is not None else None
        return t if t is not None and getattr(t, "argv", None) else None

    def open_resources(self):
        """Standalone T.A.S.K. Resources for managing the library (adding/scanning); reading stays here."""
        t = self._resources_tile()
        if t is None:
            self.mw.home.show_notice("error", "T.A.S.K. Resources is not installed.")
            return None
        return self.mw.activate(t)
