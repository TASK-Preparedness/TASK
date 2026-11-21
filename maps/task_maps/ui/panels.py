# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Side panels: Maps (layers + import), Download, GPS, Waypoints & tracks."""

import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

from task_maps import tilemath as tm
from task_maps.downloader import human_bytes, human_eta
from task_maps.gpsd import MODE_TEXT
from task_maps.sources import download_permission


ZWSP = "\u200b"


def breakable(text: str) -> str:
    """Allow long URLs/paths to wrap inside narrow side panels (zero-width spaces after / and _)."""
    return re.sub(r"([/_])(?=\S)", "\\1" + ZWSP, text)


def _label(text="", role=None, wrap=True):
    lab = QLabel(breakable(text) if wrap else text)
    lab.setWordWrap(wrap)
    if wrap:
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lab.setMinimumWidth(120)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        lab.setProperty("role", role)
    return lab


def _list():
    w = QListWidget()
    w.setWordWrap(True)
    w.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    return w


def _heading(text):
    return _label(text, "heading", False)


class MapsPanel(QWidget):
    layerChosen = Signal(str)
    importRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_heading("Maps"))
        lay.addWidget(_label("Offline map files on this device. Choose one to display.", "muted"))
        self.list = _list()
        self.list.setMinimumHeight(160)
        self.list.itemActivated.connect(self._chosen)
        self.list.itemClicked.connect(self._chosen)
        lay.addWidget(self.list, 1)
        self.info = _label("", "muted")
        lay.addWidget(self.info)
        self.import_btn = QPushButton("Import MBTiles file…")
        self.import_btn.clicked.connect(self.importRequested)
        lay.addWidget(self.import_btn)
        lay.addWidget(_label("Import works without network: the file is checked, then copied into the data folder "
                             "(or linked, for large files on another disk).", "muted"))
        self.data_dir = _label("", "muted")
        lay.addWidget(self.data_dir)

    def set_layers(self, layers, current_path, data_dir):
        self.list.clear()
        for lay in layers:
            z = f"z{lay.minzoom}–{lay.maxzoom}" if lay.minzoom is not None else "no tiles yet"
            text = f"{lay.name}\n{lay.kind} · {lay.tiles:,} tiles · {z}" + (f"\nPROBLEM: {lay.problem}" if lay.problem else "")
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, lay.path)
            if lay.problem:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list.addItem(it)
            if lay.path == current_path:
                it.setSelected(True)
        self.info.setText("" if layers else "No map files yet. Use Download to save an area, or import an MBTiles file.")
        self.data_dir.setText(f"Data folder: {data_dir}")

    def _chosen(self, it):
        p = it.data(Qt.ItemDataRole.UserRole)
        if p:
            self.layerChosen.emit(p)


