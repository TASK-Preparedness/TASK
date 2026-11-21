# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""System: read-only host information collected in a background thread (sysinfo.Collector) every
2 s while the window is open, plus the task-core link and the network indicator source."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from task_launcher.sysinfo import Collector, fmt_bytes, fmt_duration
from task_launcher.workers import PollWorker

DASH = "—"


class SystemWindow(QWidget):
    def __init__(self, link, net_fn, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("System")
        self.link = link
        self.net_fn = net_fn
        self.resize(760, 680)
        lay = QVBoxLayout(self)
        self.fields = {}
        for title, keys in (("Host", ["Hostname", "Operating system", "Kernel", "Architecture", "Uptime"]),
                            ("Load", ["CPU usage (calculated)", "Load average (1/5/15 min)", "Memory",
                                      "CPU temperature"]),
                            ("Storage", ["Storage"]),
                            ("task-core", ["Core link", "Core version", "Core health", "Core uptime"]),
                            ("Network (read-only)", ["Network", "Internet", "Source"])):
            g = QGroupBox(title)
            f = QFormLayout(g)
            for k in keys:
                lab = QLabel(DASH)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lab.setWordWrap(True)
                f.addRow(k, lab)
                self.fields[k] = lab
            lay.addWidget(g)
        note = QLabel("Values are read from /proc, /sys, /etc/os-release and statvfs as your user; "
                      "unreadable values show —. Nothing here changes the system.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.worker = None
        link.changed.connect(lambda _w: self.update_core())
        self.update_core()

    def showEvent(self, e):
        super().showEvent(e)
        if self.worker is None:
            self.worker = PollWorker(Collector(), 2.0, "system-info", self)
            self.worker.result.connect(self.apply)
            self.worker.start()
        self.update_core()
        self.update_net()

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker = None

    def set(self, key, value):
        self.fields[key].setText(value if value not in (None, "") else DASH)

    def apply(self, d):
        if not isinstance(d, dict):
            return
        self.set("Hostname", d.get("hostname"))
        self.set("Operating system", d.get("os"))
        self.set("Kernel", d.get("kernel"))
        self.set("Architecture", d.get("arch"))
        self.set("Uptime", fmt_duration(d.get("uptime")) if d.get("uptime") is not None else None)
        pct = d.get("cpu_percent")
        self.set("CPU usage (calculated)", f"{pct:.1f} % (from /proc/stat over 2 s)" if pct is not None else None)
        ld = d.get("load")
        self.set("Load average (1/5/15 min)", " / ".join(f"{x:.2f}" for x in ld) if ld else None)
        m = d.get("memory")
        self.set("Memory", f"{fmt_bytes(m['used'])} used of {fmt_bytes(m['total'])} "
                           f"({fmt_bytes(m['available'])} available)" if m else None)
        t = d.get("temperature")
        self.set("CPU temperature", f"{t[0]:.1f} °C ({t[1]})" if t else "Unavailable (no readable thermal zone)")
        st = d.get("storage") or []
        self.set("Storage", "\n".join(f"{s['mount']}: {fmt_bytes(s['used'])} used of {fmt_bytes(s['total'])}, "
                                      f"{fmt_bytes(s['free'])} free" for s in st) or None)
        self.update_net()

    def update_core(self):
        text, _c = self.link.footer_text()
        self.set("Core link", text)
        self.set("Core version", self.link.version())
        h = self.link.health if self.link.live else None
        self.set("Core health", ("reports ok" if h.get("ok") is True else "reports not ok") if isinstance(h, dict) else None)
        up = h.get("uptime_seconds") if isinstance(h, dict) else None
        self.set("Core uptime", fmt_duration(up) if isinstance(up, int) else None)

    def update_net(self):
        n = self.net_fn()
        if n is None:
            return
        self.set("Network", n.network + (f" — {n.detail}" if n.detail else ""))
        self.set("Internet", n.internet)
        self.set("Source", {"networkmanager": "NetworkManager (D-Bus, read-only)",
                            "sysfs": "/sys/class/net (NetworkManager not reachable)"}.get(n.source, "none"))
