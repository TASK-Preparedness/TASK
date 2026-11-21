# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Edit metadata (stored as overrides in our index; the file is never changed) and categories."""

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QVBoxLayout)

from task_resources.index import EDITABLE


class EditDialog(QDialog):
    def __init__(self, resource, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit resource")
        self.r = resource
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<small>{resource['path']}</small><br><small>Changes are stored by T.A.S.K. "
                             "Resources only; the file itself is not modified.</small>"))
        form = QFormLayout()
        self.fields = {}
        for k in EDITABLE:
            w = QPlainTextEdit() if k in ("description", "notes") else QLineEdit()
            (w.setPlainText if isinstance(w, QPlainTextEdit) else w.setText)(resource.get(k) or "")
            self.fields[k] = w
            form.addRow(k.capitalize(), w)
        self.categories = QLineEdit(", ".join(resource.get("categories", [])))
        self.categories.setPlaceholderText("comma separated, e.g. Medical, Water")
        form.addRow("Categories", self.categories)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        out = {}
        for k, w in self.fields.items():
            out[k] = (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip()
        cats = [c.strip() for c in self.categories.text().split(",") if c.strip()]
        return out, cats

    def apply(self, index):
        vals, cats = self.values()
        for k, v in vals.items():
            original = self.r["extracted"].get(k, "") if k != "notes" else ""
            if v == original:
                index.clear_override(self.r["id"], k)
            else:
                index.set_override(self.r["id"], k, v)
        index.set_categories(self.r["id"], cats)
