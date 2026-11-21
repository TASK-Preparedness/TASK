# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Launcher main window: owns the registry, the process manager, the task-core link, the network
and desktop-scan workers, the idle lock and all secondary windows."""

import logging
import os

from PySide6.QtCore import QEvent, QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QVBoxLayout)

from task_launcher import autostart, branding, motion, netstatus
from task_launcher import settings as settings_mod
from task_launcher.launch import ProcessManager, POLL_MS, tail
from task_launcher.layout import layout
from task_launcher.registry import desktop as D
from task_launcher.registry.registry import (DISABLED, ERROR, INSTALLED, PLANNED, QUIET_BUILTINS, UNAVAILABLE,
                                             Registry, files_opener)
from task_launcher.services import readiness as readiness_mod
from task_launcher.theme import C
from task_launcher.ui import iconcache
from task_launcher.ui.dialogs import InfoSheet, SettingsDialog, SignInDialog, effective_layout_text, \
    login_error_text, retry_seconds
from task_launcher.ui.home import HomeView
from task_launcher.ui.widgets import set_keyboard_mode
from task_launcher.workers import PollWorker

logger = logging.getLogger("task_launcher")
RESCAN_DEBOUNCE_MS = 1500
NET_INTERVAL_S = 10.0
PROBE_INTERVAL_S = 30.0
NATIVE_WINDOWS = ("library", "radio", "weather", "medical")
NATIVE_VIEWS = ("medical",)          # Phase 4F.2: shown inside the main window (view stack)
INPUT_EVENTS = {QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.Wheel,
                QEvent.Type.TouchBegin}


class IdleFilter(QObject):
    """Input/idle tracking (auto-lock) and keyboard-focus mode.

    launcher 0.3.7: installed on top-level QWindows, NOT application-wide. An application-wide Python event
    filter makes PySide wrap every QObject that receives any event - including QObjects that are still being
    constructed in C++ (QWebEngineUrlRequestJob's ChildAdded/ParentChange during its constructor). With the
    embedded WebEngine Medical reader that segfaulted the launcher in PySide::getWrapperForQObject on the first
    zim:// request (reproduced on x86, see docs RCA). A QWindow receives every spontaneous input event for its
    widgets before they are dispatched, so idle tracking is unchanged; windows are attached when created/focused
    (QGuiApplication.focusWindowChanged, a signal - no event interception)."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.windows = []            # attached QWindows (strong refs are fine: they live as long as their widget)

    def attach(self, qwindow):
        if qwindow is None or any(w is qwindow for w in self.windows):
            return False
        qwindow.installEventFilter(self)
        self.windows.append(qwindow)
        qwindow.destroyed.connect(lambda *_a, w=qwindow: self._forget(w))
        return True

    def _forget(self, qwindow):
        self.windows = [w for w in self.windows if w is not qwindow]

    def detach_all(self):
        for w in self.windows:
            try:
                w.removeEventFilter(self)
            except RuntimeError:     # already deleted on the C++ side
                pass
        self.windows = []

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et in INPUT_EVENTS:
            self.window.note_input()
            if et == QEvent.Type.KeyPress:
                set_keyboard_mode(True)
            elif et in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
                set_keyboard_mode(False)
        return False


class LockOverlay(QFrame):
    """In-window application lock (never a screen locker, never a grab)."""

    def __init__(self, parent, sign_in, public):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background: rgba(11,13,16,240); }} QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        t = QLabel("Locked — signed out")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"color: {C['text']}; font-size: 32px; font-weight: 600;")
        lay.addWidget(t)
        self.sign_in = QPushButton("Sign in")
        self.public = QPushButton("Continue as public")
        for b in (self.sign_in, self.public):
            b.setFixedWidth(320)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.sign_in.clicked.connect(sign_in)
        self.public.clicked.connect(public)
        self.hide()


