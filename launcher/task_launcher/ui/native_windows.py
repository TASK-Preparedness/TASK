# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A native windows: Library (Kiwix), Radio / APRS (Direwolf status + receive-only monitor),
Weather (honest local-data status) and Medical (offline reference finder).

All blocking work (HTTP to the local kiwix-serve, the KISS receive loop) runs in worker threads;
results come back through queued signals. Every window says what it is and what it is not.
"""

import html
import os
import threading
import time

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTextBrowser, QVBoxLayout, QWidget)

from task_launcher.registry.registry import XDG_OPEN
from task_launcher.services import aprs, kiwix, medical
from task_launcher.services.readiness import _cap_text
from task_launcher.theme import C
from task_launcher.workers import PollWorker

DASH = "—"
MAX_PACKETS = 2000
DOC_CSS = f"a {{ color: {C['accent']}; }}"


def _esc(x):
    return html.escape(str(x)) if x not in (None, "") else DASH


def open_external(mw, key, target):
    """Hand a loopback URL or an absolute local path to the desktop (xdg-open, argv only)."""
    if not (target.startswith("http://localhost:") or target.startswith("http://127.0.0.1:") or
            target.startswith("/")):
        mw.home.show_notice("error", "Refused: only local files and localhost URLs are opened.")
        return None
    if not (os.path.isfile(XDG_OPEN) and os.access(XDG_OPEN, os.X_OK)):
        mw.home.show_notice("error", "xdg-open is not installed; cannot open the system browser/viewer.")
        return None
    return mw.procs.start(key, [XDG_OPEN, target], single_instance=False)


class _Base(QWidget):
    title = ""
    probe_key = ""

    def __init__(self, mw):
        super().__init__(None, Qt.WindowType.Window)
        self.mw = mw
        self.setWindowTitle(self.title)
        self.resize(1000, 560)
        self.setMinimumSize(640, 420)
        self.lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.heading = QLabel(self.title)
        self.heading.setProperty("role", "heading")
        top.addWidget(self.heading, 1)
        self.checked = QLabel("")
        self.checked.setProperty("role", "muted")
        top.addWidget(self.checked)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        self.lay.addLayout(top)
        self.workers = []

    def refresh(self):
        self.checked.setText("checking…")
        self.mw.refresh_probes()

    def probes_updated(self):
        self.checked.setText("checked " + time.strftime("%H:%M:%S"))
        self.render()

    def render(self):  # pragma: no cover - overridden
        pass

    def run_bg(self, fn, done, name):
        w = PollWorker(fn, 0, name, self, once=True)
        w.result.connect(done)
        w.finished.connect(lambda: self._reap(w))
        self.workers.append(w)
        w.start()
        return w

    def _reap(self, w):
        if w in self.workers:
            self.workers.remove(w)
        w.stop()

    def stop(self):
        for w in list(self.workers):
            w.stop()
        self.workers = []

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)


# ====================================================================== Library

class LibraryView(QTextBrowser):
    """Simple HTML reader: never loads remote resources (images show their alt text) and never runs
    scripts (QTextBrowser has no script engine). Links are handled by the window."""

    def loadResource(self, rtype, url):
        return None


class LibraryWindow(_Base):
    title = "Library"

    def __init__(self, mw):
        super().__init__(mw)
        self.status = QLabel("Looking for the local Kiwix server…")
        self.status.setWordWrap(True)
        self.lay.addWidget(self.status)
        self.details = QLabel("")
        self.details.setProperty("role", "muted")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lay.addWidget(self.details)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Collections"))
        self.books = QListWidget()
        self.books.setAccessibleName("Kiwix collections")
        self.books.currentRowChanged.connect(self._book_selected)
        ll.addWidget(self.books, 1)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        sr = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search in the selected collection")
        self.query.returnPressed.connect(self.do_search)
        sr.addWidget(self.query, 1)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.do_search)
        sr.addWidget(self.search_btn)
        self.main_btn = QPushButton("Main page")
        self.main_btn.clicked.connect(self.open_main)
        sr.addWidget(self.main_btn)
        self.browser_btn = QPushButton("Open in browser")
        self.browser_btn.setToolTip("Documented fallback: opens the page from the local kiwix-serve in the "
                                    "desktop's web browser (localhost only).")
        self.browser_btn.clicked.connect(self.open_browser)
        sr.addWidget(self.browser_btn)
        rl.addLayout(sr)
        self.results = QListWidget()
        self.results.setAccessibleName("Search results")
        self.results.itemActivated.connect(self._hit_activated)
        self.results.setMaximumHeight(170)
        rl.addWidget(self.results)
        self.view = LibraryView()
        self.view.document().setDefaultStyleSheet(DOC_CSS)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link_clicked)
        self.view.setPlaceholderText("Select a collection, then search or open its main page.\n"
                                     "Simple text view: no images or scripts. Use “Open in browser” for the "
                                     "full page.")
        rl.addWidget(self.view, 1)
        split.addWidget(right)
        split.setSizes([300, 700])
        self.lay.addWidget(split, 1)
        self.current_url = ""
        self.render()

    @property
    def st(self):
        return self.mw.probes.kiwix

    def selected_book(self):
        st, row = self.st, self.books.currentRow()
        if st is None or row < 0 or row >= len(st.books):
            return None
        return st.books[row]

    def render(self):
        st = self.st
        prev = self.selected_book().name if self.selected_book() else None
        self.books.blockSignals(True)
        self.books.clear()
        if st is None:
            self.status.setText("Looking for the local Kiwix server… (background check)")
            self.details.setText("")
        else:
            if st.endpoint:
                e = st.endpoint
                self.status.setText(f"Kiwix server: {e.label} — verified (found via {e.source})."
                                    + (" Legacy catalog API." if e.legacy_catalog else ""))
                self.status.setProperty("role", "")
            else:
                self.status.setText("No reachable Kiwix server. " + st.summary() +
                                    ". Content can only be read while kiwix-serve runs; the launcher does "
                                    "not start it.")
                self.status.setProperty("role", "warn")
            self.status.style().polish(self.status)
            lines = []
            for c in st.candidates:
                lines.append(f"{c.label}: {'verified' if c.verified else 'not reachable (' + (c.error or '—') + ')'}"
                             f" — {c.source}")
            for path, exists, n in st.library_files:
                lines.append(f"library file {path}: " + (f"{n} book(s)" if exists else "not present"))
            if st.catalog_error:
                lines.append("catalog: " + st.catalog_error)
            self.details.setText("\n".join(lines[:8]))
            for b in st.books:
                meta = " · ".join(x for x in (b.language, f"{b.articles} articles" if b.articles else "",
                                              "file missing" if b.file_present is False else "") if x)
                it = QListWidgetItem(f"{b.title or b.name}\n{meta or DASH}")
                it.setToolTip(b.summary or b.name)
                self.books.addItem(it)
            if prev:
                for i, b in enumerate(st.books):
                    if b.name == prev:
                        self.books.setCurrentRow(i)
        self.books.blockSignals(False)
        online = bool(st and st.endpoint)
        for w in (self.query, self.search_btn, self.main_btn, self.browser_btn):
            w.setEnabled(online)

    def select_book(self, name):
        for i, b in enumerate(self.st.books if self.st else []):
            if b.name == name:
                self.books.setCurrentRow(i)
                return True
        return False

    def _book_selected(self, _row):
        self.results.clear()

    def do_search(self):
        b, st = self.selected_book(), self.st
        text = self.query.text().strip()
        if not (b and st and st.endpoint and text):
            return
        self.results.clear()
        self.results.addItem("Searching…")
        ep = st.endpoint
        self.run_bg(lambda: kiwix.search(ep, b, text), self._search_done, "kiwix-search")

    def _search_done(self, res):
        self.results.clear()
        if res is None:
            self.results.addItem("Search failed.")
            return
        if res.error:
            self.results.addItem("Search error: " + res.error)
            return
        if not res.hits:
            self.results.addItem("No results.")
            return
        for h in res.hits:
            it = QListWidgetItem(f"{h.title} — {h.snippet[:140]}")
            it.setData(Qt.ItemDataRole.UserRole, h.href)
            self.results.addItem(it)

    def _hit_activated(self, item):
        href = item.data(Qt.ItemDataRole.UserRole)
        if href:
            self.load(kiwix.absolute(self.st.endpoint, href))

    def open_main(self):
        b, st = self.selected_book(), self.st
        if not (b and st and st.endpoint):
            return
        href = b.content_href or f"content/{b.name}"
        self.load(kiwix.absolute(st.endpoint, href))

    def load(self, url):
        st = self.st
        if not url or not st or not st.endpoint:
            self.view.setHtml("<p>This link points outside the local Kiwix server and was not opened.</p>")
            return
        ep = st.endpoint
        self.view.setHtml("<p>Loading…</p>")
        self.run_bg(lambda: kiwix.fetch_page(ep, url), self._page_done, "kiwix-page")

    def _page_done(self, res):
        if not res:
            return
        url, body, err = res
        self.current_url = url
        if err:
            self.view.setHtml(f"<p><b>Could not show this page:</b> {_esc(err)}</p>")
            return
        self.view.setHtml(body)

    def _link_clicked(self, qurl: QUrl):
        st = self.st
        if not st or not st.endpoint:
            return
        target = kiwix.absolute(st.endpoint, kiwix.urljoin(self.current_url or st.endpoint.base_url, qurl.toString()))
        if not target:
            self.mw.home.show_notice("info", "External link not opened (offline-first; outside the local library).")
            return
        self.load(target)

    def open_browser(self):
        st = self.st
        if not st or not st.endpoint:
            return
        url = self.current_url
        if not url:
            b = self.selected_book()
            url = kiwix.absolute(st.endpoint, (b.content_href or f"content/{b.name}")) if b else st.endpoint.base_url
        open_external(self.mw, "app:task.library#browser", kiwix.browser_url(url))


# ====================================================================== Radio / APRS

class MonitorThread(QThread):
    packet = Signal(object)
    stopped = Signal(str)

    def __init__(self, port, parent=None, connect=aprs.ReceiveOnlySocket):
        super().__init__(parent)
        self.port = port
        self._stop = threading.Event()
        self._connect = connect

    def run(self):
        reason = aprs.monitor(self.port, self.packet.emit, self._stop.is_set, connect=self._connect)
        self.stopped.emit(reason)

    def stop(self, timeout_ms=3000):
        self._stop.set()
        if self.isRunning():
            self.wait(timeout_ms)


class RadioWindow(_Base):
    title = "Radio / APRS"
    COLS = ("Time", "From", "To / path", "Type", "Decoded")

    def __init__(self, mw):
        super().__init__(mw)
        banner = QLabel("RECEIVE ONLY. This window never transmits, never sends anything to the TNC and never "
                        "starts or configures Direwolf.")
        banner.setProperty("role", "warn")
        banner.setWordWrap(True)
        self.lay.addWidget(banner)
        self.info = QLabel(DASH)
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lay.addWidget(self.info)
        row = QHBoxLayout()
        row.addWidget(QLabel("KISS TCP port:"))
        self.port = QComboBox()
        row.addWidget(self.port)
        self.start_btn = QPushButton("Start monitor")
        self.start_btn.clicked.connect(self.start_monitor)
        row.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_monitor)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        self.mon_state = QLabel("monitor stopped")
        self.mon_state.setProperty("role", "muted")
        row.addWidget(self.mon_state, 1)
        self.lay.addLayout(row)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        for i in range(4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.lay.addWidget(self.table, 1)
        self.monitor = None
        self.render()

    @property
    def st(self):
        return self.mw.probes.direwolf

    def render(self):
        st = self.st
        if st is None:
            self.info.setText("Checking Direwolf… (background)")
            self.start_btn.setEnabled(False)
            return
        rows = [("Status", st.summary()), ("Direwolf program", st.binary or "not installed")]
        rows.append(("Processes", ", ".join(f"pid {p.pid}" for p in st.processes) or "none running"))
        rows.append(("systemd units", ", ".join(f"{u.name} ({u.scope}: {u.active}/{u.sub})" for u in st.units)
                     or "none found"))
        if st.configs:
            for c in st.configs:
                if not c.readable:
                    rows.append((f"Config {c.path}", f"not readable: {c.error}"))
                    continue
                rows.append((f"Config {c.path}",
                             f"MYCALL {', '.join(c.mycall) or DASH} · ADEVICE {'; '.join(c.adevice) or DASH} · "
                             f"PTT {'; '.join(c.ptt) or 'none'} · MODEM {'; '.join(c.modem) or DASH} · "
                             f"KISSPORT {', '.join(map(str, c.effective_kiss_ports)) or 'disabled'} · "
                             f"AGWPORT {c.effective_agw_port or 'disabled'}"
                             + (f" · beacons {c.beacons}" if c.beacons else "")
                             + (f" · digipeater" if c.digipeat else "")
                             + (f" · IGate {c.igserver} login {c.iglogin}" if c.igserver else "")
                             + (" · TRANSMIT-CAPABLE configuration (Direwolf may transmit on its own)"
                                if c.transmit_capable else "")))
        else:
            rows.append(("Configuration", "no direwolf.conf found (checked -c argument, process directory, "
                                          "~/direwolf.conf, /etc/direwolf.conf)"))
        ports = ", ".join(f"{p} {'open' if ok else 'closed'}" for p, ok in st.kiss_open.items()) or DASH
        agw = ", ".join(f"{p} {'open' if ok else 'closed'}" for p, ok in st.agw_open.items()) or DASH
        rows.append(("Local ports (connect-only check)", f"KISS {ports} · AGW {agw}"))
        self.info.setText("<table>" + "".join(f"<tr><td><b>{_esc(k)}</b>&nbsp;&nbsp;</td><td>{_esc(v)}</td></tr>"
                                              for k, v in rows) + "</table>")
        cur = self.port.currentData()
        self.port.clear()
        for p, ok in st.kiss_open.items():
            self.port.addItem(f"{p} ({'open' if ok else 'closed'})", p)
        if cur is not None:
            i = self.port.findData(cur)
            if i >= 0:
                self.port.setCurrentIndex(i)
        self.start_btn.setEnabled(self.monitor is None and any(st.kiss_open.values()))

    def start_monitor(self, connect=aprs.ReceiveOnlySocket):
        port = self.port.currentData()
        if port is None or self.monitor is not None:
            return None
        self.monitor = MonitorThread(port, self, connect)
        self.monitor.packet.connect(self._on_packet)
        self.monitor.stopped.connect(self._on_stopped)
        self.monitor.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.mon_state.setText(f"connecting to {port} (receive only)…")
        return self.monitor

    def stop_monitor(self):
        if self.monitor is not None:
            self.monitor.stop()

    def _on_stopped(self, reason):
        self.mon_state.setText(f"monitor stopped: {reason}")
        m, self.monitor = self.monitor, None
        if m is not None:
            m.wait(1000)
        self.stop_btn.setEnabled(False)
        self.render()

    def _on_packet(self, p):
        if isinstance(p, str):
            self.mon_state.setText(p)
            return
        if self.table.rowCount() >= MAX_PACKETS:
            self.table.removeRow(0)
        r = self.table.rowCount()
        self.table.insertRow(r)
        vals = (time.strftime("%H:%M:%S", time.localtime(p.time)), p.source, f"{p.dest} {p.path}".strip(),
                p.kind, (p.summary() or p.raw) + (f" [{p.error}]" if p.error else ""))
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            it.setToolTip(p.raw)
            self.table.setItem(r, c, it)
        self.table.scrollToBottom()

    def stop(self):
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None
        super().stop()


# ====================================================================== Weather

class WeatherWindow(_Base):
    title = "Weather"

    def __init__(self, mw):
        super().__init__(mw)
        note = QLabel("Honest status only: no forecasts are shown unless local weather data exists, and then "
                      "only the data itself with its age. Nothing is downloaded.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.text = QTextBrowser()
        self.text.document().setDefaultStyleSheet(DOC_CSS)
        self.text.setOpenLinks(False)
        self.text.anchorClicked.connect(lambda u: open_external(self.mw, "app:task.weather#open", u.toLocalFile()))
        self.lay.addWidget(self.text, 1)
        self.render()

    def render(self):
        st = self.mw.probes.weather
        if st is None:
            self.text.setHtml("<p>Checking… (background)</p>")
            return
        now = time.time()
        cap = self.mw.link.capability_status("weather.products") if self.mw.link.live else None
        h = [f"<h3>{_esc(st.summary(now))}</h3>",
             f"<p><b>task-core weather.products:</b> {_esc(_cap_text(cap) if cap else 'unknown (Core not connected)')}"
             "</p>", "<h4>Decoders / receivers on this device</h4><ul>"]
        for t in st.tools:
            h.append(f"<li>{_esc(t.name)}: <b>{'installed' if t.installed else 'not installed'}</b>"
                     f"{' — ' + _esc(t.path) if t.path else ''}</li>")
        h.append("</ul><h4>Local data folders</h4>")
        if not st.dirs:
            h.append("<p>None configured. Add folders to <code>~/.config/task-launcher/reference.toml</code> "
                     "under <code>[weather] dirs = [...]</code>.</p>")
        for status, prods in st.dirs:
            h.append(f"<p><b>{_esc(status.path)}</b>: {_esc(status.detail)}</p><ul>")
            for p in prods[:20]:
                h.append(f"<li><a href='{QUrl.fromLocalFile(p.path).toString()}'>{_esc(p.title)}</a> — "
                         f"{_esc(p.kind)}, {_esc(p.age(now))}</li>")
            if status.installed and not prods:
                h.append("<li>no image or log files</li>")
            h.append("</ul>")
        if self.mw.probes.ref_error:
            h.append(f"<p><b>reference.toml:</b> {_esc(self.mw.probes.ref_error)}</p>")
        self.text.setHtml("".join(h))


# ====================================================================== Medical

class MedicalWindow(_Base):
    title = "Medical — offline reference"

    def __init__(self, mw):
        super().__init__(mw)
        banner = QLabel(medical.DISCLAIMER + " Patient records need a separate design (authentication, "
                        "encryption, audit) and are not part of this release.")
        banner.setProperty("role", "warn")
        banner.setWordWrap(True)
        self.lay.addWidget(banner)
        self.list = QListWidget()
        self.list.setAccessibleName("Medical reference items")
        self.list.itemActivated.connect(self._open)
        self.lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(lambda: self._open(self.list.currentItem()))
        row.addStretch(1)
        row.addWidget(self.open_btn)
        self.lay.addLayout(row)
        self.render()

    def render(self):
        st = self.mw.probes.medical
        self.list.clear()
        if st is None:
            self.list.addItem("Checking… (background)")
            return
        if not st.count:
            self.list.addItem("No offline medical reference material found on this device.")
            if not st.kiwix_ready:
                self.list.addItem("(Kiwix server not reachable — Kiwix collections cannot be checked or opened.)")
            for d in st.missing_dirs:
                self.list.addItem(f"Configured folder missing: {d}")
            return
        for b in st.books:
            it = QListWidgetItem(f"Kiwix: {b.title or b.name}  ({b.language or DASH})")
            it.setData(Qt.ItemDataRole.UserRole, ("kiwix", b.name))
            self.list.addItem(it)
        for name, path in st.modules:
            it = QListWidgetItem(f"IIAB module: {name}")
            it.setData(Qt.ItemDataRole.UserRole, ("file", path))
            self.list.addItem(it)
        for folder, files in st.documents:
            for f in files:
                it = QListWidgetItem(f"Document: {os.path.relpath(f, folder)}  ({folder})")
                it.setData(Qt.ItemDataRole.UserRole, ("file", f))
                self.list.addItem(it)

    def _open(self, item):
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return None
        kind, value = data
        if kind == "kiwix":
            lib = self.mw.open_builtin("library")
            lib.select_book(value)
            lib.open_main()
            return lib
        return open_external(self.mw, "app:task.medical#open", value)


def create(which, mw):
    return {"library": LibraryWindow, "radio": RadioWindow, "weather": WeatherWindow,
            "medical": MedicalWindow}[which](mw)
