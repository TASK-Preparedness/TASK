# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Overlays tab: per-dataset toggles, search/filter, source information, user annotations and a
confirm-before-tune action. Reference data only. Nothing here transmits, and tuning is receive-only."""

import html

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTextBrowser, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from task_sdr import overlays as O


def fmt_hz(hz):
    return f"{hz / 1e6:.6f} MHz"


def describe(it):
    if it.kind == "marker":
        bw = f" (±{it.bandwidth_hz // 2 / 1e3:g} kHz)" if it.bandwidth_hz else ""
        return f"{fmt_hz(it.freq_hz)}{bw}"
    return f"{fmt_hz(it.start_hz)} – {fmt_hz(it.end_hz)}"


class _Bridge(QObject):
    loaded = Signal(object)


class OverlayPanel(QWidget):
    message = Signal(str)
    tuneRequested = Signal(object)       # emitted only after the user confirms; object = no 32-bit limit (Hz up to 6 GHz)
    changed = Signal()                   # toggles/data changed; the window refreshes the spectrum strip

    def __init__(self, dirs=None, toggles_path=None, user_dir=None, parent=None):
        super().__init__(parent)
        self.dirs, self.toggles_path, self.user_dir = dirs, toggles_path, user_dir
        self.set = O.OverlaySet()
        self.errors = []
        self.loading = False
        self.confirm = self._confirm_dialog          # replaceable (tests)
        self.ask_text = self._ask_text_dialog
        self._bridge = _Bridge()
        self._bridge.loaded.connect(self._on_loaded, Qt.ConnectionType.QueuedConnection)
        self._current_hz = None

        v = QVBoxLayout(self)
        self.note = QLabel(f"<b>{O.NOTE_NOT_ACTIVE}</b><br>{O.NOTE_NO_TX}")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.status = QLabel("Overlays not loaded.")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        h = QHBoxLayout()
        left = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Overlay", "Type", "Status"])
        self.tree.itemChanged.connect(self._toggled)
        self.tree.currentItemChanged.connect(lambda *_: self._show_info())
        left.addWidget(self.tree, 2)
        self.info = QTextBrowser()
        self.info.setOpenLinks(False)                # source URLs are shown as text; nothing is fetched
        self.info.setOpenExternalLinks(False)
        left.addWidget(self.info, 2)
        self.errors_lbl = QLabel("")
        self.errors_lbl.setWordWrap(True)
        self.errors_lbl.setTextFormat(Qt.TextFormat.PlainText)
        left.addWidget(self.errors_lbl)
        h.addLayout(left, 1)
        right = QVBoxLayout()
        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search label, reference, or a frequency (e.g. 162.55 MHz)")
        self.search.textChanged.connect(self.refresh_results)
        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", None)
        for t in O.TYPES:
            self.type_filter.addItem(O.TYPE_LABEL[t], t)
        self.type_filter.currentIndexChanged.connect(self.refresh_results)
        f.addWidget(self.search, 3)
        f.addWidget(self.type_filter, 1)
        right.addLayout(f)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _i: self.tune_selected())
        right.addWidget(self.results, 1)
        b = QHBoxLayout()
        self.tune_btn = QPushButton("Tune (receive only)…")
        self.tune_btn.clicked.connect(self.tune_selected)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self.reload)
        b.addWidget(self.tune_btn)
        b.addWidget(self.reload_btn)
        right.addLayout(b)
        u = QHBoxLayout()
        self.add_btn = QPushButton("Annotate current frequency…")
        self.add_btn.clicked.connect(self.annotate_current)
        self.edit_btn = QPushButton("Rename…")
        self.edit_btn.clicked.connect(self.rename_selected)
        self.del_btn = QPushButton("Remove")
        self.del_btn.clicked.connect(self.remove_selected)
        for w in (self.add_btn, self.edit_btn, self.del_btn):
            u.addWidget(w)
        right.addLayout(u)
        h.addLayout(right, 1)
        v.addLayout(h, 1)

    # ------------------------------------------------------------ loading (background thread)
    def reload(self):
        if self.loading:
            return None
        self.loading = True
        self.status.setText("Loading overlays…")
        return O.BackgroundLoader(self._bridge.loaded.emit, self.dirs).start()

    def _on_loaded(self, res):
        self.loading = False
        self.set = O.OverlaySet(res.datasets, O.load_toggles(self.toggles_path))
        self.errors = res.errors
        n = len(res.datasets)
        self.status.setText(f"{n} overlay(s) loaded; {len(res.errors)} file(s) rejected. Overlays start off.")
        self.errors_lbl.setText("\n".join(f"Rejected {p}: {why}" for p, why in res.errors))
        self._fill_tree()
        self.refresh_results()
        self.changed.emit()

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for d in sorted(self.set.datasets.values(), key=lambda d: (d.origin != "user", d.title.lower())):
            it = QTreeWidgetItem([d.title, O.TYPE_LABEL[d.type], ", ".join(s.upper() for s in d.status())])
            it.setData(0, Qt.ItemDataRole.UserRole, d.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if self.set.enabled(d.id) else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(it)
        self.tree.blockSignals(False)

    def _toggled(self, item, col):
        if col != 0:
            return
        ds_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.set.set_enabled(ds_id, item.checkState(0) == Qt.CheckState.Checked)
        try:
            O.save_toggles(self.set.toggles, self.toggles_path)
        except OSError as exc:
            self.message.emit(f"overlay toggles not saved: {exc}")
        self.refresh_results()
        self.changed.emit()

    def set_enabled(self, ds_id, on):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) == ds_id:
                it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                return
        raise KeyError(ds_id)

    # ------------------------------------------------------------ info / search
    def selected_dataset(self):
        it = self.tree.currentItem()
        return self.set.datasets.get(it.data(0, Qt.ItemDataRole.UserRole)) if it else None

    def info_html(self, d):
        e = html.escape
        s = d.source
        rows = [("Title", d.title), ("Type", O.TYPE_LABEL[d.type]), ("Version", d.version),
                ("Agency / source", s.get("agency", "")), ("Citation", s.get("citation", "")),
                ("Source URL (not opened)", s.get("url", "")),
                ("Publication date", d.publication_date or "—"), ("Retrieved", d.retrieved or "—"),
                ("Last verified", d.last_verified or "never (UNVERIFIED)"),
                ("Stale after", f"{d.stale_after_days} days"), ("Attribution", d.attribution or "—"),
                ("Origin", f"{d.origin}: {d.path}"), ("SHA-256", d.sha256), ("Entries", len(d.items)),
                ("Notes", d.notes or "—")]
        warn = []
        st = d.status()
        if "example" in st:
            warn.append("EXAMPLE DATA, for format demonstration only. Not real reference data.")
        if "unverified" in st:
            warn.append("UNVERIFIED: no one has checked this against its source.")
        if "stale" in st:
            warn.append(f"STALE: last verified {d.last_verified}, more than {d.stale_after_days} days ago.")
        body = "".join(f"<tr><td><b>{e(k)}</b></td><td>{e(str(v))}</td></tr>" for k, v in rows)
        w = "".join(f"<p style='color:#e8a33d'><b>{e(x)}</b></p>" for x in warn)
        return f"{w}<table>{body}</table><p><i>{e(O.NOTE_NOT_ACTIVE)} {e(O.NOTE_NO_TX)}</i></p>"

    def _show_info(self):
        d = self.selected_dataset()
        self.info.setHtml(self.info_html(d) if d else "")

    def refresh_results(self):
        t = self.type_filter.currentData()
        self.results.clear()
        for d, it in self.set.search(self.search.text(), types=(t,) if t else None):
            flags = d.status()
            tag = f" [{', '.join(x.upper() for x in flags)}]" if flags else ""
            row = QListWidgetItem(f"{it.label} | {describe(it)} | {d.title}{tag}")
            row.setData(Qt.ItemDataRole.UserRole, (d.id, d.items.index(it)))
            self.results.addItem(row)

    def selected_entry(self):
        r = self.results.currentItem()
        if r is None:
            return None
        ds_id, idx = r.data(Qt.ItemDataRole.UserRole)
        d = self.set.datasets[ds_id]
        return d, d.items[idx]

    # ------------------------------------------------------------ tune with confirmation
    def offer_tune(self, d, it):
        hz = it.tune_hz()
        text = (f"Tune the receiver to {fmt_hz(hz)}?\n\n{it.label} ({describe(it)})\nfrom {d.title} "
                f"[{', '.join(d.status()) or 'ok'}]\n\nReceive only. {O.NOTE_NOT_ACTIVE} The mode and "
                f"bandwidth stay as they are.")
        if not self.confirm(text):
            self.message.emit("Tune cancelled.")
            return False
        self.tuneRequested.emit(hz)
        return True

    def tune_selected(self):
        e = self.selected_entry()
        if e is None:
            self.message.emit("Select an overlay entry first.")
            return False
        return self.offer_tune(*e)

    def _confirm_dialog(self, text):
        return QMessageBox.question(self, "Tune (receive only)", text) == QMessageBox.StandardButton.Yes

    def _ask_text_dialog(self, title, prompt, default=""):
        t, ok = QInputDialog.getText(self, title, prompt, text=default)
        return t if ok else None

    # ------------------------------------------------------------ user annotations
    def set_current_hz(self, hz):
        self._current_hz = hz

    def _store(self):
        return O.UserAnnotations(self.user_dir)

    def _after_user_change(self):
        if O.USER_ID not in self.set.toggles:
            self.set.toggles[O.USER_ID] = True          # the user's own notes appear once created
            try:
                O.save_toggles(self.set.toggles, self.toggles_path)
            except OSError:
                pass
        return self.reload()

    def annotate_current(self):
        if self._current_hz is None:
            self.message.emit("No current frequency.")
            return None
        label = self.ask_text("Annotate", f"Label for {fmt_hz(self._current_hz)}:")
        if not label:
            return None
        try:
            self._store().add_marker(int(self._current_hz), label)
        except (O.OverlayError, OSError) as exc:
            self.message.emit(f"Annotation not saved: {exc}")
            return None
        return self._after_user_change()

    def _selected_user_index(self):
        e = self.selected_entry()
        if e is None or e[0].id != O.USER_ID or e[0].origin != "user":
            self.message.emit("Select one of your own annotations first.")
            return None
        return e[0].items.index(e[1])

    def rename_selected(self):
        idx = self._selected_user_index()
        if idx is None:
            return None
        label = self.ask_text("Rename", "New label:", self.set.datasets[O.USER_ID].items[idx].label)
        if not label:
            return None
        try:
            self._store().edit_label(idx, label)
        except (O.OverlayError, OSError) as exc:
            self.message.emit(f"Annotation not changed: {exc}")
            return None
        return self._after_user_change()

    def remove_selected(self):
        idx = self._selected_user_index()
        if idx is None:
            return None
        try:
            self._store().remove(idx)
        except (O.OverlayError, OSError) as exc:
            self.message.emit(f"Annotation not removed: {exc}")
            return None
        return self._after_user_change()