class MainWindow(QMainWindow):
    tilesChanged = Signal()

    def __init__(self, link, settings=None, registry=None, procs=None, net_reader=None, desktop_scan=None,
                 start_workers=True, motion_hint_fn=motion.system_animations_enabled, idle_clock=None,
                 probe_fn=None):
        super().__init__()
        import time

        self.link = link
        self.settings = settings or settings_mod.load()
        self.registry = registry or Registry(core_version_fn=link.version)
        self.registry.core_version_fn = link.version
        self.procs = procs or ProcessManager()
        self.procs.listeners.append(self._on_outcome)
        self.runtime = {}            # key -> {"status": Running|Error|Starting, "message", "log"}
        self.files_fallbacks = []
        self.net = None
        self.scanning = False
        self.idle_clock = idle_clock or time.monotonic
        self.last_input = self.idle_clock()
        self.system_window = self.app_manager = self.devices_window = None
        self.native_windows = {}     # library | radio | weather | medical -> window (Phase 4A)
        self.probes = readiness_mod.ProbeResults()
        self._probe_fn = probe_fn or readiness_mod.collect_all
        self.probe_worker = None
        self.sign_in_dialog = None
        self._pending_after_login = None
        self._closing = False
        self.system_animations = None
        self.home = HomeView()
        # Phase 4F.2: view stack — Home is page 0; native views (Medical) are pages inside this window.
        from PySide6.QtWidgets import QStackedWidget
        self.views = QStackedWidget()
        self.views.addWidget(self.home)
        self.view_pages = {}
        self.view_history = []
        self.setCentralWidget(self.views)
        self.overlay = LockOverlay(self.home, self.request_sign_in, self.link.continue_public)
        self.setMinimumSize(800, 480)
        self.home.auth_chip.clicked.connect(self._auth_clicked)
        self.home.settings_btn.clicked.connect(self.open_settings)
        self.home.net_chip.clicked.connect(lambda: self.open_builtin("system"))
        self.home.tileActivated.connect(self.activate)
        self.home.tileMenu.connect(self.tile_menu)
        self.home.moveRequested.connect(self.move_tile)
        self.home.removeRequested.connect(lambda k: self.remove_tile(k, confirm_parent=self))
        link.changed.connect(self._link_changed)
        link.notice.connect(lambda sev, text: self.home.show_notice(sev, text))
        link.lockChanged.connect(self._lock_changed)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.procs.poll)
        self._poll.start(POLL_MS)
        self._tick = QTimer(self)               # footer retry countdown + idle check
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(1000)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.timeout.connect(self.rescan)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self._rescan_timer.start(RESCAN_DEBOUNCE_MS))
        self._idle_filter = IdleFilter(self)          # per-window, never application-wide (0.3.7, see IdleFilter)
        QApplication.instance().focusWindowChanged.connect(self._idle_filter.attach)
        self._desktop_scan = desktop_scan or self.registry.scan_desktop
        self._net_reader = net_reader
        self._motion_hint_fn = motion_hint_fn
        self.workers = []
        self._shortcuts()
        self.apply_settings(rebuild=False)
        self.rebuild()
        self._link_changed("link")
        if start_workers:
            self.start_workers()

    # ------------------------------------------------------------------ workers
    def start_workers(self):
        reader = self._net_reader
        net = PollWorker((lambda: netstatus.collect(reader)) if reader else netstatus.collect, NET_INTERVAL_S,
                         "network-status", self)
        net.result.connect(self._on_net)
        net.start()
        self.workers.append(net)
        if self._motion_hint_fn is not None and self.settings.reduce_motion == "system":
            mw = PollWorker(self._motion_hint_fn, 0, "motion-hint", self, once=True)
            mw.result.connect(self._on_motion_hint)
            mw.start()
            self.workers.append(mw)
        pw = PollWorker(self._probe_fn, PROBE_INTERVAL_S, "readiness-probes", self)
        pw.result.connect(self._on_probes)
        pw.start()
        self.workers.append(pw)
        self.probe_worker = pw
        self.rescan()
        for d in D.application_dirs():
            if d.is_dir():
                self.watcher.addPath(str(d))

    def stop_workers(self):
        for w in self.workers:
            w.stop()
        self.workers = []
        self.probe_worker = None
        for w in (self.system_window,) + tuple(self.native_windows.values()):
            if w is not None and hasattr(w, "stop"):
                w.stop()

    def _on_probes(self, result):
        """Probe results arrive on the GUI thread (queued signal from the worker)."""
        if not isinstance(result, dict):
            return
        for k, v in result.items():
            setattr(self.probes, k, v)
        self.refresh_states()
        for w in list(self.native_windows.values()) + list(self.view_pages.values()):
            if hasattr(w, "probes_updated"):
                w.probes_updated()
        if self.app_manager is not None:
            self.app_manager.render_detail()

    def refresh_probes(self):
        """Run the readiness probes again now (window Refresh buttons)."""
        if self.probe_worker is not None:
            self.probe_worker.poke()

    def rescan(self):
        """Non-blocking rescan of installed desktop applications (and manifests)."""
        if self.scanning:
            self._rescan_timer.start(RESCAN_DEBOUNCE_MS)
            return
        self.scanning = True
        self.registry.reload_manifests()
        w = PollWorker(self._desktop_scan, 0, "desktop-scan", self, once=True)
        w.result.connect(self._on_scan)
        w.finished.connect(lambda: self._reap(w))
        self.workers.append(w)
        w.start()
        self._refresh_children()

    def _reap(self, w):
        if w in self.workers:
            self.workers.remove(w)
        w.stop()

    def _on_scan(self, entries):
        self.scanning = False
        if isinstance(entries, dict):
            self.registry.set_desktop_entries(entries)
        iconcache.clear_cache()
        self.rebuild()

    def _on_net(self, st):
        if st is None:
            return
        self.net = st
        icon = {"wifi": "wifi", "wired": "network", "none": "wifi-off", "other": "network"}.get(st.kind, "wifi")
        colour = C["text"] if st.up else C["text2"]
        self.home.net_chip.set_content(icon, st.network, colour)
        self.home.net_chip.setToolTip(f"Source: {st.source}" + (f" — {st.detail}" if st.detail else ""))
        self.home.set_internet(st.internet)
        if self.system_window is not None:
            self.system_window.update_net()

    def _on_motion_hint(self, enabled):
        self.system_animations = enabled
        self._apply_motion()

    def _apply_motion(self):
        self.home.pager.reduce_motion = motion.effective_reduce(self.settings.reduce_motion, self.system_animations)

    # ------------------------------------------------------------------ settings
    def apply_settings(self, rebuild=True):
        s = self.settings
        if s.branding == "default":
            title, subtitle = branding.resolve(None)
        else:
            title, subtitle = branding.resolve(s.branding, s.custom_title, s.custom_subtitle)
        self.setWindowTitle(title)
        self.home.set_branding(title, subtitle)
        self.home.set_layout_mode(s.layout, s.scale)
        from task_launcher.theme import stylesheet

        app = QApplication.instance()
        css = stylesheet(s.scale)
        if app.styleSheet() != css:        # re-polishing every widget is expensive; only on change
            app.setStyleSheet(css)
        self._apply_motion()
        if rebuild:
            self.rebuild()

    def open_settings(self):
        about = {"core": self.link.version()}
        try:
            from PySide6 import __version__ as pv
            from PySide6.QtCore import qVersion

            from task_launcher.fonts import choose_family

            about.update(qt=qVersion(), pyside=pv, font=choose_family())
        except Exception:
            pass
        dlg = SettingsDialog(self.settings, effective_layout_text(self.home.width, self.home.height), about, self)
        dlg.accepted.connect(lambda: self._settings_accepted(dlg))
        dlg.show()
        return dlg

    def _settings_accepted(self, dlg):
        self.settings = dlg.result_settings()
        try:
            settings_mod.save(self.settings)
        except OSError as exc:
            self.home.show_notice("error", f"Settings could not be saved: {exc.strerror or exc}")
        want = dlg.autostart_wanted()
        try:
            if want is True and not autostart.is_enabled():
                autostart.enable(self.windowTitle())
            elif want is False and autostart.is_enabled():
                autostart.disable()
        except (OSError, FileExistsError) as exc:
            self.home.show_notice("error", f"Autostart: {exc}")
        self.apply_settings()

    # ------------------------------------------------------------------ tiles
    def rebuild(self):
        tiles = self.registry.build(show_planned=self.settings.show_planned)
        self.home.set_tiles(tiles)
        self.refresh_states()
        self._refresh_children()
        self.tilesChanged.emit()

    def _refresh_children(self):
        if self.app_manager is not None:
            self.app_manager.refresh()

    def display_state(self, t):
        """(style key, state line) combining static status, runtime state and the role gate."""
        rt = self.runtime.get(t.key)
        if rt and rt["status"] == "Running":
            return "Running", "● Running"
        if rt and rt["status"] == "Error":
            return "Error", f"Error — {rt['message']}"
        if t.status == PLANNED:
            return "Planned", "Planned"
        if t.status == DISABLED:
            return "Disabled", "Disabled"
        if t.status == ERROR:
            return "Error", f"Error — {t.reason}"
        if t.status == UNAVAILABLE:
            return "Unavailable", f"Unavailable — {t.reason}"
        if not self.link.at_least(t.min_role):
            return "SignIn", "Sign in to use"
        if t.source == "desktop" or t.builtin in QUIET_BUILTINS:
            return "Available", ""
        note = t.variant or (t.manifest.status_note if t.manifest else "")
        return "Available", "Available" + (f" — {note}" if note else "")

    def ready_state(self, t):
        """(text, level) secondary readiness line, or None. Display only (never changes status)."""
        if not t.readiness or t.status in (PLANNED, DISABLED, ERROR):
            return None
        r = self.probes.line(t.readiness, self.link)
        return (r.text, r.level) if r and r.text else None

    def refresh_states(self):
        for w in self.home.tiles:
            w.set_state(*self.display_state(w.tile), ready=self.ready_state(w.tile))

    def _on_outcome(self, out):
        key = out.key
        if out.status == "running":
            self.runtime[key] = {"status": "Running", "message": "", "log": out.log_path}
        elif out.status == "exited":
            self.runtime.pop(key, None)
        elif out.status == "error":
            if key == "app:task.files" and self.files_fallbacks:
                nxt = self.files_fallbacks.pop(0)
                self.procs.start(key, [nxt, os.path.expanduser("~")], single_instance=False)
                return
            self.runtime[key] = {"status": "Error", "message": out.message, "log": out.log_path,
                                 "tail": (out.extra or {}).get("tail", "")}
            t = self.registry.get(key)
            self.home.show_notice("error", f"{t.name if t else key}: {out.message}")
        if key == "app:task.files" and out.status in ("exited", "running"):
            self.runtime.pop(key, None)    # the opener is a short-lived helper, not a running app
        self.refresh_states()
        if self.app_manager is not None:
            self.app_manager.render_detail()

    def clear_error(self, key):
        if self.runtime.get(key, {}).get("status") == "Error":
            self.runtime.pop(key, None)
        self.refresh_states()
        self._refresh_children()

    def activate(self, t):
        style, line = self.display_state(t)
        if t.status == PLANNED:
            return self._sheet(t.name, [t.description, f"Status: Planned ({t.reason}).",
                                        "Not installed. No app exists yet; nothing will open."])
        if t.status == DISABLED:
            return self._sheet(t.name, [t.description, "Disabled in App Manager (per user)."],
                               [("Open App Manager", lambda: self.open_builtin("app-manager"))])
        if t.status == ERROR:
            return self._sheet(t.name, [t.description, f"Error: {t.reason}"])
        if style == "SignIn":
            self._pending_after_login = t.key
            return self.request_sign_in()
        if t.builtin in ("devices", "radio") and t.status == UNAVAILABLE:
            return self.open_builtin(t.builtin)
        if t.app_id == "task.mesh" and t.status == UNAVAILABLE:
            return self._mesh_unavailable_sheet(t)
        if t.status == UNAVAILABLE:
            buttons = [("Remove tile", lambda: self.remove_tile(t.key))] if t.source == "desktop" else []
            lines = [t.description, f"Unavailable: {t.reason}"]
            if t.manifest and t.manifest.candidates():
                lines.append("Looked for: " + ", ".join(a[0] for a in t.manifest.candidates()))
            return self._sheet(t.name, lines, buttons)
        if t.builtin in NATIVE_VIEWS:
            return self.open_view(t.builtin)
        if (t.builtin in ("system", "app-manager") or t.builtin in NATIVE_WINDOWS) and \
                not (t.builtin in ("radio", "library") and t.argv):
            # radio: task-aprs installed -> start it instead of the built-in monitor;
            # library: task-resources installed -> start it instead of the built-in 4A Kiwix viewer.
            return self.open_builtin(t.builtin)
        if t.builtin == "files":
            prefix, how, rest = files_opener()
            if prefix is None:
                return self._sheet(t.name, ["Unavailable: no file manager found."])
            self.files_fallbacks = list(rest) if prefix[0].endswith("xdg-open") else []
            return self.procs.start(t.key, prefix + [os.path.expanduser("~")], single_instance=False)
        if t.argv:
            single = t.manifest.single_instance if t.manifest else True
            if single and self.procs.running(t.key):
                if t.manifest and t.manifest.on_reactivate == "relaunch":
                    return self.procs.start(t.key, t.argv, cwd=t.cwd, helper=True)
                self.home.show_notice("info", f"{t.name} is already running — use the desktop's window switcher.")
                return None
            self.runtime.pop(t.key, None)
            return self.procs.start(t.key, t.argv, cwd=t.cwd, single_instance=single)
        return None

    # ------------------------------------------------------------ in-window views (Phase 4F.2)
    def open_view(self, name):
        """Show a native view inside this window (one instance per view; reopening reuses it). Falls back to the
        legacy built-in window if the view cannot be built."""
        page = self.view_pages.get(name)
        if page is None:
            try:
                from task_launcher.ui.medical_view import MedicalView
                page = {"medical": MedicalView}[name](self)
            except Exception:  # noqa: BLE001
                logger.exception("native view %s failed; using the built-in window", name)
                return self.open_builtin(name)
            self.view_pages[name] = page
            self.views.addWidget(page)
        else:
            page.refresh()
        cur = self.views.currentWidget()
        if cur is not page:
            self.view_history.append(cur)
            self.views.setCurrentWidget(page)
        self.refresh_probes()
        return page

    def go_back(self):
        while self.view_history:
            prev = self.view_history.pop()
            if prev is not self.views.currentWidget():
                self.views.setCurrentWidget(prev)
                return prev
        return self.go_home()

    def go_home(self):
        self.view_history.clear()
        self.views.setCurrentWidget(self.home)
        return self.home

    def open_builtin(self, which):
        if which == "system":
            from task_launcher.ui.system_window import SystemWindow

            if self.system_window is None:
                self.system_window = SystemWindow(self.link, lambda: self.net)
            w = self.system_window
        elif which in NATIVE_WINDOWS:
            w = self.native_windows.get(which)
            if w is None:
                from task_launcher.ui import native_windows as NW

                w = NW.create(which, self)
                self.native_windows[which] = w
            self.refresh_probes()
        elif which == "app-manager":
            from task_launcher.ui.app_manager import AppManagerWindow

            if self.app_manager is None:
                self.app_manager = AppManagerWindow(self)
            w = self.app_manager
            w.refresh()
        else:
            from task_launcher.ui.devices_window import DevicesWindow

            if self.devices_window is None:
                self.devices_window = DevicesWindow(self.link, self.request_sign_in)
            w = self.devices_window
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def _mesh_unavailable_sheet(self, t):
        """Temporary, clearly labelled read-only status while task-mesh is not installed."""
        st = self.probes.mesh
        lines = [t.description, f"Unavailable: {t.reason}.",
                 "Looked for: " + ", ".join(c[0] for c in t.manifest.candidates()),
                 "Install the task-mesh package (task-mesh_0.1.0_arm64.deb) to get the Mesh app. "
                 "The meshtastic command-line tool alone does not count as the Mesh app."]
        status = ["Read-only status (temporary, not the Mesh app):"]
        if self.link.live:
            status.append("• task-core mesh.messaging: " +
                          readiness_mod._cap_text(self.link.capability_status("mesh.messaging")))
        else:
            status.append("• task-core: not connected")
        if st is not None:
            status.append("• meshtastic CLI: " + (st.meshtastic_cli or "not installed"))
            status.append("• USB serial devices (/dev/serial/by-id): " + (", ".join(st.serial_ports) or "none"))
        else:
            status.append("• local checks still running…")
        return self._sheet(t.name, lines + ["\n".join(status)])

    def run_action(self, t, action):
        """Secondary manifest action (e.g. gpsmon in a terminal). argv only, process manager."""
        if action.argv is None:
            return self._sheet(t.name, [f"{action.label}: unavailable — {action.reason}"])
        return self.procs.start(f"{t.key}#{action.id}", action.argv, single_instance=False)

    def _sheet(self, title, lines, buttons=()):
        s = InfoSheet(title, lines, buttons, self)
        s.show()
        return s

    # ------------------------------------------------------------------ customisation
    def tile_menu(self, w, pos):
        t = w.tile
        m = QMenu(self)
        m.addAction("Open", lambda: self.activate(t))
        for act in t.actions:
            if t.argv and act.argv and act.argv[0] == t.argv[0]:
                continue                      # same program as the main action
            a = m.addAction(act.label, lambda _c=False, x=act: self.run_action(t, x))
            if act.argv is None:
                a.setEnabled(False)
                a.setToolTip(act.reason)
        m.addSeparator()
        for label, delta, keys in (("Move left", -1, "Alt+Left"), ("Move right", 1, "Alt+Right"),
                                   ("Move up", -self.home.grid_geom["cols"], "Alt+Up"),
                                   ("Move down", self.home.grid_geom["cols"], "Alt+Down")):
            a = QAction(label, m)
            a.setShortcut(QKeySequence(keys))
            a.triggered.connect(lambda _c=False, d=delta: self.move_tile(t.key, d))
            m.addAction(a)
        m.addSeparator()
        if t.source == "desktop":
            m.addAction("Rename…", lambda: self.rename_tile(t, self))
            m.addAction("Change icon…", lambda: self.change_icon(t, self))
        if t.can_hide:
            m.addAction("Remove from dashboard", lambda: self.remove_tile(t.key, confirm_parent=self))
        m.addAction("Details in App Manager", lambda: self.open_builtin("app-manager"))
        if pos is None:
            pos = w.mapToGlobal(w.rect().center())
        m.popup(pos)
        return m

    def move_tile(self, key, delta):
        self.registry.move(key, delta)
        self.rebuild()
        self.home.focus_tile(key)     # follows the tile across pages (animated)

    def remove_tile(self, key, confirm_parent=None):
        t = self.registry.get(key)
        if t is None or not t.can_hide:
            return False
        if confirm_parent is not None:
            what = ("This removes the tile only; the application stays installed."
                    if t.source == "desktop" else "The tile can be shown again from App Manager.")
            if QMessageBox.question(confirm_parent, "Remove tile", f"Remove “{t.name}” from the dashboard?\n{what}") \
                    != QMessageBox.StandardButton.Yes:
                return False
        self.registry.remove_tile(key)
        self.rebuild()
        return True

    def show_tile(self, key):
        self.registry.store.set_hidden(key, False)
        self.rebuild()

    def add_desktop(self, desktop_id):
        key = self.registry.add_desktop(desktop_id)
        self.rebuild()
        self.home.focus_tile(key)
        return key

    def set_enabled(self, t, enabled):
        self.registry.set_enabled(t, enabled)
        self.rebuild()

    def rename_tile(self, t, parent):
        name, ok = QInputDialog.getText(parent, "Rename tile", "Tile name (empty = the application's name):",
                                        text=self.registry.store.custom_for(t.desktop_id).get("name", ""))
        if ok:
            try:
                self.registry.store.rename(t.desktop_id, name)
            except ValueError as exc:
                QMessageBox.warning(parent, "Rename tile", str(exc))
            self.rebuild()

    def change_icon(self, t, parent):
        from task_launcher.ui.app_manager import IconDialog

        dlg = IconDialog(self.registry.store.custom_for(t.desktop_id).get("icon", ""), parent)
        if dlg.exec() and dlg.value is not None:
            self.registry.store.set_icon(t.desktop_id, dlg.value)
            iconcache.clear_cache()
            self.rebuild()

    def reset_layout(self):
        self.registry.store.reset_layout()
        self.rebuild()

    # ------------------------------------------------------------------ core / auth
    def _link_changed(self, what):
        text, colour = self.link.footer_text()
        self.home.set_core(text, colour)
        if what in ("role", "link"):
            if self.link.signed_in:
                self.home.auth_chip.set_content("circle-user", f"{self.link.username} · {self.link.role}")
            else:
                self.home.auth_chip.set_content("circle-user", "Public · Sign in")
            self.refresh_states()
            if what == "role" and self.link.signed_in and self.link.devices is None and \
                    any(t.readiness in ("rtl-sdr", "mesh") for t in self.registry.tiles):
                self.link.fetch_devices()
        if what in ("devices", "caps", "counts"):
            self.refresh_states()
        if what == "health" or what == "link":
            v = self.link.version()
            if v != getattr(self, "_last_core_version", None):
                self._last_core_version = v
                self.rebuild()

    def _on_tick(self):
        if self.link.link not in ("connected",):
            self.home.set_core(*self.link.footer_text())
        if self.link.signed_in and self.idle_clock() - self.last_input >= self.settings.idle_lock_minutes * 60:
            self.link.lock("idle")

    def note_input(self):
        self.last_input = self.idle_clock()

    def _auth_clicked(self):
        if not self.link.signed_in:
            return self.request_sign_in()
        m = QMenu(self)
        m.addAction("Lock (Ctrl+L)", lambda: self.link.lock("user"))
        m.addAction("Sign out", lambda: self.link.logout())
        m.popup(self.home.auth_chip.mapToGlobal(self.home.auth_chip.rect().bottomLeft()))
        return m

    def request_sign_in(self):
        if self.sign_in_dialog is not None:
            self.sign_in_dialog.raise_()
            return self.sign_in_dialog
        dlg = SignInDialog(self)
        self.sign_in_dialog = dlg
        dlg.finished.connect(lambda _r: setattr(self, "sign_in_dialog", None))
        dlg.submitted.connect(lambda u, p: self._do_login(dlg, u, p))
        dlg.show()
        return dlg

    def _do_login(self, dlg, username, password):
        from shiboken6 import isValid

        def done(reply):
            if not isValid(dlg):
                return
            if reply.get("ok") is True:
                dlg.accept()
                key, self._pending_after_login = self._pending_after_login, None
                if key and self.registry.get(key):
                    self.activate(self.registry.get(key))
                return
            msg = (reply.get("error") or {}).get("message", "")
            dlg.show_error(login_error_text(reply), retry_seconds(msg) if
                           (reply.get("error") or {}).get("code") == "rate-limited" else None)

        self.link.login(username, password, done, still_wanted=lambda: isValid(dlg) and dlg.isVisible())
        password = None  # noqa: F841

    def _lock_changed(self, locked):
        if locked:
            if self.sign_in_dialog is not None:
                self.sign_in_dialog.reject()
            for page in self.view_pages.values():  # Phase 4F.3: lock privacy — clear embedded content
                getattr(page, "lock_hide", lambda: None)()
            self.go_home()                        # Phase 4F.2: the lock overlay covers Home; never leave a view up
            self.overlay.setGeometry(self.home.rect())
            self.overlay.show()
            self.overlay.raise_()
            self.overlay.sign_in.setFocus()
        else:
            self.overlay.hide()

    # ------------------------------------------------------------------ window
    def _shortcuts(self):
        for keys, fn in (("F11", self.toggle_fullscreen), ("Ctrl+L", lambda: self.link.lock("user") if self.link.signed_in else None),
                         ("Ctrl+Shift+S", self.request_sign_in), ("Ctrl+,", self.open_settings),
                         ("F5", self._refresh_all)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(fn)
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(lambda: self.showMaximized() if self.isFullScreen() else None)

    def _refresh_all(self):
        self.link.retry_now()
        self.rescan()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.home.rect())

    def showEvent(self, e):
        super().showEvent(e)
        self._idle_filter.attach(self.windowHandle())     # also without a focus change (no WM / offscreen)

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)

    def shutdown(self):
        """Graceful close: stop workers and timers, revoke the session once, keep launched apps running."""
        if self._closing:
            return
        self._closing = True
        for page in self.view_pages.values():
            try:
                getattr(page, "shutdown", lambda: None)()
            except Exception:  # noqa: BLE001
                logger.exception("view shutdown failed")
        self._poll.stop()
        self._tick.stop()
        self._rescan_timer.stop()
        self.stop_workers()
        self.procs.shutdown()
        self.link.stop()
        for w in (self.system_window, self.app_manager, self.devices_window) + tuple(self.native_windows.values()):
            if w is not None:
                w.close()
        try:
            QApplication.instance().focusWindowChanged.disconnect(self._idle_filter.attach)
        except (RuntimeError, TypeError):
            pass
        self._idle_filter.detach_all()
