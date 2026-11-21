# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. Maps & GPS main window."""

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QScrollArea,
                               QSpinBox, QStackedWidget, QStatusBar, QToolBar, QToolButton, QVBoxLayout, QWidget)

from task_maps import APP_NAME, PRODUCT, __version__, core, gpx, layers, net, online, overlays, sources
from task_maps import settings as settings_mod
from task_maps import tilemath as tm
from task_maps.downloader import JobManager, human_bytes, human_eta
from task_maps.gpsd import GpsdClient, GpsState
from task_maps.jobs import DuplicateJob
from task_maps.ui.map_view import MapView
from task_maps.ui.panels import DownloadPanel, GpsPanel, MapsPanel, WaypointPanel
from task_maps.ui.theme import stylesheet
from task_maps.ui.tiles import TileLoader
from task_maps.waypoints import Store, TrackFilter, TrackPoint

def _alive(fn):
    """Skip queued GUI-thread callbacks that arrive after shutdown (stores are closed then)."""
    def wrapper(self, *a):
        if getattr(self, "_shut", False):
            return None
        return fn(self, *a)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


PANEL_W = 380
PANEL_W_COMPACT = 330


class Bridge(QObject):
    """Marshals callbacks from background threads onto the GUI thread (queued signals)."""
    progress = Signal(dict)
    state = Signal(int, str, str)
    tiles = Signal(str, list)
    diskFull = Signal(str)
    gps = Signal(object)
    core = Signal(object, str)
    estimate = Signal(int, dict)
    imported = Signal(str, str)     # path, error
    network = Signal(bool, str)     # online?, message


class Dialogs:
    """User prompts; replaced by a scripted object in tests."""

    def __init__(self, parent):
        self.parent = parent

    def confirm(self, title, text):
        return QMessageBox.question(self.parent, title, text) == QMessageBox.StandardButton.Yes

    def inform(self, title, text):
        QMessageBox.information(self.parent, title, text)

    def open_file(self, title, filt):
        p, _ = QFileDialog.getOpenFileName(self.parent, title, str(Path.home()), filt)
        return p

    def save_file(self, title, name, filt):
        p, _ = QFileDialog.getSaveFileName(self.parent, title, str(Path.home() / name), filt,
                                           options=QFileDialog.Option.DontConfirmOverwrite)
        return p

    def secret(self, title, label):
        v, ok = QInputDialog.getText(self.parent, title, label, QLineEdit.EchoMode.Password)
        return v if ok else None

    def text(self, title, label, value=""):
        v, ok = QInputDialog.getText(self.parent, title, label, QLineEdit.EchoMode.Normal, value)
        return v if ok else None


class SettingsDialog(QDialog):
    def __init__(self, s: settings_mod.Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.data_dir = QLineEdit(s.data_dir)
        self.data_dir.setPlaceholderText(str(settings_mod.paths.default_data_dir()))
        form.addRow("Data folder", self.data_dir)
        self.coord = QComboBox()
        self.coord.addItem("Decimal degrees", "decimal")
        self.coord.addItem("Degrees minutes seconds", "dms")
        self.coord.setCurrentIndex(0 if s.coord_format == "decimal" else 1)
        form.addRow("Coordinates", self.coord)
        self.cache = QSpinBox()
        self.cache.setRange(64, 8192)
        self.cache.setValue(s.cache_tiles)
        form.addRow("Tile cache (tiles in memory)", self.cache)
        self.contact = QLineEdit(s.ua_contact)
        self.contact.setPlaceholderText("optional contact for the User-Agent")
        form.addRow("Download contact", self.contact)
        lay.addLayout(form)
        note = QLabel("Changing the data folder takes effect after restarting task-maps. Existing maps are not moved "
                      "or deleted; point it at e.g. an NVMe mount to store maps there.")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self, s):
        d = self.data_dir.text().strip()
        s.data_dir = d if d.startswith("/") else ""
        s.coord_format = self.coord.currentData()
        s.cache_tiles = self.cache.value()
        s.ua_contact = self.contact.text().strip()[:120]


