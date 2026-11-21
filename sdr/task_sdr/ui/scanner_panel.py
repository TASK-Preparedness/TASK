# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Smart Scanner panel (SDR Studio M2, task-sdr 0.2.2). Receive only. Scanning runs in the engine worker;
this panel sends commands and shows Scanner.snapshot() (refreshed every 250 ms by the window's GUI timer).
Nothing here starts a scan, a connection or a service by itself: every action is a user click."""

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMenu, QPushButton, QSpinBox, QVBoxLayout)

from task_sdr import prefs as prefs_mod
from task_sdr.dsp import BANDWIDTH, MODES
from task_sdr.scanner import ScanConfig, Scanner
from task_sdr.tuner import parse

STEPS = [5_000, 6_250, 8_333, 10_000, 12_500, 25_000, 50_000, 100_000, 200_000]
UNITS = {"Hz": 1, "kHz": 1000}


def mhz(hz):
    return f"{hz / 1e6:.4f}"


def fmt_tol(hz):
    return "exact" if hz == 0 else (f"±{hz / 1000:g} kHz" if hz >= 1000 and hz % 100 == 0 else f"±{hz} Hz")


class ToleranceEdit(QHBoxLayout):
    """Number + unit (Hz / kHz). value_hz() always returns an integer number of Hz; 0 = exact."""

    def __init__(self, hz=0):
        super().__init__()
        self.num = QDoubleSpinBox()
        self.num.setDecimals(3)
        self.num.setRange(0, 1_000_000)
        self.unit = QComboBox()
        self.unit.addItems(list(UNITS))
        self.addWidget(self.num)
        self.addWidget(self.unit)
        self.set_hz(hz)

    def set_hz(self, hz):
        if hz and hz % 1000 == 0:
            self.unit.setCurrentText("kHz")
            self.num.setValue(hz / 1000)
        else:
            self.unit.setCurrentText("Hz")
            self.num.setValue(hz)

    def value_hz(self):
        return int(round(self.num.value() * UNITS[self.unit.currentText()]))


class ScannerPanel(QGroupBox):
    message = Signal(str)
    tuneRequested = Signal(object)  # Hz as a Python int (no 32-bit limit)
    saveRequested = Signal()
    bookmarksChanged = Signal()

    def __init__(self, engine):
        super().__init__("Smart Scanner (receive only)")
        self.engine = engine
        pr = engine.prefs
        self.scanner = Scanner(pr.sample_rate, engine.profile, persistent_ignores=prefs_mod.ignore_list(pr),
                               default_tolerance_hz=pr.scan_ignore_tol_hz)
        self._last = 0.0
        g = QGridLayout()
        self.start_e, self.stop_e = QLineEdit(mhz(pr.scan_start_hz)), QLineEdit(mhz(pr.scan_stop_hz))
        self.step = QComboBox()
        for s in STEPS:
            self.step.addItem(f"{s / 1000:g} kHz", s)
        self.step.setCurrentIndex(STEPS.index(pr.scan_step_hz) if pr.scan_step_hz in STEPS else 4)
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        self.mode.setCurrentText(pr.scan_mode)
        self.snr = QDoubleSpinBox()
        self.snr.setRange(3, 40)
        self.snr.setValue(pr.scan_snr_db)
        self.snr.setSuffix(" dB over floor")
        self.vad = QCheckBox("Voice check (labels history)")
        self.vad.setChecked(pr.scan_vad)
        self.use_bm = QCheckBox("Scan bookmarks instead")
        self.carrier_on = QCheckBox("Carrier-only timeout: release a no-voice carrier after")
        self.carrier_on.setChecked(pr.scan_carrier_timeout_s is not None)
        self.carrier_s = QSpinBox()
        self.carrier_s.setRange(1, 3600)
        self.carrier_s.setSuffix(" s")
        self.carrier_s.setValue(int(pr.scan_carrier_timeout_s or 10))
        self.carrier_off_note = QLabel("OFF: channels are released only by the 4 s hold.")
        self.tol = ToleranceEdit(pr.scan_ignore_tol_hz)
        for i, (lbl, w) in enumerate([("Start MHz", self.start_e), ("Stop MHz", self.stop_e), ("Step", self.step),
                                       ("Mode", self.mode)]):
            g.addWidget(QLabel(lbl), 0, 2 * i)
            g.addWidget(w, 0, 2 * i + 1)
        g.addWidget(QLabel("Threshold"), 1, 0)
        g.addWidget(self.snr, 1, 1, 1, 3)
        g.addWidget(self.vad, 1, 4, 1, 2)
        g.addWidget(self.use_bm, 1, 6, 1, 2)
        crow = QHBoxLayout()
        crow.addWidget(self.carrier_on)
        crow.addWidget(self.carrier_s)
        crow.addWidget(self.carrier_off_note, 1)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("New ignores match:"))
        trow.addLayout(self.tol)
        self.tol_note = QLabel("0 = exact frequency. Always capped below half the channel spacing.")
        trow.addWidget(self.tol_note, 1)
        b = QHBoxLayout()
        self.scan_btn = QPushButton("Scan")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.skip_btn = QPushButton("Skip")
        self.ign_btn = QPushButton("Ignore current (session)")
        self.ign_always = QPushButton("Ignore current (always)")
        for w in (self.scan_btn, self.pause_btn, self.resume_btn, self.skip_btn, self.ign_btn, self.ign_always):
            b.addWidget(w)
        self.status = QLabel("Idle")
        # history
        hv = QVBoxLayout()
        hv.addWidget(QLabel("History (newest first, 50 + pinned; right-click for actions)"))
        self.history = QListWidget()
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        hv.addWidget(self.history)
        self.h_actions = {}
        hb1, hb2 = QHBoxLayout(), QHBoxLayout()
        for key, text, row in [("retune", "Retune", hb1), ("ignore", "Ignore (session)", hb1),
                               ("ignore_always", "Ignore (always)", hb1), ("unignore", "Un-ignore", hb1),
                               ("bm_add", "Add bookmark", hb2), ("bm_remove", "Remove bookmark", hb2),
                               ("pin", "Pin / unpin", hb2), ("clear", "Clear unpinned", hb2)]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, k=key: self.history_action(k))
            row.addWidget(btn)
            self.h_actions[key] = btn
        hv.addLayout(hb1)
        hv.addLayout(hb2)
        # ignores
        iv = QVBoxLayout()
        iv.addWidget(QLabel("Ignored frequencies — Always = saved, Session = until the Studio closes"))
        self.ignored = QListWidget()
        iv.addWidget(self.ignored)
        er = QHBoxLayout()
        self.edit_tol = ToleranceEdit(0)
        self.edit_apply = QPushButton("Set tolerance")
        er.addLayout(self.edit_tol)
        er.addWidget(self.edit_apply)
        iv.addLayout(er)
        ib = QHBoxLayout()
        self.make_always = QPushButton("Make Always")
        self.make_session = QPushButton("Make Session")
        self.unign_btn = QPushButton("Remove")
        for w in (self.make_always, self.make_session, self.unign_btn):
            ib.addWidget(w)
        iv.addLayout(ib)
        lists = QHBoxLayout()
        lists.addLayout(hv, 3)
        lists.addLayout(iv, 2)
        v = QVBoxLayout(self)
        v.addLayout(g)
        v.addLayout(crow)
        v.addLayout(trow)
        v.addLayout(b)
        v.addWidget(self.status)
        v.addLayout(lists)
        self.scan_btn.clicked.connect(self.toggle)
        self.pause_btn.clicked.connect(self.pause)
        self.resume_btn.clicked.connect(self.resume)
        self.skip_btn.clicked.connect(self.skip)
        self.ign_btn.clicked.connect(lambda: self.ignore(False))
        self.ign_always.clicked.connect(lambda: self.ignore(True))
        self.unign_btn.clicked.connect(self.unignore)
        self.edit_apply.clicked.connect(self.edit_tolerance)
        self.make_always.clicked.connect(lambda: self.set_kind(True))
        self.make_session.clicked.connect(lambda: self.set_kind(False))
        self.ignored.currentRowChanged.connect(self._ignore_selected)
        self.history.itemDoubleClicked.connect(lambda _i: self.history_action("retune"))
        self.history.customContextMenuRequested.connect(self._history_menu)
        self.carrier_on.toggled.connect(self._carrier_label)
        self._carrier_label()
        self.refresh(force=True)

    # ------------------------------------------------------------- config
    def _carrier_label(self):
        on = self.carrier_on.isChecked()
        self.carrier_s.setEnabled(on)
        self.carrier_off_note.setText("ON: needs Voice check; a channel judged 'no voice' is released after this."
                                      if on else "OFF: channels are released only by the 4 s hold.")

    def config(self):
        pr = self.engine.prefs
        start, stop = parse(self.start_e.text()), parse(self.stop_e.text())
        step = int(self.step.currentData())
        mode = self.mode.currentText()
        chans = [b["freq_hz"] for b in pr.bookmarks] if self.use_bm.isChecked() else None
        bw = BANDWIDTH[mode][0] if mode != "WFM" else 200_000
        return ScanConfig(start_hz=start, stop_hz=stop, step_hz=step, mode=mode, channel_bw_hz=min(bw, max(step, 2_000)),
                          channels=chans, snr_db=float(self.snr.value()), squelch_dbfs=pr.squelch_dbfs,
                          use_vad=self.vad.isChecked(),
                          carrier_timeout_s=float(self.carrier_s.value()) if self.carrier_on.isChecked() else None)

    def _persist(self):
        prefs_mod.store_ignores(self.engine.prefs, self.scanner.ignores)
        self.saveRequested.emit()

    # ------------------------------------------------------------- scan state
    def toggle(self):
        if self.scanning():
            self.engine.stop_scan()
            self.message.emit("Scan stopped.")
            self.refresh(force=True)
            return
        if not (self.engine._thread and self.engine._thread.is_alive()):
            self.message.emit("Start the receiver first.")
            return
        try:
            cfg = self.config()
            self.scanner.ignores.default_tolerance_hz = self.tol.value_hz()
            self.engine.start_scan(self.scanner, cfg)
        except (ValueError, TypeError) as exc:
            self.message.emit(f"Scan not started: {exc}")
            return
        pr = self.engine.prefs
        if not cfg.channels:
            pr.scan_start_hz, pr.scan_stop_hz = cfg.start_hz, cfg.stop_hz
        pr.scan_step_hz, pr.scan_mode, pr.scan_snr_db, pr.scan_vad = cfg.step_hz, cfg.mode, cfg.snr_db, cfg.use_vad
        pr.scan_carrier_timeout_s = cfg.carrier_timeout_s
        pr.scan_ignore_tol_hz = self.scanner.ignores.default_tolerance_hz
        self.saveRequested.emit()
        n = sum(len(c) for _, c in self.scanner.chunks)
        self.message.emit(f"Scanning {n} channels in {len(self.scanner.chunks)} sweeps.")
        self.refresh(force=True)

    def scanning(self):
        return self.engine.scanner is not None and self.scanner.state != "idle"

    def pause(self):
        if not self.scanner.pause():
            self.message.emit("Nothing to pause.")
        self.refresh(force=True)

    def resume(self):
        f = self.scanner.resume()
        if f is None:
            self.message.emit("Not paused.")
        else:
            self.engine.request_tune(f)
        self.refresh(force=True)

    def skip(self):
        f = self.scanner.skip()
        if f is not None:
            self.engine.request_tune(f)
        self.refresh(force=True)

    def ignore(self, persistent):
        f = self.scanner.locked or (self.scanner.entry.freq_hz if self.scanner.entry else None)
        if f is None:
            self.message.emit("Nothing to ignore yet.")
            return
        nxt = self.scanner.ignore_current(persistent, self.tol.value_hz())
        if nxt is not None:
            self.engine.request_tune(nxt)
        if persistent:
            self._persist()
        self.message.emit(f"Ignoring {mhz(f)} MHz {fmt_tol(self.tol.value_hz())} "
                          f"{'(Always)' if persistent else '(this session)'}.")
        self.refresh(force=True)

    # ------------------------------------------------------------- ignore review / edit
    def _selected_ignore(self):
        rev = self.scanner.ignores.review()
        row = self.ignored.currentRow()
        return rev[row] if 0 <= row < len(rev) else None

    def _ignore_selected(self, _row):
        sel = self._selected_ignore()
        if sel:
            self.edit_tol.set_hz(sel[2])

    def _keep_selection(self, freq):
        self.refresh(force=True)
        for i, r in enumerate(self.scanner.ignores.review()):
            if r[0] == freq:
                self.ignored.setCurrentRow(i)

    def edit_tolerance(self):
        sel = self._selected_ignore()
        if not sel:
            return
        try:
            self.scanner.ignores.edit(sel[0], tolerance_hz=self.edit_tol.value_hz())
        except ValueError as exc:
            self.message.emit(str(exc))
            return
        self._persist()
        self._keep_selection(sel[0])

    def set_kind(self, persistent):
        sel = self._selected_ignore()
        if not sel:
            return
        self.scanner.ignores.edit(sel[0], persistent=persistent)
        self._persist()
        self._keep_selection(sel[0])

    def unignore(self):
        sel = self._selected_ignore()
        if not sel:
            return
        self.scanner.unignore(sel[0])
        self._persist()
        self.message.emit(f"No longer ignoring {mhz(sel[0])} MHz.")
        self.refresh(force=True)

    # ------------------------------------------------------------- history actions
    def _history_menu(self, pos):
        menu = QMenu(self)
        for key, btn in self.h_actions.items():
            act = menu.addAction(btn.text())
            act.triggered.connect(lambda _=False, k=key: self.history_action(k))
        menu.exec(self.history.mapToGlobal(pos))

    def _selected_entry(self):
        row = self.history.currentRow()
        items = self.scanner.history.items
        return (row, items[row]) if 0 <= row < len(items) else (row, None)

    def history_action(self, key):
        row, e = self._selected_entry()
        if key == "clear":
            with self.scanner.lock:
                self.scanner.history.clear()
            self.refresh(force=True)
            return
        if e is None:
            self.message.emit("Select a history entry first.")
            return
        pr = self.engine.prefs
        if key == "retune":
            # a manual retune takes the receiver back: the scan stops (there is no recording to interrupt)
            if self.scanning():
                self.engine.stop_scan()
            self.tuneRequested.emit(e.freq_hz)
        elif key in ("ignore", "ignore_always"):
            nxt = self.scanner.ignore_freq(e.freq_hz, key == "ignore_always", self.tol.value_hz())
            if nxt is not None:
                self.engine.request_tune(nxt)
            if key == "ignore_always":
                self._persist()
            self.message.emit(f"Ignoring {mhz(e.freq_hz)} MHz ({'Always' if key == 'ignore_always' else 'session'}).")
        elif key == "unignore":
            if self.scanner.unignore(e.freq_hz):
                self._persist()
                self.message.emit(f"No longer ignoring {mhz(e.freq_hz)} MHz.")
            else:
                self.message.emit(f"{mhz(e.freq_hz)} MHz is not on the ignore list.")
        elif key == "bm_add":
            if any(b["freq_hz"] == e.freq_hz for b in pr.bookmarks):
                self.message.emit("Already bookmarked.")
            else:
                pr.bookmarks.append({"name": f"Scan {mhz(e.freq_hz)}", "freq_hz": e.freq_hz, "mode": e.mode,
                                     "bandwidth_hz": None})
                self.saveRequested.emit()
                self.bookmarksChanged.emit()
                self.message.emit(f"Bookmarked {mhz(e.freq_hz)} MHz.")
        elif key == "bm_remove":
            n = len(pr.bookmarks)
            pr.bookmarks[:] = [b for b in pr.bookmarks if b["freq_hz"] != e.freq_hz]
            if len(pr.bookmarks) != n:
                self.saveRequested.emit()
                self.bookmarksChanged.emit()
                self.message.emit(f"Bookmark {mhz(e.freq_hz)} MHz removed.")
            else:
                self.message.emit("Not bookmarked.")
        elif key == "pin":
            self.scanner.set_pin(row, not e.pinned)
        self.refresh(force=True)
        self.history.setCurrentRow(min(row, self.history.count() - 1))

    # ------------------------------------------------------------- display
    def refresh(self, force=False):
        now = time.monotonic()
        if not force and now - self._last < 0.25:
            return
        self._last = now
        s = self.scanner.snapshot()
        st = s["state"]
        if st == "locked":
            txt = f"LOCKED {mhz(s['locked'])} MHz, hold {s['hold_left']:.1f} s"
        elif st == "scanning":
            txt = f"Scanning sweep {s['chunk'] + 1}/{s['chunks']} ({s['channels']} channels)"
        elif st == "paused":
            txt = ("Paused on " + mhz(s["locked"]) + " MHz (audio on, hold frozen)") if s["paused_from"] == "locked" \
                else "Paused (sweep frozen)"
        else:
            txt = "Idle"
        if s["ignore_cap_hz"] is not None and st != "idle":
            txt += f" — ignore tolerance capped at {fmt_tol(s['ignore_cap_hz'])}"
        self.status.setText(txt)
        active = self.engine.scanner is not None and st != "idle"
        self.scan_btn.setText("Stop scan" if active else "Scan")
        self.pause_btn.setEnabled(st in ("scanning", "locked"))
        self.resume_btn.setEnabled(st == "paused")
        self.skip_btn.setEnabled(st in ("scanning", "locked", "paused"))
        bms = {b["freq_hz"] for b in self.engine.prefs.bookmarks}
        rows = []
        for e in s["history"]:
            voice = {True: "voice", False: "no voice", None: "squelch only"}[e.voice]
            tags = ("📌 " if e.pinned else "") + ("★ " if e.freq_hz in bms else "") + \
                ("⊘ " if self.scanner.ignores.match(e.freq_hz) else "")
            rows.append(f"{tags}{time.strftime('%H:%M:%S', time.localtime(e.first))}  "
                        f"{mhz(e.freq_hz)} MHz {e.mode}  {e.duration_s:.1f} s  peak {e.peak_dbfs:.0f} dBFS  {voice}"
                        f"{'  — ' + e.note if e.note else ''}")
        if rows != [self.history.item(i).text() for i in range(self.history.count())]:
            cur = self.history.currentRow()
            self.history.clear()
            self.history.addItems(rows)
            self.history.setCurrentRow(cur)
        ign = []
        for f, kind, tol, eff, label in s["ignores"]:
            t = fmt_tol(tol) + (f" (capped to {fmt_tol(eff)})" if eff != tol else "")
            ign.append(f"{mhz(f)} MHz {t}  [{'Always' if kind == 'always' else 'Session'}]{'  ' + label if label else ''}")
        if ign != [self.ignored.item(i).text() for i in range(self.ignored.count())]:
            cur = self.ignored.currentRow()
            self.ignored.clear()
            self.ignored.addItems(ign)
            self.ignored.setCurrentRow(min(cur, len(ign) - 1))
