# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""PDF viewing with QtPdf (python3-pyside6.qtpdf + qtpdfwidgets, optional). Read-only."""

import importlib

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


def qtpdf_available():
    try:
        importlib.import_module("PySide6.QtPdf")
        importlib.import_module("PySide6.QtPdfWidgets")
        return True, ""
    except (ImportError, OSError):
        return False, "PDF viewing needs python3-pyside6.qtpdf and python3-pyside6.qtpdfwidgets"


class PdfViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        ok, why = qtpdf_available()
        self.available = ok
        self.doc = self.view = None
        if not ok:
            self.label = QLabel(why)
            self.label.setWordWrap(True)
            lay.addWidget(self.label)
            return
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        self.doc = QPdfDocument(self)
        self.view = QPdfView(self)
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        lay.addWidget(self.view)

    def open(self, path):
        if not self.available:
            return False, self.label.text()
        from PySide6.QtPdf import QPdfDocument
        err = self.doc.load(str(path))
        if err != QPdfDocument.Error.None_:
            return False, f"PDF could not be opened ({err.name})"
        return True, f"{self.doc.pageCount()} pages"
