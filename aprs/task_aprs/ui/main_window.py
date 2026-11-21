# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-aprs window. Every transmission is a button press; nothing is sent automatically."""

import datetime
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from task_aprs import config
from task_aprs.amateur import parse_path


class Bridge(QObject):
    changed = Signal(object)


class SignInDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to T.A.S.K. Core")
        f = QFormLayout(self)
        self.user, self.secret = QLineEdit(), QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        f.addRow("Account", self.user)
        f.addRow("Password", self.secret)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)


def _ts(t):
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S") if t else "—"


def _refusal_text(d):
    return "\n".join(["Not sent:"] + [f"• {r}" for r in d.reasons + d.needs_confirmation])


class MainWindow(QMainWindow):
    def __init__(self, svc, gate=None, history_factory=None):
        super().__init__()
        self.svc, self.gate, self.history_factory, self.history = svc, gate, history_factory, None
        self.setWindowTitle("T.A.S.K. APRS")
        self.bridge = Bridge()
        self.bridge.changed.connect(self._refresh)
        svc.listeners.append(self.bridge.changed.emit)
        tabs = QTabWidget()
        tabs.addTab(self._stations_tab(), "Stations")
        tabs.addTab(self._monitor_tab(), "Monitor")
        tabs.addTab(self._messages_tab(), "Messages")
        tabs.addTab(self._gmrs_tab(), "GMRS data")
        tabs.addTab(self._settings_tab(), "Settings")
        top = QWidget()
        v = QVBoxLayout(top)
        bar = QHBoxLayout()
        self.conn_label, self.queued_label, self.session_btn = QLabel(), QLabel(), QPushButton("Sign in")
        self.queued_label.setStyleSheet("color:#c80; font-weight:bold")
        self.session_btn.clicked.connect(self.toggle_session)
        reconnect = QPushButton("Connect to Direwolf")
        reconnect.clicked.connect(self.connect_direwolf)
        for w in (self.conn_label, self.queued_label):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(reconnect)
        bar.addWidget(self.session_btn)
        v.addLayout(bar)
        v.addWidget(tabs)
        self.setCentralWidget(top)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        if gate is not None:
            gate.listeners.append(lambda reason: self._locked(reason))
        self._refresh(None)

    # ------------------------------------------------------------ tabs
    def _stations_tab(self):
        self.stations = QTableWidget(0, 5)
        self.stations.setHorizontalHeaderLabels(["Station", "Last heard", "Position", "Type", "Source"])
        return self.stations

    def _monitor_tab(self):
        self.monitor = QPlainTextEdit(readOnly=True)
        self.monitor.setMaximumBlockCount(2000)
        return self.monitor

    def _messages_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.msg_lock = QLabel("Sign in to view and send messages.")
        self.msg_list = QListWidget()
        self.outbox = QTableWidget(0, 4)
        self.outbox.setHorizontalHeaderLabels(["To", "Id", "State", "Detail"])
        form = QFormLayout()
        self.to, self.text, self.path = QLineEdit(), QLineEdit(), QLineEdit("WIDE1-1,WIDE2-1")
        self.text.setMaxLength(67)
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setValue(3)
        form.addRow("To (call-SSID)", self.to)
        form.addRow("Text (≤ 67)", self.text)
        form.addRow("Path", self.path)
        form.addRow("Retries (30/60/120 s)", self.retries)
        self.preview = QLabel()
        row = QHBoxLayout()
        self.send_btn, cancel, posbtn = QPushButton("Send"), QPushButton("Cancel retries"), QPushButton("Send position now…")
        self.send_btn.clicked.connect(lambda: self.send_message())
        cancel.clicked.connect(self.cancel_selected)
        posbtn.clicked.connect(self.send_position)
        for b in (self.send_btn, cancel, posbtn):
            row.addWidget(b)
        self.text.textChanged.connect(self._update_preview)
        self.to.textChanged.connect(self._update_preview)
        for x in (self.msg_lock, self.msg_list):
            v.addWidget(x)
        v.addLayout(form)
        v.addWidget(self.preview)
        v.addLayout(row)
        v.addWidget(QLabel("Outgoing (QUEUED = waiting in Direwolf's queue; 'left queue' is not proof of RF)"))
        v.addWidget(self.outbox)
        return w

    def _gmrs_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.gmrs_status = QLabel()
        self.gmrs_status.setWordWrap(True)
        v.addWidget(self.gmrs_status)
        v.addWidget(QLabel("GMRS data uses only the certified hand-held's own data function (47 CFR §95.1731(d), "
                           "§95.1787, §95.339). Separate settings, attestation and audit from amateur APRS."))
        f = QFormLayout()
        self.g_to, self.g_text = QLineEdit(), QLineEdit()
        self.g_text.setMaxLength(64)
        self.g_lat, self.g_lon = QDoubleSpinBox(), QDoubleSpinBox()
        self.g_lat.setRange(-90, 90)
        self.g_lon.setRange(-180, 180)
        for s in (self.g_lat, self.g_lon):
            s.setDecimals(5)
        f.addRow("Recipient unit", self.g_to)
        f.addRow("Brief text", self.g_text)
        f.addRow("Latitude", self.g_lat)
        f.addRow("Longitude", self.g_lon)
        v.addLayout(f)
        row = QHBoxLayout()
        for label, kind in (("Send location", "location"), ("Request location", "location-request"),
                            ("Send text", "text")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=kind: self.send_gmrs(k))
            row.addWidget(b)
        vid = QPushButton("I identified by voice")
        vid.clicked.connect(self.svc.gmrs.voice_id_done)
        row.addWidget(vid)
        v.addLayout(row)
        self.gmrs_rx = QListWidget()
        v.addWidget(self.gmrs_rx)
        return w

    def _settings_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        a, g = self.svc.amateur_cfg, self.svc.gmrs_cfg
        fa = QFormLayout()
        self.a_tx, self.a_call, self.a_att = QCheckBox("Amateur transmit enabled"), QLineEdit(a.callsign), QLineEdit(a.attestation)
        self.a_tx.setChecked(a.tx_enabled)
        self.radio_box = QComboBox()
        for p in self.svc.profiles:
            self.radio_box.addItem(f"{p.name or p.id} ({'verified' if p.verified else 'UNVERIFIED'})", p.id)
        fa.addRow(QLabel("<b>Amateur APRS (via Direwolf)</b>"))
        fa.addRow(self.a_tx)
        fa.addRow("Your callsign-SSID", self.a_call)
        fa.addRow("Licence attestation", self.a_att)
        fa.addRow("Radio profile", self.radio_box)
        self.dw_info = QLabel("\n".join(self.svc.dw.warnings(a.callsign)) or "Direwolf configuration: no warnings")
        self.dw_info.setWordWrap(True)
        fa.addRow(self.dw_info)
        fg = QFormLayout()
        self.g_tx, self.g_call, self.g_att = QCheckBox("GMRS data transmit enabled"), QLineEdit(g.callsign), QLineEdit(g.attestation)
        self.g_tx.setChecked(g.tx_enabled)
        self.g_auto = QCheckBox("Automatically answer location requests (§95.1787(a)(3))")
        self.g_auto.setChecked(g.auto_reply_location)
        fg.addRow(QLabel("<b>GMRS data (separate licence)</b>"))
        fg.addRow(self.g_tx)
        fg.addRow("GMRS call sign", self.g_call)
        fg.addRow("GMRS licence attestation", self.g_att)
        fg.addRow(self.g_auto)
        save = QPushButton("Save settings")
        save.clicked.connect(self.save_settings)
        v.addLayout(fa)
        v.addLayout(fg)
        v.addWidget(save)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ session
    def _signed_in(self, role="operator"):
        if self.gate is None:
            return False, "no Core connection"
        return self.gate.require(role)

    def toggle_session(self):
        if self.gate is None:
            return
        if self.gate.unlocked:
            self.gate.sign_out()
            self._locked("signed out")
            return
        dlg = SignInDialog(self)
        if dlg.exec() == QDialog.Accepted:
            try:
                self.gate.sign_in(dlg.user.text(), dlg.secret.text())
            except Exception as exc:          # CoreError / OSError: show, never log the secret
                QMessageBox.warning(self, "Sign in", f"Sign in failed: {exc}")
                return
            if self.history_factory:
                self.history = self.history_factory()
            self._refresh(None)

    def _locked(self, reason):
        if self.history is not None:
            self.history.close()
            self.history = None
        self.msg_list.clear()
        self._refresh(None)

    # ------------------------------------------------------------ actions
    def connect_direwolf(self):
        self.svc.connect()
        self._refresh(None)

    def _update_preview(self):
        try:
            frame, n = self.svc.amateur.preview("message", self.to.text(), self.text.text() or " ",
                                                path=self.path.text())
            self.preview.setText(f"Frame: {frame}   ({len(self.text.text())}/67)")
        except ValueError as exc:
            self.preview.setText(str(exc))

    def _confirm_and_retry(self, d, fn):
        if d.needs_confirmation and not d.reasons:
            if QMessageBox.question(self, "Confirm", "\n".join(d.needs_confirmation) + "\n\nSend anyway?") \
                    == QMessageBox.Yes:
                return fn(("duplicate",))
        QMessageBox.information(self, "Not sent", _refusal_text(d))

    def send_message(self, confirmed=()):
        ok, why = self._signed_in()
        if not ok:
            QMessageBox.information(self, "Not sent", why)
            return
        try:
            parse_path(self.path.text())
        except ValueError as exc:
            QMessageBox.information(self, "Not sent", str(exc))
            return
        o, d = self.svc.amateur.send("message", addressee=self.to.text(), text=self.text.text(),
                                     retries=self.retries.value(), path=self.path.text(), confirmed=confirmed)
        if o is None:
            return self._confirm_and_retry(d, self.send_message)
        if self.history is not None:
            self.history.add(time.time(), "amateur", "out", o.addressee, self.text.text(), o.msg_id, o.state)
        self.text.clear()
        self._refresh(o)

    def send_position(self):
        ok, why = self._signed_in()
        if not ok:
            QMessageBox.information(self, "Not sent", why)
            return
        dlg = QDialog(self)
        f = QFormLayout(dlg)
        lat, lon = QDoubleSpinBox(), QDoubleSpinBox()
        lat.setRange(-90, 90)
        lon.setRange(-180, 180)
        lat.setDecimals(5)
        lon.setDecimals(5)
        f.addRow("Latitude (typed or from gpsd)", lat)
        f.addRow("Longitude", lon)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        o, d = self.svc.amateur.send("position", lat=lat.value(), lon=lon.value(), path=self.path.text())
        if o is None:
            QMessageBox.information(self, "Not sent", _refusal_text(d))
        self._refresh(o)

    def cancel_selected(self):
        r = self.outbox.currentRow()
        if r >= 0:
            item = self.outbox.item(r, 0)
            self.svc.amateur.cancel(item.data(256))
            self._refresh(None)

    def send_gmrs(self, kind, confirmed=()):
        ok, why = self._signed_in()
        if not ok:
            QMessageBox.information(self, "Not sent", why)
            return
        sent, d = self.svc.gmrs.send(kind, recipient=self.g_to.text().strip(), text=self.g_text.text(),
                                     lat=self.g_lat.value(), lon=self.g_lon.value(), confirmed=confirmed)
        if not sent:
            return self._confirm_and_retry(d, lambda c: self.send_gmrs(kind, c))
        msg = "Requested from the radio (SIMULATION — nothing transmitted)" if "SIMULATION" in self.svc.gmrs.status() \
            else "Requested from the radio"
        if d.reminders:
            msg += "\n" + "\n".join(d.reminders)
        QMessageBox.information(self, "GMRS", msg)

    def save_settings(self):
        ok, why = self._signed_in("administrator")
        if not ok:
            QMessageBox.information(self, "Settings", f"Changing transmit settings: {why}")
            return
        a, g = self.svc.amateur_cfg, self.svc.gmrs_cfg
        today = datetime.date.today().isoformat()
        a.tx_enabled, a.callsign = self.a_tx.isChecked(), self.a_call.text().strip().upper()
        if self.a_att.text().strip() != a.attestation:
            a.attestation, a.attestation_date = self.a_att.text().strip(), today
        g.tx_enabled, g.callsign = self.g_tx.isChecked(), self.g_call.text().strip().upper()
        g.auto_reply_location = self.g_auto.isChecked()
        if self.g_att.text().strip() != g.attestation:
            g.attestation, g.attestation_date = self.g_att.text().strip(), today
        config.save_amateur(a, self.svc.conf_root)
        config.save_gmrs(g, self.svc.conf_root)
        self.svc.selected = self.radio_box.currentData()
        self._refresh(None)

    # ------------------------------------------------------------ refresh
    def _tick(self):
        self.svc.tick()
        self._refresh(None)

    def _refresh(self, obj):
        t = self.svc.transport
        self.conn_label.setText(f"Direwolf: {t.name} connected" if t else
                                f"Direwolf: not connected{(' — ' + self.svc.last_error) if self.svc.last_error else ''}")
        self.queued_label.setText("QUEUED" if self.svc.amateur.queued() else "")
        unlocked = self.gate is not None and self.gate.unlocked
        self.session_btn.setText("Sign out" if unlocked else "Sign in")
        self.msg_lock.setVisible(not unlocked)
        self.msg_list.setVisible(unlocked)
        self.gmrs_status.setText("GMRS: " + self.svc.gmrs.status())
        if obj is not None and hasattr(obj, "raw") and hasattr(obj, "source"):
            self.monitor.appendPlainText(f"{_ts(obj.time)} {obj.source}>{obj.dest} [{obj.kind}] {obj.summary()}")
        st = sorted(self.svc.rx.stations.values(), key=lambda s: -s.last_heard)
        self.stations.setRowCount(len(st))
        for i, s in enumerate(st):
            pos = f"{s.lat:.4f}, {s.lon:.4f}" if s.lat is not None else "—"
            for j, val in enumerate((s.call, _ts(s.last_heard), pos, s.kind, s.via)):
                self.stations.setItem(i, j, QTableWidgetItem(val))
        items = list(self.svc.amateur.items.values())
        self.outbox.setRowCount(len(items))
        for i, o in enumerate(reversed(items)):
            cells = (o.addressee or o.kind, o.msg_id or "—", o.state, o.history[-1][2] if o.history else "")
            for j, val in enumerate(cells):
                it = QTableWidgetItem(val)
                if j == 0:
                    it.setData(256, o.local_id)
                self.outbox.setItem(i, j, it)
        self.gmrs_rx.clear()
        for p in self.svc.gmrs.received[-200:]:
            self.gmrs_rx.addItem(f"{_ts(p.ts)} {p.sender} {p.kind} " +
                                 (f"{p.lat:.4f},{p.lon:.4f}" if p.lat is not None else (p.text if unlocked else "")))
