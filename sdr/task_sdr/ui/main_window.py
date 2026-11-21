# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""T.A.S.K. SDR Studio main window (0.2.2: M1 + M2 Smart Scanner). RECEIVE ONLY — there is no transmit control anywhere.

Threads: the engine's worker reads IQ, demodulates and computes spectra; it only appends to bounded queues
(engine.frames, engine.audio_q). A GUI-thread QTimer (30 ms) takes the newest frame and pending audio, so Qt is
never blocked by DSP and the worker never waits on Qt.
"""

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QMainWindow, QPushButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from task_sdr import prefs as prefs_mod
from task_sdr.backends import RangeError, discover
from task_sdr.dsp import BANDWIDTH, MODES, s_meter
from task_sdr.ui.overlay_panel import OverlayPanel
from task_sdr.ui.scanner_panel import ScannerPanel
from task_sdr.ui.widgets import ACCENT, BG, PANEL, SMeter, SpectrumWaterfall, TunerWidget

STYLE = f"""
QWidget {{ background: {BG}; color: #d8e3ee; }}
QGroupBox {{ border: 1px solid {PANEL}; border-radius: 6px; margin-top: 14px; padding: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {ACCENT}; }}
QPushButton {{ background: {PANEL}; border: 1px solid #34485f; border-radius: 4px; padding: 5px 9px; }}
QPushButton:checked {{ background: {ACCENT}; color: {BG}; }}
QComboBox, QSpinBox, QListWidget {{ background: {PANEL}; border: 1px solid #34485f; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 12px; }}
"""


class Bridge(QObject):
    update = Signal(str, object)


class MainWindow(QMainWindow):
    def __init__(self, engine, audio_out=None, prefs_path=None, backends=None, discover_fn=discover,
                 overlay_opts=None, load_overlays=True):
        super().__init__()
        self.engine, self.audio_out, self.prefs_path = engine, audio_out, prefs_path
        self.backends, self.discover_fn = backends, discover_fn
        self.setWindowTitle("T.A.S.K. SDR Studio (receive only)")
        self.setStyleSheet(STYLE)
        self.bridge = Bridge()
        self.bridge.update.connect(self._on_update)
        engine.on_update = self.bridge.update.emit       # state changes only (rare); data goes through queues
        engine.audio = None
        # 0.2.4: the sink pulls from engine.ring itself (Qt schedule) when it shares the ring; the GUI timer then never
        # touches audio, so waterfall/repaint load cannot starve or chop the audio.
        self._sink_pulls = audio_out is not None and getattr(audio_out, "ring", None) is engine.ring
        if audio_out is not None and hasattr(audio_out, "stats"):
            engine.sink_info = audio_out
        pr = engine.prefs
        self.found = []

        # ---- top: tuner + S-meter + status
        prof = engine.profile
        self.tuner = TunerWidget(pr.freq_hz if prof.accepts(pr.freq_hz) else 100_000_000, prof.accepts, self._why)
        self.tuner.changed.connect(self.tune)
        self.tuner.rejected.connect(lambda why: self._msg(f"Rejected: {why}"))
        self.smeter = SMeter()
        self.state = QLabel("Stopped")
        self.message = QLabel("")
        self.message.setStyleSheet(f"color: {ACCENT};")
        top = QHBoxLayout()
        top.addWidget(self.tuner, 3)
        tv = QVBoxLayout()
        tv.addWidget(self.smeter)
        tv.addWidget(self.state)
        tv.addWidget(self.message)
        top.addLayout(tv, 2)

        # ---- source
        self.backend_box = QComboBox()
        self.device_box = QComboBox()
        self.refresh_btn = QPushButton("Find receivers")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.toggle)
        self.device_box.currentIndexChanged.connect(self._device_chosen)
        src = QGroupBox("Source")
        sf = QFormLayout(src)
        sf.addRow("Backend", self.backend_box)
        sf.addRow("Device", self.device_box)
        row = QHBoxLayout()
        row.addWidget(self.refresh_btn)
        row.addWidget(self.start_btn)
        sf.addRow(row)
        self.range_lbl = QLabel("")
        self.range_lbl.setWordWrap(True)
        sf.addRow(self.range_lbl)

        # ---- demod
        dem = QGroupBox("Demodulator")
        dv = QVBoxLayout(dem)
        mrow = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for m in MODES:
            b = QPushButton(m)
            b.setCheckable(True)
            b.setChecked(m == pr.mode)
            self.mode_group.addButton(b)
            self.mode_btns[m] = b
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            mrow.addWidget(b)
        dv.addLayout(mrow)
        df = QFormLayout()
        self.bw = QSpinBox()
        self.bw.setSuffix(" Hz")
        self.bw.setSingleStep(100)
        self.bw.editingFinished.connect(lambda: self.set_bandwidth(self.bw.value()))
        df.addRow("Bandwidth", self.bw)
        self.auto_gain = QCheckBox("Auto")
        self.auto_gain.setChecked(pr.gain_db is None)
        self.gain = QSlider(Qt.Orientation.Horizontal)
        self.gain.setRange(0, 496)
        self.gain.setValue(int((pr.gain_db or 30) * 10))
        self.gain_lbl = QLabel("")
        self.auto_gain.toggled.connect(lambda _: self.apply_gain())
        self.gain.sliderReleased.connect(self.apply_gain)
        g = QHBoxLayout()
        g.addWidget(self.auto_gain)
        g.addWidget(self.gain, 1)
        g.addWidget(self.gain_lbl)
        df.addRow("RF gain", g)
        self.agc = QCheckBox("Audio AGC")
        self.agc.setChecked(pr.agc)
        self.agc.toggled.connect(lambda on: setattr(self.engine.prefs, "agc", bool(on)))
        df.addRow(self.agc)
        self.sq_on = QCheckBox("Squelch")
        self.sq_on.setChecked(pr.squelch_dbfs is not None)
        self.sq = QSlider(Qt.Orientation.Horizontal)
        self.sq.setRange(-1200, 0)
        self.sq.setValue(int((pr.squelch_dbfs if pr.squelch_dbfs is not None else -60) * 10))
        self.sq_on.toggled.connect(lambda _: self.apply_squelch())
        self.sq.sliderReleased.connect(self.apply_squelch)
        s = QHBoxLayout()
        s.addWidget(self.sq_on)
        s.addWidget(self.sq, 1)
        df.addRow(s)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(pr.volume * 100))
        self.vol.valueChanged.connect(lambda v: setattr(self.engine.prefs, "volume", v / 100))
        df.addRow("Volume", self.vol)
        self.audio_lbl = QLabel("Audio: " + ("output ready" if audio_out is not None else "no permitted output"))
        df.addRow(self.audio_lbl)
        dv.addLayout(df)

        # ---- bookmarks + presets
        bm = QGroupBox("Bookmarks && presets")
        bv = QVBoxLayout(bm)
        self.bookmarks = QListWidget()
        self.bookmarks.itemActivated.connect(lambda it: self.use_entry(self.bookmarks.row(it), "bookmarks"))
        brow = QHBoxLayout()
        self.add_bm = QPushButton("☆ Add")
        self.add_bm.clicked.connect(self.add_bookmark)
        self.del_bm = QPushButton("Remove")
        self.del_bm.clicked.connect(self.remove_bookmark)
        brow.addWidget(self.add_bm)
        brow.addWidget(self.del_bm)
        self.presets = QListWidget()
        self.presets.itemActivated.connect(lambda it: self.use_entry(self.presets.row(it), "presets"))
        bv.addWidget(QLabel("Bookmarks"))
        bv.addWidget(self.bookmarks)
        bv.addLayout(brow)
        bv.addWidget(QLabel("Presets"))
        bv.addWidget(self.presets)

        side = QVBoxLayout()
        for w in (src, dem, bm):
            side.addWidget(w)
        foot = QLabel("Receive only. SDR++/Gqrx are separate External apps; only one program can own the receiver.")
        foot.setWordWrap(True)
        side.addWidget(foot)
        sw = QWidget()
        sw.setLayout(side)
        sw.setMaximumWidth(400)
        self.view = SpectrumWaterfall()
        self.view.tuneRequested.connect(self.tune)
        self.view.overlayClicked.connect(lambda hit: self.overlays.offer_tune(*hit))
        root = QWidget()
        v = QVBoxLayout(root)
        v.addLayout(top)
        h = QHBoxLayout()
        h.addWidget(sw)
        self.scan = ScannerPanel(engine)
        self.scan.message.connect(self._msg)
        self.scan.tuneRequested.connect(self.tune)
        self.scan.saveRequested.connect(self._save)
        self.scan.bookmarksChanged.connect(self._fill_lists)
        rv = QVBoxLayout()
        rv.addWidget(self.view, 3)
        self.overlays = OverlayPanel(**(overlay_opts or {}))
        self.overlays.message.connect(self._msg)
        self.overlays.tuneRequested.connect(self.tune)          # same receive-only path as a manual tune
        self.overlays.changed.connect(self._sync_overlays)
        self._ov_key = None
        self.tabs = QTabWidget()
        self.tabs.addTab(self.scan, "Scanner")
        self.tabs.addTab(self.overlays, "Overlays")
        rv.addWidget(self.tabs, 2)
        h.addLayout(rv, 1)
        v.addLayout(h, 1)
        self.setCentralWidget(root)
        self._fill_lists()
        self._sync_bw()
        self.apply_gain(apply=False)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)
        self.hb = QTimer(self)
        self.hb.timeout.connect(lambda: self.engine.status.heartbeat())
        self.hb.start(2000)
        self.refresh_devices()
        self.overlays.set_current_hz(self.engine.prefs.freq_hz)
        if load_overlays:
            self.overlays.reload()                               # background thread; UI stays responsive

    # ------------------------------------------------------------------ helpers
    def _why(self, hz):
        p = self.engine.profile
        return (f"{hz / 1e6:.6f} MHz is outside the {p.name} range ({p.min_hz / 1e6:g}–{p.max_hz / 1e6:g} MHz)")

    def _msg(self, text):
        self.message.setText(text)

    def _save(self):
        try:
            prefs_mod.save(self.engine.prefs, self.prefs_path)
        except (OSError, ValueError) as exc:
            self._msg(f"settings not saved: {exc}")

    def _fill_lists(self):
        self.bookmarks.clear()
        for b in self.engine.prefs.bookmarks:
            self.bookmarks.addItem(f"{b['name']} — {b['freq_hz'] / 1e6:.4f} MHz {b['mode']}")
        self.presets.clear()
        for p in self.engine.prefs.presets:
            self.presets.addItem(f"{p['name']} — {p['freq_hz'] / 1e6:.4f} MHz {p['mode']}")

    def _sync_bw(self):
        m = self.engine.prefs.mode
        dflt, lo, hi = BANDWIDTH[m]
        self.bw.blockSignals(True)
        self.bw.setRange(lo, hi)
        self.bw.setValue(int(self.engine.prefs.bandwidth_hz or dflt))
        self.bw.blockSignals(False)

    # ------------------------------------------------------------------ discovery / source
    def refresh_devices(self):
        """Safe discovery: lists receivers without opening or claiming them."""
        self.backend_box.clear()
        self.device_box.blockSignals(True)
        self.device_box.clear()
        self.found = []
        for b, ok, why, devs in self.discover_fn(self.backends):
            label = b.name + ("" if ok else ("  [STUB]" if b.stub else "  [unavailable]"))
            self.backend_box.addItem(label, b.key)
            self.backend_box.setItemData(self.backend_box.count() - 1, why or "available", Qt.ItemDataRole.ToolTipRole)
            for d in devs:
                self.found.append((b, d))
                self.device_box.addItem(f"{d.label} — {b.key}")
        self.device_box.blockSignals(False)
        pick = next((i for i, (b, d) in enumerate(self.found) if b.key == self.engine.prefs.backend), 0 if self.found else -1)
        if pick >= 0:
            self.device_box.setCurrentIndex(pick)
            self._device_chosen(pick)
        else:
            self.range_lbl.setText("No receiver found. Plug in the RTL-SDR (or choose SIMULATED).")
        return self.found

    def _device_chosen(self, i):
        if not 0 <= i < len(self.found):
            return
        b, d = self.found[i]
        self.engine.opener = lambda b=b, d=d: b.open(d)
        self.engine.profile = d.profile
        self.engine.prefs.backend = b.key
        self.tuner.set_range(d.profile.accepts, self._why)
        self.range_lbl.setText(f"{d.profile.name}: {d.profile.min_hz / 1e6:g}–{d.profile.max_hz / 1e6:g} MHz. "
                               f"{d.profile.note}")
        if not d.profile.accepts(self.tuner.hz):
            self._msg(f"Current frequency is outside {d.profile.name}; tune inside the range.")

    def toggle(self):
        if self.engine._thread and self.engine._thread.is_alive():
            self.engine.stop()
            self.start_btn.setText("Start")
            return
        if not self.found:
            self._msg("No receiver selected.")
            return
        self.engine.start()
        self.start_btn.setText("Stop")

    # ------------------------------------------------------------------ controls
    def tune(self, hz):
        if self.scan.scanning():                 # a manual tune takes the receiver back from the scanner
            self.scan.toggle()
        try:
            hz = self.engine.retune_checked(hz)
        except RangeError as exc:
            self._msg(f"Rejected: {exc}")
            self.tuner.set_hz(self.engine.prefs.freq_hz)
            return False
        if self.tuner.hz != hz:
            self.tuner.set_hz(hz)
        self._msg("")
        self._save()
        return True

    def set_mode(self, m):
        self.engine.retune(mode=m, bandwidth=None)
        self.mode_btns[m].setChecked(True)
        self._sync_bw()
        self._save()

    def set_bandwidth(self, hz):
        self.engine.retune(bandwidth=int(hz))
        self._sync_bw()
        self._save()

    def apply_gain(self, apply=True):
        auto = self.auto_gain.isChecked()
        self.gain.setEnabled(not auto)
        self.gain_lbl.setText("auto" if auto else f"{self.gain.value() / 10:.1f} dB")
        if apply:
            self.engine.retune(gain_db=None if auto else self.gain.value() / 10)
            self._save()

    def apply_squelch(self):
        self.engine.retune(squelch=self.sq.value() / 10 if self.sq_on.isChecked() else None)
        self._save()

    def add_bookmark(self, name=None):
        p = self.engine.prefs
        b = {"name": name or f"{p.freq_hz / 1e6:.4f} {p.mode}", "freq_hz": int(p.freq_hz), "mode": p.mode,
             "bandwidth_hz": p.bandwidth_hz}
        p.bookmarks.append(b)
        self._fill_lists()
        self._save()
        return b

    def remove_bookmark(self):
        r = self.bookmarks.currentRow()
        if 0 <= r < len(self.engine.prefs.bookmarks):
            del self.engine.prefs.bookmarks[r]
            self._fill_lists()
            self._save()

    def use_entry(self, row, kind):
        items = getattr(self.engine.prefs, kind)
        if not 0 <= row < len(items):
            return False
        e = items[row]
        if not self.engine.profile.accepts(e["freq_hz"]):
            self._msg(f"Rejected: {self._why(e['freq_hz'])}")
            return False
        self.engine.retune(mode=e["mode"], bandwidth=e.get("bandwidth_hz"))
        self.mode_btns[e["mode"]].setChecked(True)
        self._sync_bw()
        return self.tune(e["freq_hz"])

    # ------------------------------------------------------------------ data path (GUI thread)
    def _tick(self):
        f = self.engine.take_frame()
        if f is not None:
            self.view.set_frame(f["spectrum"], self.engine.prefs.freq_hz, self.engine.prefs.sample_rate,
                                self.engine.demod.bandwidth if self.engine.demod else 0)
            if f["chan"] is not None:                         # None while the scanner is sweeping
                lbl, units = s_meter(f["chan"], self.engine.prefs.s9_dbfs)
                self.smeter.set_value(lbl, units, f["chan"])
            if f.get("scan") is not None and self.tuner.hz != self.engine.prefs.freq_hz:
                self.tuner.set_hz(self.engine.prefs.freq_hz)
        key = (self.engine.prefs.freq_hz, self.engine.prefs.sample_rate)
        if key != self._ov_key:
            self._ov_key = key
            self._sync_overlays()
        self.scan.refresh()
        if not self._sink_pulls:
            a = self.engine.take_audio()
            if len(a) and self.audio_out is not None:
                self.audio_out.write(a)

    def _on_update(self, kind, data):
        if kind == "state":
            self.state.setText(data["state"] + (f": {data['error']}" if data.get("error") else ""))
            if data["state"] in ("stopped",):
                self.start_btn.setText("Start")

    def _sync_overlays(self):
        hz, rate = self.engine.prefs.freq_hz, self.engine.prefs.sample_rate
        self.overlays.set_current_hz(hz)
        self.view.set_overlays(self.overlays.set.visible(hz - rate // 2, hz + rate // 2))

    def closeEvent(self, ev):
        self.engine.stop_scan()
        self.timer.stop()
        self.hb.stop()
        self.engine.stop()
        if self.audio_out is not None:
            self.audio_out.close()
        super().closeEvent(ev)
