# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Add Resource dialog: A Import from Pi, B Download from Website, C Online ZIM Catalog (Phase 4E).

B and C are live when the dialog gets a DownloadManager + Catalog (the main window always passes them);
without them (embedding/tests) the disabled placeholders below are shown and nothing is contacted."""

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QProgressBar, QPushButton,
                               QTabWidget, QTableWidget, QVBoxLayout, QWidget)

PHASE_4E = "Downloads are not available in this window"


class ImportTab(QWidget):
    def __init__(self, categories, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Choose files or folders on this Pi (ZIM, PDF, EPUB, TXT, Markdown, HTML, ODT, "
                             "DOCX). They are registered where they are; nothing is moved or changed."))
        self.files = QListWidget()
        lay.addWidget(self.files)
        row = QHBoxLayout()
        self.add_files = QPushButton("Add files…")
        self.add_folder = QPushButton("Add folder…")
        self.clear = QPushButton("Clear")
        for b in (self.add_files, self.add_folder, self.clear):
            b.setMinimumHeight(40)
            row.addWidget(b)
        lay.addLayout(row)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + list(categories))
        self.title = QLineEdit()
        self.title.setPlaceholderText("(optional) overrides the title read from the file")
        self.description = QLineEdit()
        self.managed = QCheckBox("Copy into managed storage (otherwise registered in place)")
        self.allow_dup = QCheckBox("Add even if it is a duplicate")
        form.addRow("Category", self.category)
        form.addRow("Title", self.title)
        form.addRow("Description", self.description)
        lay.addLayout(form)
        lay.addWidget(self.managed)
        lay.addWidget(self.allow_dup)
        self.add_files.clicked.connect(self._pick_files)
        self.add_folder.clicked.connect(self._pick_folder)
        self.clear.clicked.connect(self.files.clear)

    def _pick_files(self):
        names, _ = QFileDialog.getOpenFileNames(self, "Add files", "/library")
        self.files.addItems(names)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder", "/library")
        if d:
            self.files.addItem(d)

    def paths(self):
        return [self.files.item(i).text() for i in range(self.files.count())]


class DisabledDownloadTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.notice = QLabel(f"<b>{PHASE_4E}.</b> Downloading a website page or a document URL into managed "
                             "storage needs the download manager, which this window was opened without. "
                             "These controls are disabled.")
        self.notice.setWordWrap(True)
        lay.addWidget(self.notice)
        form = QFormLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://… (website or direct document link)")
        self.category = QComboBox()
        self.format = QComboBox()
        self.format.addItems(["Keep original format", "PDF", "EPUB", "ZIM"])
        form.addRow("Address", self.url)
        form.addRow("Category", self.category)
        form.addRow("Format", self.format)
        lay.addLayout(form)
        self.progress = QProgressBar()
        self.free = QLabel("Free space: —")
        self.start = QPushButton(f"Download ({PHASE_4E})")
        lay.addWidget(self.progress)
        lay.addWidget(self.free)
        lay.addWidget(self.start)
        for w in (self.url, self.category, self.format, self.progress, self.start):
            w.setEnabled(False)
            w.setToolTip(PHASE_4E)


class DisabledCatalogTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.notice = QLabel(f"<b>{PHASE_4E}.</b> Searching Kiwix-compatible online catalogs (descriptions, "
                             "sizes) needs the download manager, which this window was opened without. "
                             "These controls are disabled; nothing is contacted.")
        self.notice.setWordWrap(True)
        lay.addWidget(self.notice)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search the catalog")
        self.search = QPushButton(f"Search ({PHASE_4E})")
        row.addWidget(self.query)
        row.addWidget(self.search)
        lay.addLayout(row)
        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Title", "Language", "Size", "Description"])
        lay.addWidget(self.results)
        self.download = QPushButton(f"Download and verify ({PHASE_4E})")
        lay.addWidget(self.download)
        for w in (self.query, self.search, self.results, self.download):
            w.setEnabled(False)
            w.setToolTip(PHASE_4E)


class AddResourceDialog(QDialog):
    def __init__(self, categories, parent=None, manager=None, catalog=None, jobs=None, index=None):
        super().__init__(parent)
        self.setWindowTitle("Add Resource")
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tab_import = ImportTab(categories)
        if manager is not None and catalog is not None:
            from task_resources.ui.downloads_ui import CatalogTab, DownloadTab
            self.tab_download = DownloadTab(manager, jobs, categories)
            self.tab_catalog = CatalogTab(catalog, manager, jobs, index or manager.index)
        else:
            self.tab_download = DisabledDownloadTab()
            self.tab_catalog = DisabledCatalogTab()
        self.tabs.addTab(self.tab_import, "Import from Pi")
        self.tabs.addTab(self.tab_download, "Download from Website")
        self.tabs.addTab(self.tab_catalog, "Online ZIM Catalog")
        lay.addWidget(self.tabs)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def request(self):
        t = self.tab_import
        cat = t.category.currentText().strip()
        return {"paths": t.paths(), "categories": [cat] if cat else [],
                "overrides": {"title": t.title.text().strip(), "description": t.description.text().strip()},
                "managed_copy": t.managed.isChecked(), "allow_duplicate": t.allow_dup.isChecked()}