class DownloadPanel(QWidget):
    startRequested = Signal()
    pauseRequested = Signal()
    resumeRequested = Signal(int)
    cancelRequested = Signal(int)
    retryRequested = Signal(int)
    importRequested = Signal()
    clearRect = Signal()
    paramsChanged = Signal()
    keyRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_heading("Download Maps"))
        self.hint = _label("Drag on the map to draw the area. Drag the handles to adjust it, or drag inside to move it.",
                           "muted")
        lay.addWidget(self.hint)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(12)
        self.source.currentIndexChanged.connect(self.paramsChanged)
        form.addRow("Source", self.source)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Region name")
        self.name.setMaxLength(60)
        form.addRow("Name", self.name)
        zr = QHBoxLayout()
        self.minz = QSpinBox()
        self.maxz = QSpinBox()
        for sb in (self.minz, self.maxz):
            sb.setRange(0, 22)
            sb.valueChanged.connect(self.paramsChanged)
            zr.addWidget(sb)
        self.minz.setValue(8)
        self.maxz.setValue(13)
        form.addRow("Zoom min / max", zr)
        lay.addLayout(form)
        self.permission = _label("")
        lay.addWidget(self.permission)
        self.estimate = _label("Draw an area to see the tile count and size.", "muted")
        lay.addWidget(self.estimate)
        row = QHBoxLayout()
        self.start_btn = QPushButton("Download")
        self.start_btn.setProperty("role", "primary")
        self.start_btn.clicked.connect(self.startRequested)
        self.clear_btn = QPushButton("Clear area")
        self.clear_btn.clicked.connect(self.clearRect)
        row.addWidget(self.start_btn)
        row.addWidget(self.clear_btn)
        lay.addLayout(row)
        self.key_btn = QPushButton("API key…")
        self.key_btn.setToolTip("Store the API key for this source in ~/.config/task-maps/keys.toml (mode 0600)")
        self.key_btn.clicked.connect(self.keyRequested)
        self.key_btn.hide()
        lay.addWidget(self.key_btn)
        self.import_btn = QPushButton("Import MBTiles file instead…")
        self.import_btn.clicked.connect(self.importRequested)
        self.import_btn.hide()
        lay.addWidget(self.import_btn)

        box = QGroupBox("Progress")
        bl = QVBoxLayout(box)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        bl.addWidget(self.bar)
        self.progress = _label("No download running.", "muted")
        bl.addWidget(self.progress)
        pr = QGridLayout()
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.cancel_btn = QPushButton("Cancel")
        self.retry_btn = QPushButton("Retry failed")
        self.pause_btn.clicked.connect(self.pauseRequested)
        self.resume_btn.clicked.connect(lambda: self.resumeRequested.emit(self.selected_job() or -1))
        self.cancel_btn.clicked.connect(lambda: self.cancelRequested.emit(self.selected_job() or -1))
        self.retry_btn.clicked.connect(lambda: self.retryRequested.emit(self.selected_job() or -1))
        for i, b in enumerate((self.pause_btn, self.resume_btn, self.cancel_btn, self.retry_btn)):
            pr.addWidget(b, i // 2, i % 2)
        bl.addLayout(pr)
        lay.addWidget(box)
        lay.addWidget(_label("Downloads", "muted"))
        self.jobs = _list()
        self.jobs.setMinimumHeight(90)
        self.jobs.itemSelectionChanged.connect(self._sync_buttons)
        lay.addWidget(self.jobs, 1)
        self._running_id = None
        self._jobs = {}
        self._sync_buttons()

    def set_sources(self, sources, keys):
        cur = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        rows = [(s, download_permission(s, keys.get(s.id, ""))[0]) for s in sources]
        rows.sort(key=lambda r: not r[1])          # permitted sources first; refused ones stay visible
        for s, ok in rows:
            self.source.addItem(f"{s.name}" + ("" if ok else "  (download not permitted)"), s.id)
            self.source.setItemData(self.source.count() - 1, s.name, Qt.ItemDataRole.ToolTipRole)
        i = self.source.findData(cur)
        self.source.setCurrentIndex(i if i >= 0 else 0)
        self.source.blockSignals(False)

    def set_estimate(self, text, role="muted"):
        self.estimate.setText(breakable(text))
        self.estimate.setProperty("role", role)
        self.estimate.style().unpolish(self.estimate)
        self.estimate.style().polish(self.estimate)

    def set_permission(self, ok, text):
        self.permission.setText(breakable(("Download " if ok else "Not permitted: ") + text))
        self.permission.setProperty("role", "ok" if ok else "warn")
        self.permission.style().unpolish(self.permission)
        self.permission.style().polish(self.permission)
        self.import_btn.setVisible(not ok)

    def set_jobs(self, jobs, running_id):
        sel = self.selected_job()
        self._running_id = running_id
        self._jobs = {j.id: j for j in jobs}
        self.jobs.clear()
        for j in jobs:
            pct = 100.0 * j.cursor / j.total if j.total else 0
            it = QListWidgetItem(f"{j.name} — {j.state_text()} · {pct:.0f}% · {j.cursor:,}/{j.total:,} · "
                                 f"z{j.minz}–{j.maxz}" + (f" · {j.failed} failed" if j.failed else ""))
            it.setData(Qt.ItemDataRole.UserRole, j.id)
            self.jobs.addItem(it)
            if j.id == (sel or running_id):
                it.setSelected(True)
        self._sync_buttons()

    def selected_job(self):
        items = self.jobs.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else self._running_id

    def _sync_buttons(self):
        jid = self.selected_job()
        j = self._jobs.get(jid)
        running = j is not None and jid == self._running_id and j.state in ("running", "waiting-network")
        self.pause_btn.setEnabled(running)
        self.resume_btn.setEnabled(j is not None and j.state in ("paused", "paused-disk", "interrupted", "queued",
                                                                 "waiting-network") and not running)
        self.cancel_btn.setEnabled(j is not None and j.active)
        self.retry_btn.setEnabled(j is not None and not j.active and j.failed > 0)

    def show_progress(self, snap):
        total = max(1, snap["total"])
        self.bar.setValue(int(1000 * snap["finished"] / total))
        rate = f"{snap['rate']:.1f} tiles/s" if snap["rate"] else "— tiles/s"
        lines = [f"{snap['finished']:,} / {snap['total']:,} tiles · {rate} · ETA {human_eta(snap['eta'])}",
                 f"downloaded {snap['downloaded']:,} · already present {snap['skipped']:,} · failed {snap['failed']:,} · "
                 f"{human_bytes(snap['bytes'])}"]
        if snap.get("message"):
            lines.append(snap["message"])
        self.progress.setText(breakable("\n".join(lines)))


class GpsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_heading("GPS"))
        self.status = _label("", None)
        lay.addWidget(self.status)
        self.form = QFormLayout()
        self.fields = {}
        for k in ("Position", "Fix", "Satellites", "Speed", "Course", "Altitude", "Accuracy", "Time", "Source",
                  "rain-core"):
            v = _label("—")
            self.fields[k] = v
            self.form.addRow(k, v)
        lay.addLayout(self.form)
        self.note = _label("Position comes from gpsd on this device (127.0.0.1:2947), read-only. rain-core 0.2.1 "
                           "reports gps.position only as a capability and offers no position data.", "muted")
        lay.addWidget(self.note)
        lay.addStretch(1)

    def show_state(self, g, coord_style="decimal", core_text="—", now=None):
        now = time.monotonic() if now is None else now
        if g.connection != "connected":
            self.status.setText(g.fix_text(now))
            self.status.setProperty("role", "warn")
        elif not g.fix_fresh(now):
            self.status.setText("NO FIX" if not g.has_fix else "FIX LOST — last known position shown")
            self.status.setProperty("role", "error")
        else:
            self.status.setText(MODE_TEXT.get(g.mode, "fix").upper())
            self.status.setProperty("role", "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        f = self.fields
        f["Position"].setText(tm.fmt_coord(g.lat, g.lon, coord_style) if g.has_fix else "—")
        f["Fix"].setText(MODE_TEXT.get(g.mode, "—") if g.connection == "connected" else "—")
        if g.sats_used is None and g.sats_visible is None:
            f["Satellites"].setText("—")
        else:
            f["Satellites"].setText(f"{'—' if g.sats_used is None else g.sats_used} used / "
                                    f"{'—' if g.sats_visible is None else g.sats_visible} visible")
        f["Speed"].setText(f"{g.speed * 3.6:.1f} km/h ({g.speed * 1.943844:.1f} kn)" if g.speed is not None else "—")
        f["Course"].setText(f"{g.track:.0f}° true" if g.track is not None else "—")
        f["Altitude"].setText(f"{g.alt:.0f} m" if g.alt is not None else "—")
        parts = []
        if g.eph is not None:
            parts.append(f"eph {g.eph:.0f} m")
        if g.epx is not None:
            parts.append(f"epx {g.epx:.0f} m")
        if g.epy is not None:
            parts.append(f"epy {g.epy:.0f} m")
        f["Accuracy"].setText(" · ".join(parts) or "— (not reported)")
        f["Time"].setText(g.time or "—")
        dev = f" · {', '.join(g.devices)}" if g.devices else ""
        f["Source"].setText(f"gpsd {g.gpsd_version}{dev}".strip() if g.connection == "connected" else "gpsd (not connected)")
        f["rain-core"].setText(core_text)


class WaypointPanel(QWidget):
    addAtGps = Signal()
    addByClick = Signal(bool)
    renameRequested = Signal(str)
    editRequested = Signal(str)
    deleteRequested = Signal(str)
    gotoRequested = Signal(str)
    recordToggled = Signal(bool)
    importGpx = Signal()
    exportGpx = Signal()
    trackDelete = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_heading("Waypoints & tracks"))
        g = QGridLayout()
        self.at_gps = QPushButton("Add at GPS")
        self.by_click = QPushButton("Add by clicking map")
        self.by_click.setCheckable(True)
        self.at_gps.clicked.connect(self.addAtGps)
        self.by_click.toggled.connect(self.addByClick)
        g.addWidget(self.at_gps, 0, 0)
        g.addWidget(self.by_click, 0, 1)
        lay.addLayout(g)
        self.list = _list()
        self.list.setMinimumHeight(120)
        self.list.itemDoubleClicked.connect(lambda it: self.gotoRequested.emit(it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.list, 2)
        g2 = QGridLayout()
        self.rename_btn = QPushButton("Rename")
        self.edit_btn = QPushButton("Edit coordinates")
        self.delete_btn = QPushButton("Delete")
        self.goto_btn = QPushButton("Show on map")
        for i, (b, sig) in enumerate(((self.rename_btn, self.renameRequested), (self.edit_btn, self.editRequested),
                                      (self.delete_btn, self.deleteRequested), (self.goto_btn, self.gotoRequested))):
            b.clicked.connect(lambda _=False, s=sig: self._emit_sel(s))
            g2.addWidget(b, i // 2, i % 2)
        lay.addLayout(g2)
        lay.addWidget(_label("Tracks", "muted"))
        self.record = QPushButton("Start recording track")
        self.record.setCheckable(True)
        self.record.toggled.connect(self._record)
        lay.addWidget(self.record)
        self.tracks = _list()
        self.tracks.setMinimumHeight(70)
        lay.addWidget(self.tracks, 1)
        self.track_del = QPushButton("Delete track")
        self.track_del.clicked.connect(self._del_track)
        lay.addWidget(self.track_del)
        g3 = QHBoxLayout()
        self.imp = QPushButton("Import GPX…")
        self.exp = QPushButton("Export GPX…")
        self.imp.clicked.connect(self.importGpx)
        self.exp.clicked.connect(self.exportGpx)
        g3.addWidget(self.imp)
        g3.addWidget(self.exp)
        lay.addLayout(g3)

    def _record(self, on):
        self.record.setText("Stop recording" if on else "Start recording track")
        self.recordToggled.emit(on)

    def _emit_sel(self, sig):
        it = self.list.currentItem()
        if it:
            sig.emit(it.data(Qt.ItemDataRole.UserRole))

    def _del_track(self):
        it = self.tracks.currentItem()
        if it:
            self.trackDelete.emit(it.data(Qt.ItemDataRole.UserRole))

    def set_data(self, waypoints, tracks, coord_style="decimal"):
        cur = self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None
        self.list.clear()
        for w in waypoints:
            it = QListWidgetItem(f"{w.name}\n{tm.fmt_coord(w.lat, w.lon, coord_style)} · {w.source}")
            it.setData(Qt.ItemDataRole.UserRole, w.id)
            self.list.addItem(it)
            if w.id == cur:
                self.list.setCurrentItem(it)
        self.tracks.clear()
        for t in tracks:
            km = t.length_m() / 1000
            it = QListWidgetItem(f"{t.name}{' (recording)' if t.recording else ''} · {len(t.points)} points · {km:.2f} km")
            it.setData(Qt.ItemDataRole.UserRole, t.id)
            self.tracks.addItem(it)