class MainWindow(QMainWindow):
    def __init__(self, settings=None, data_dir=None, gpsd_factory=None, core_fn=core.gps_capability, fetch=net.fetch,
                 dialogs=None, catalog=None, start_gps=True, engine_kwargs=None, free_space=None, reserve_bytes=None):
        super().__init__()
        self.settings = settings or settings_mod.load()
        self.data_dir = Path(data_dir) if data_dir else self.settings.resolved_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.dialogs = dialogs or Dialogs(self)
        self.bridge = Bridge()
        self.setWindowTitle(f"{APP_NAME} — {PRODUCT}")
        self.catalog = catalog or sources.load()
        self.keys = sources.load_keys()
        kw = {}
        if reserve_bytes is not None:
            kw["reserve_bytes"] = reserve_bytes
        self.manager = JobManager(self.data_dir, self.catalog, self.keys, ua=net.user_agent(self.settings.ua_contact),
                                  fetch=fetch, engine_kwargs=engine_kwargs, free_space=free_space, **kw)
        self.manager.on_progress = self.bridge.progress.emit
        self.manager.on_state = self.bridge.state.emit
        self.manager.on_tiles = self.bridge.tiles.emit
        self.manager.on_disk_full = self.bridge.diskFull.emit
        self.store = Store(self.data_dir / "waypoints.sqlite")
        self.track_filter = TrackFilter()
        self.recording = self.store.recording_track()
        self.gps_state = GpsState(connection="connecting")
        self.core_text = "checking…"
        self.layers = []
        self.add_by_click = False
        self._est_seq = 0

        self._fetch = fetch
        self.providers = {}
        self.feeds_dir = None             # tests may point overlays elsewhere
        self.loader = TileLoader(2, self)
        self.view = MapView(self.loader, self.settings.cache_tiles)
        self.view.coord_style = self.settings.coord_format
        lat, lon, z = self.settings.view
        self.view.set_view(lat, lon, z)

        self.maps_panel = MapsPanel()
        self.dl_panel = DownloadPanel()
        self.gps_panel = GpsPanel()
        self.wpt_panel = WaypointPanel()
        self.stack = QStackedWidget()
        for w in (self.maps_panel, self.dl_panel, self.gps_panel, self.wpt_panel):
            self.stack.addWidget(w)
        self.side = QScrollArea()
        self.side.setWidget(self.stack)
        self.side.setWidgetResizable(True)
        self.side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side.setFixedWidth(PANEL_W)
        self.side.hide()
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self.view, 1)
        h.addWidget(self.side)
        self.setCentralWidget(central)
        self._build_toolbar()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.coord_label = QLabel("—")
        self.zoom_label = QLabel("")
        self.gps_label = QLabel("")
        self.oz_label = QLabel("")
        self.oz_label.setProperty("role", "warn")
        self.coord_label.setMinimumWidth(200)
        self.status.addWidget(self.coord_label)
        self.status.addWidget(self.zoom_label)
        self.status.addWidget(self.oz_label, 1)
        self.status.addPermanentWidget(self.gps_label)

        self.net_label = QLabel("")
        self.status.addPermanentWidget(self.net_label)
        self._add_online_controls()
        self._wire()
        self.bridge.network.connect(self._on_network)
        self.refresh_layers(select=self._initial_layer())
        self.refresh_sources()
        self.refresh_jobs()
        self.refresh_waypoints()
        self.apply_compact()

        self._gps_timer = QTimer(self)
        self._gps_timer.setInterval(1000)
        self._gps_timer.timeout.connect(lambda: self._on_gps(self.gps_state))
        self._gps_timer.start()
        self.gpsd = None
        if start_gps:
            factory = gpsd_factory or (lambda cb: GpsdClient(port=self.settings.gpsd_port, on_update=cb))
            self.gpsd = factory(self.bridge.gps.emit)
            self.gpsd.start()
        self._core_fn = core_fn
        threading.Thread(target=self._core_probe, name="core-gps-capability", daemon=True).start()
        QTimer.singleShot(0, self.check_interrupted)
        self._overlay_timer = QTimer(self)
        self._overlay_timer.setInterval(5000)
        self._overlay_timer.timeout.connect(self.refresh_overlays)
        self._overlay_timer.start()
        self._absent_timer = QTimer(self)          # retry failed/busy online tiles every 30 s
        self._absent_timer.setInterval(30000)
        self._absent_timer.timeout.connect(lambda: self.view.network_changed(True))
        self._absent_timer.start()
        self.refresh_overlays()

    # ------------------------------------------------------------ construction
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.tool = {}

        def btn(key, text, tip, checkable=False, slot=None):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if slot:
                b.clicked.connect(slot)
            tb.addWidget(b)
            self.tool[key] = b
            return b

        btn("maps", "Maps", "Offline map files and import", True, lambda c: self.show_panel("maps", c))
        btn("download", "Download", "Download Maps mode: draw an area and download it", True,
            lambda c: self.show_panel("download", c))
        btn("gps", "GPS", "GPS status", True, lambda c: self.show_panel("gps", c))
        btn("waypoints", "Waypoints", "Waypoints and tracks", True, lambda c: self.show_panel("waypoints", c))
        tb.addSeparator()
        btn("center", "Center", "Center the map on the GPS position", False, self.center_on_gps)
        btn("follow", "Follow", "Keep the map centred on the GPS position", True, self.set_follow)
        btn("zoomin", "+", "Zoom in", False, lambda: self.view.zoom_at(round(self.view.zoom) + 1))
        btn("zoomout", "−", "Zoom out", False, lambda: self.view.zoom_at(round(self.view.zoom) - 1))
        btn("settings", "Settings", "Settings", False, self.open_settings)
        self.tool["follow"].setChecked(self.settings.follow)

    def _wire(self):
        b = self.bridge
        b.progress.connect(self._on_progress)
        b.state.connect(self._on_job_state)
        b.tiles.connect(self._on_tiles)
        b.diskFull.connect(self._on_disk_full)
        b.gps.connect(self._on_gps)
        b.core.connect(self._on_core)
        b.estimate.connect(self._on_estimate)
        b.imported.connect(self._on_imported)
        v = self.view
        v.cursorMoved.connect(self._on_cursor)
        v.viewChanged.connect(self._on_view_changed)
        v.mapClicked.connect(self._on_map_click)
        v.rectChanged.connect(self.update_estimate)
        v.userPanned.connect(lambda: self.set_follow(False))
        v.overzoomChanged.connect(self.oz_label.setText)
        mp = self.maps_panel
        mp.layerChosen.connect(self.select_layer)
        mp.importRequested.connect(self.import_mbtiles)
        d = self.dl_panel
        d.startRequested.connect(self.start_download)
        d.pauseRequested.connect(self.manager_pause)
        d.resumeRequested.connect(self.resume_job)
        d.cancelRequested.connect(self.cancel_job)
        d.retryRequested.connect(self.retry_job)
        d.importRequested.connect(self.import_mbtiles)
        d.clearRect.connect(self.clear_rect)
        d.paramsChanged.connect(self.update_estimate)
        d.keyRequested.connect(self.set_api_key)
        w = self.wpt_panel
        w.addAtGps.connect(self.add_waypoint_at_gps)
        w.addByClick.connect(self._set_add_by_click)
        w.renameRequested.connect(self.rename_waypoint)
        w.editRequested.connect(self.edit_waypoint)
        w.deleteRequested.connect(self.delete_waypoint)
        w.gotoRequested.connect(self.goto_waypoint)
        w.recordToggled.connect(self.set_recording)
        w.importGpx.connect(self.import_gpx)
        w.exportGpx.connect(self.export_gpx)
        w.trackDelete.connect(self.delete_track)
        if self.recording:
            w.record.blockSignals(True)
            w.record.setChecked(True)
            w.record.setText("Stop recording")
            w.record.blockSignals(False)

    # ------------------------------------------------------------ layout
    def compact(self):
        return self.width() < 1280 or self.height() < 720

    def apply_compact(self):
        c = self.compact()
        self.setStyleSheet(stylesheet(c))
        self.side.setFixedWidth(PANEL_W_COMPACT if c else PANEL_W)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.apply_compact()

    def show_panel(self, key, on=True):
        idx = {"maps": 0, "download": 1, "gps": 2, "waypoints": 3}[key]
        for k in ("maps", "download", "gps", "waypoints"):
            self.tool[k].setChecked(on and k == key)
        if on:
            self.stack.setCurrentIndex(idx)
            self.side.show()
        else:
            self.side.hide()
        self.view.download_mode = on and key == "download"
        if not self.view.download_mode:
            self.view.unsetCursor()
        self.view.update()
        if self.view.download_mode:
            self.update_estimate()

    # ------------------------------------------------------------ 0.1.1 online layers + overlays
    def online_sources(self):
        if not self.settings.online_auto:
            return []
        out = []
        for src in self.catalog.ordered():
            ok, _ = sources.download_permission(src, self.keys.get(src.id, ""))
            if ok and not src.api_key_required:
                out.append(src)
        return out

    def online_layers(self):
        return [layers.Layer(online.layer_path(s.id), f"{s.name} — online + offline", "online", s.attribution[:300],
                             s.min_zoom, s.max_zoom) for s in self.online_sources()]

    def _initial_layer(self):
        """0.1.0 saved layer is kept. A saved manual-region file of a permitted source (e.g. the Pennsylvania USGS
        downloads) is shown through that source's online layer, which reads the same file first, read-only."""
        saved = self.settings.layer
        for s in self.online_sources():
            if not saved or saved == str(self.data_dir / "maps" / f"{s.id}.mbtiles") or saved == online.layer_path(s.id):
                return online.layer_path(s.id)
        return saved

    def _provider(self, path):
        prov = self.providers.get(path)
        if prov is None:
            sid = path[len(online.PREFIX):]
            src = self.catalog.sources.get(sid)
            if src is None:
                return None
            try:
                prov = online.OnlineSource(src, self.data_dir, fetch=self._fetch,
                                           ua=net.user_agent(self.settings.ua_contact),
                                           cache_bytes=self.settings.cache_mb * 1024 * 1024,
                                           on_network=self.bridge.network.emit, api_key=self.keys.get(sid, ""))
            except (sources.SourceError, OSError) as exc:
                self.status.showMessage(str(exc), 15000)
                return None
            self.providers[path] = prov
            self.loader.add_provider(prov)
        return prov

    def _on_network(self, is_online, msg):
        self.net_label.setText("Online" if is_online else "Offline — showing saved tiles")
        self.view.network_changed(is_online)

    def _add_online_controls(self):
        lay = self.maps_panel.layout()
        self.overlay_boxes = {}
        for key, label in (("aprs", "APRS positions"), ("mesh", "Mesh node positions"), ("gmrs", "GMRS positions")):
            cb = QCheckBox(label)
            cb.setChecked(bool(self.settings.overlays.get(key)))
            cb.toggled.connect(lambda on, k=key: self._toggle_overlay(k, on))
            lay.addWidget(cb)
            self.overlay_boxes[key] = cb
        from PySide6.QtWidgets import QPushButton
        self.clear_cache_btn = QPushButton("Clear automatic tile cache")
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        lay.addWidget(self.clear_cache_btn)
        from task_maps.ui.panels import _label
        lay.addWidget(_label("Overlays come from T.A.S.K. APRS / Mesh on this device (read-only). The cache never "
                             "contains your downloaded regions or imported files.", "muted"))

    def _toggle_overlay(self, key, on):
        self.settings.overlays[key] = on
        self._save_settings()
        self.refresh_overlays()

    def refresh_overlays(self):
        try:
            data = overlays.read_all(self.feeds_dir)
        except Exception:   # noqa: BLE001 — a bad feed only empties overlays
            data = {}
        self.view.set_overlays(data, self.settings.overlays)

    def clear_cache(self):
        if not self.dialogs.confirm("Clear cache", "Delete automatically cached tiles? Downloaded regions and "
                                                   "imported maps are not affected."):
            return
        for prov in self.providers.values():
            prov.cache.clear()
        self.view.cache.clear()
        self.view.update()

    # ------------------------------------------------------------ layers
    def refresh_layers(self, select=None):
        self.layers = self.online_layers() + [lay for lay in layers.scan(self.data_dir)]
        if select and online.is_online(select):
            self._provider(select)
        cur = select or (self.view.layer.path if self.view.layer else "")
        chosen = next((lay for lay in self.layers if lay.path == cur and not lay.problem), None)
        if chosen is None:
            chosen = next((lay for lay in self.layers if not lay.problem and lay.tiles), None)
        if chosen is not None and (self.view.layer is None or self.view.layer.path != chosen.path):
            self.view.set_layer(chosen)
            self.view.failed = self.manager.failed_tiles_for(chosen.path)
        self.maps_panel.set_layers(self.layers, self.view.layer.path if self.view.layer else "", self.data_dir)

    def select_layer(self, path):
        lay = next((x for x in self.layers if x.path == path), None)
        if lay and lay.kind == "online" and self._provider(path) is None:
            return
        if lay and not lay.problem:
            self.view.set_layer(lay)
            self.view.failed = self.manager.failed_tiles_for(path)
            self.settings.layer = path
            self._save_settings()
            if lay.bounds and not self._view_overlaps(lay.bounds):
                w, s, e, n = lay.bounds
                self.view.set_view((s + n) / 2, (w + e) / 2, max(lay.minzoom or 0, min(self.view.zoom, lay.maxzoom or 0)))

    def _view_overlaps(self, b):
        v = self.view.visible_bbox()
        return not (b[2] < v.west or b[0] > v.east or b[3] < v.south or b[1] > v.north)

    def import_mbtiles(self):
        path = self.dialogs.open_file("Import MBTiles map", "MBTiles (*.mbtiles);;All files (*)")
        if not path:
            return
        link = False
        try:
            size = Path(path).stat().st_size
        except OSError as exc:
            self.dialogs.inform("Import", f"Cannot read the file: {exc}")
            return
        if size > 2 * 1024 ** 3:
            link = self.dialogs.confirm("Import", f"The file is {human_bytes(size)}. Link it in place instead of copying "
                                        "(keep the original file where it is)?")

        def work():
            try:
                dest = layers.import_mbtiles(path, self.data_dir, link=link)
                self.bridge.imported.emit(str(dest), "")
            except (ValueError, OSError) as exc:
                self.bridge.imported.emit("", str(exc))

        self.status.showMessage("Checking and importing the map file…")
        threading.Thread(target=work, name="mbtiles-import", daemon=True).start()

    @_alive
    def _on_imported(self, dest, err):
        if err:
            self.dialogs.inform("Import failed", err)
            self.status.showMessage("Import failed", 5000)
            return
        self.status.showMessage(f"Imported {Path(dest).name}", 5000)
        self.refresh_layers(select=dest)
        self.select_layer(dest)

    # ------------------------------------------------------------ download
    def refresh_sources(self):
        self.dl_panel.set_sources(self.catalog.ordered(), self.keys)
        self.update_estimate()

    def current_source(self):
        return self.catalog.sources.get(self.dl_panel.source.currentData())

    def update_estimate(self):
        src = self.current_source()
        d = self.dl_panel
        if src is None:
            d.set_permission(False, "no tile sources are defined")
            d.start_btn.setEnabled(False)
            return
        ok, why = sources.download_permission(src, self.keys.get(src.id, ""))
        d.set_permission(ok, why + (f" · {src.coverage}" if src.coverage else ""))
        d.key_btn.setVisible(src.api_key_required)
        for sb in (d.minz, d.maxz):
            sb.blockSignals(True)
            sb.setRange(src.min_zoom, src.max_zoom)
            sb.blockSignals(False)
        bbox = self.view.rect_bbox()
        if bbox is None:
            d.set_estimate("Draw an area on the map to see the tile count and size.")
            d.start_btn.setEnabled(False)
            return
        minz, maxz = d.minz.value(), d.maxz.value()
        if minz > maxz:
            d.set_estimate("Minimum zoom is above maximum zoom.", "warn")
            d.start_btn.setEnabled(False)
            return
        self._est_seq += 1
        seq = self._est_seq

        def work():
            est = self.manager.estimate(src, bbox, minz, maxz)
            self.bridge.estimate.emit(seq, est)

        threading.Thread(target=work, name="estimate", daemon=True).start()
        self._est_ctx = (src, ok)

    @_alive
    def _on_estimate(self, seq, est):
        if seq != self._est_seq:
            return
        src, ok = self._est_ctx
        d = self.dl_panel
        lines = [f"{est['tiles']:,} tiles · about {human_bytes(est['bytes'])}",
                 f"Storage needed ≈ {human_bytes(est['required'])} (+{human_bytes(est['reserve'])} reserve); "
                 f"free in {self.manager.maps_dir}: {human_bytes(est['free'])}"]
        role, can = "muted", ok
        if est["tiles"] > src.max_tiles_per_job:
            lines.append(f"Too many tiles for this source (limit {src.max_tiles_per_job:,} per download).")
            role, can = "warn", False
        if not est["fits"]:
            lines.append("Not enough free space for this download.")
            role, can = "error", False
        if ok and src.rate_limit and est["tiles"]:
            lines.append(f"At {src.rate_limit:g} requests/s this takes at least "
                         f"{human_eta(est['tiles'] / src.rate_limit)}.")
        d.set_estimate("\n".join(lines), role)
        d.start_btn.setEnabled(can and est["tiles"] > 0)
        self.last_estimate = est

    def set_api_key(self):
        src = self.current_source()
        if src is None or not src.api_key_required:
            return
        key = self.dialogs.secret(f"API key for {src.name}", "API key (stored only in ~/.config/task-maps/keys.toml)")
        if key is None:
            return
        try:
            sources.save_key(src.id, key.strip())
        except (OSError, ValueError) as exc:
            self.dialogs.inform("API key", f"Could not save the key: {exc}")
            return
        self.keys = sources.load_keys()
        self.manager.keys = self.keys
        self.refresh_sources()

    def clear_rect(self):
        self.view.rect = None
        self.view.update()
        self.update_estimate()

    def start_download(self):
        src = self.current_source()
        bbox = self.view.rect_bbox()
        if src is None or bbox is None:
            return
        name = self.dl_panel.name.text().strip() or f"{src.name} area"
        try:
            job = self.manager.create_job(src.id, name, bbox, self.dl_panel.minz.value(), self.dl_panel.maxz.value())
        except (PermissionError, ValueError, OSError, DuplicateJob) as exc:
            self.dialogs.inform("Cannot start the download", str(exc))
            return
        try:
            self.manager.start(job.id)
        except RuntimeError as exc:
            self.dialogs.inform("Download queued", f"{exc}. The new download is saved as queued.")
        self.refresh_layers(select=str(self.manager.map_path(src.id)))
        self.select_layer(str(self.manager.map_path(src.id)))
        self._update_pending()
        self.refresh_jobs()

    def manager_pause(self):
        self.manager.pause()
        self.refresh_jobs()

    def resume_job(self, job_id):
        if job_id is None or job_id < 0:
            return
        try:
            self.manager.resume(job_id)
        except RuntimeError as exc:
            self.dialogs.inform("Cannot resume", str(exc))
        self._update_pending()
        self.refresh_jobs()

    def cancel_job(self, job_id):
        if job_id is None or job_id < 0:
            return
        if not self.dialogs.confirm("Cancel download", "Cancel this download? Tiles already downloaded stay on the device."):
            return
        self.manager.cancel(job_id)
        self._update_pending()
        self.refresh_jobs()

    def retry_job(self, job_id):
        if job_id is None or job_id < 0:
            return
        try:
            self.manager.retry_failed(job_id)
        except RuntimeError as exc:
            self.dialogs.inform("Cannot retry", str(exc))
        self._update_pending()
        self.refresh_jobs()

    def refresh_jobs(self):
        run = self.manager.running_job()
        self.dl_panel.set_jobs(self.manager.store.list(), run.id if run else None)

    def _update_pending(self):
        run = self.manager.running_job()
        if run and self.view.layer and run.map_path == self.view.layer.path:
            self.view.pending_region = (run.bbox, run.minz, run.maxz)
        else:
            self.view.pending_region = None
        self.view.update()

    @_alive
    def _on_progress(self, snap):
        self.dl_panel.show_progress(snap)
        now = time.monotonic()
        if now - getattr(self, "_jobs_refreshed", 0.0) >= 1.0:
            self._jobs_refreshed = now
            self.refresh_jobs()

    @_alive
    def _on_job_state(self, job_id, state, message):
        self.refresh_jobs()
        self._update_pending()
        if state in ("completed", "completed-with-errors", "cancelled"):
            self.refresh_layers()
            if self.view.layer:
                self.view.failed = self.manager.failed_tiles_for(self.view.layer.path)
            self.status.showMessage(f"Download {state.replace('-', ' ')}" + (f": {message}" if message else ""), 8000)
        elif state == "paused-disk":
            self.status.showMessage(message, 15000)

    @_alive
    def _on_disk_full(self, msg):
        self.status.showMessage(msg, 20000)

    @_alive
    def _on_tiles(self, path, tiles):
        self.view.tiles_committed(path, tiles)
        if self.view.layer is None:
            self.refresh_layers(select=path)

    def check_interrupted(self):
        if getattr(self, "_shut", False):
            return
        jobs = self.manager.store.recover_after_restart()
        self.refresh_jobs()
        for j in jobs[:1]:
            pct = 100.0 * j.cursor / j.total if j.total else 0
            if self.dialogs.confirm("Resume download?", f"The download “{j.name}” was interrupted at {pct:.0f}% "
                                    f"({j.cursor:,} of {j.total:,} tiles). Resume it now?"):
                self.resume_job(j.id)
            else:
                self.manager.store.set_state(j.id, "paused", "interrupted; resume from the Download panel")
        self.refresh_jobs()

    # ------------------------------------------------------------ GPS
    def _core_probe(self):
        try:
            st, text = self._core_fn()
        except Exception as exc:   # noqa: BLE001
            st, text = None, str(exc)
        self.bridge.core.emit(st, f"gps.position: {text}" if st else text)

    @_alive
    def _on_core(self, st, text):
        self.core_text = text
        self._on_gps(self.gps_state)

    @_alive
    def _on_gps(self, g):
        prev = self.gps_state
        self.gps_state = g
        self.view.gps = g
        self.gps_panel.show_state(g, self.settings.coord_format, self.core_text)
        now = time.monotonic()
        if g.connection != "connected":
            self.gps_label.setText("GPS: gpsd not connected")
        elif not g.has_fix:
            self.gps_label.setText("GPS: no fix")
        elif not g.fix_fresh(now):
            self.gps_label.setText("GPS: fix lost")
        else:
            sats = f" · {g.sats_used} sats" if g.sats_used is not None else ""
            self.gps_label.setText(f"GPS: {tm.fmt_coord(g.lat, g.lon, self.settings.coord_format)}{sats}")
        if g.has_fix and g.fix_fresh(now) and g.last_tpv != prev.last_tpv:
            if self.tool["follow"].isChecked():
                self.view.set_view(g.lat, g.lon)
            if self.recording and self.track_filter.accept(g.lat, g.lon, now, g.mode, g.accuracy_m()):
                self.store.append_point(self.recording.id, TrackPoint(g.lat, g.lon, g.alt, g.time, g.speed,
                                                                      g.accuracy_m()))
                self._refresh_track_overlay()
        self.view.update()

    def center_on_gps(self):
        g = self.gps_state
        if g.has_fix:
            self.view.set_view(g.lat, g.lon, max(self.view.zoom, 14))
        else:
            self.status.showMessage("No GPS position to centre on", 4000)

    def set_follow(self, on):
        self.tool["follow"].setChecked(bool(on))
        self.settings.follow = bool(on)
        if on:
            self.center_on_gps()

    # ------------------------------------------------------------ waypoints
    def refresh_waypoints(self):
        wps = self.store.waypoints()
        trks = self.store.tracks()
        self.view.waypoints = wps
        self.view.tracks = trks
        self.wpt_panel.set_data(wps, trks, self.settings.coord_format)
        self.view.update()

    def _refresh_track_overlay(self):
        self.view.tracks = self.store.tracks()
        self.view.update()

    def _set_add_by_click(self, on):
        self.add_by_click = on
        self.view.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def _on_map_click(self, lat, lon):
        if self.add_by_click and not self.view.download_mode:
            n = len(self.store.waypoints()) + 1
            self.store.add_waypoint(f"WPT {n:03d}", lat, lon, source="map")
            self.wpt_panel.by_click.setChecked(False)
            self.refresh_waypoints()

    def add_waypoint_at_gps(self):
        g = self.gps_state
        if not g.fix_fresh():
            self.dialogs.inform("Add waypoint", "No current GPS fix.")
            return
        n = len(self.store.waypoints()) + 1
        self.store.add_waypoint(f"GPS {n:03d}", g.lat, g.lon, ele=g.alt, source="gps", accuracy_m=g.accuracy_m(),
                                time_iso=g.time)
        self.refresh_waypoints()

    def rename_waypoint(self, wid):
        wp = self.store.get_waypoint(wid)
        if not wp:
            return
        name = self.dialogs.text("Rename waypoint", "Name", wp.name)
        if name:
            try:
                self.store.update_waypoint(wid, name=name)
            except ValueError as exc:
                self.dialogs.inform("Rename", str(exc))
            self.refresh_waypoints()

    def edit_waypoint(self, wid):
        wp = self.store.get_waypoint(wid)
        if not wp:
            return
        text = self.dialogs.text("Edit coordinates", "Latitude, longitude (decimal degrees)", f"{wp.lat:.6f}, {wp.lon:.6f}")
        if not text:
            return
        try:
            lat, lon = tm.parse_coord(text)
            self.store.update_waypoint(wid, lat=lat, lon=lon)
        except ValueError as exc:
            self.dialogs.inform("Edit coordinates", str(exc))
        self.refresh_waypoints()

    def delete_waypoint(self, wid):
        wp = self.store.get_waypoint(wid)
        if wp and self.dialogs.confirm("Delete waypoint", f"Delete “{wp.name}”?"):
            self.store.delete_waypoint(wid)
            self.refresh_waypoints()

    def goto_waypoint(self, wid):
        wp = self.store.get_waypoint(wid)
        if wp:
            self.view.selected_wpt = wid
            self.set_follow(False)
            self.view.set_view(wp.lat, wp.lon, max(self.view.zoom, 13))

    def set_recording(self, on):
        if on and not self.recording:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            self.recording = self.store.start_track(f"Track {stamp}")
            self.track_filter.reset()
        elif not on and self.recording:
            self.store.stop_track(self.recording.id)
            self.recording = None
        self.refresh_waypoints()

    def delete_track(self, tid):
        t = next((x for x in self.store.tracks(False) if x.id == tid), None)
        if t and self.dialogs.confirm("Delete track", f"Delete “{t.name}”?"):
            if self.recording and self.recording.id == tid:
                self.recording = None
                self.wpt_panel.record.setChecked(False)
            self.store.delete_track(tid)
            self.refresh_waypoints()

    def import_gpx(self):
        path = self.dialogs.open_file("Import GPX", "GPX (*.gpx);;All files (*)")
        if not path:
            return
        try:
            res = gpx.import_file(path, self.store)
        except (gpx.GpxError, OSError) as exc:
            self.dialogs.inform("GPX import failed", str(exc))
            return
        msg = f"Imported {res['waypoints']} waypoints and {res['tracks']} tracks ({res['points']} points)."
        if res["warnings"]:
            msg += f"\n{len(res['warnings'])} item(s) skipped: " + "; ".join(res["warnings"][:3])
        self.dialogs.inform("GPX import", msg)
        self.refresh_waypoints()

    def export_gpx(self):
        path = self.dialogs.save_file("Export GPX", "task-waypoints.gpx", "GPX (*.gpx)")
        if not path:
            return
        if not path.lower().endswith(".gpx"):
            path += ".gpx"
        overwrite = False
        if Path(path).exists():
            if not self.dialogs.confirm("Replace file?", f"{path} already exists. Replace it?"):
                return
            overwrite = True
        data = gpx.export(self.store.waypoints(), self.store.tracks(), now_iso=datetime.now(timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"))
        try:
            gpx.write_file(path, data, overwrite=overwrite)
        except OSError as exc:
            self.dialogs.inform("Export failed", str(exc))
            return
        self.status.showMessage(f"Exported to {path}", 6000)

    # ------------------------------------------------------------ misc
    def _on_cursor(self, lat, lon):
        self.coord_label.setText(tm.fmt_coord(lat, lon, self.settings.coord_format))

    def _on_view_changed(self):
        self.zoom_label.setText(f"z{self.view.zoom:.1f}")


    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            old = self.settings.data_dir
            dlg.apply(self.settings)
            self._save_settings()
            self.view.coord_style = self.settings.coord_format
            self.view.cache.images.maxsize = self.settings.cache_tiles
            self.refresh_waypoints()
            if old != self.settings.data_dir:
                self.dialogs.inform("Data folder", "The new data folder is used after restarting task-maps. "
                                    "Existing maps were not moved.")

    def _save_settings(self):
        try:
            settings_mod.save(self.settings)
        except OSError as exc:
            self.status.showMessage(f"Settings not saved: {exc}", 6000)

    def closeEvent(self, e):
        self.settings.view = [self.view.lat, self.view.lon, self.view.zoom]
        self.settings.follow = self.tool["follow"].isChecked()
        self._save_settings()
        self.shutdown()
        super().closeEvent(e)

    def shutdown(self):
        if getattr(self, "_shut", False):
            return
        self._shut = True
        self.bridge.blockSignals(True)
        self._gps_timer.stop()
        if self.gpsd:
            self.gpsd.stop()
        self.manager.shutdown()
        for t in ("_overlay_timer", "_absent_timer"):
            if hasattr(self, t):
                getattr(self, t).stop()
        self.loader.stop()
        for prov in self.providers.values():
            prov.stop()
        self.store.close()
