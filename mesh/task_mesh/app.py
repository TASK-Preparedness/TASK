# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Application entry point: root refusal, paths, config, logging, DB, services, window."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from task_mesh import APP_ID, APP_NAME, __version__

log = logging.getLogger("task_mesh.app")
VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
ROOT_MESSAGE = (
    f"{APP_NAME} must not be run as root (or with sudo).\n"
    "Run it as your normal user. If the radio's serial port is not accessible, add your user to the "
    'dialout group once:  sudo usermod -aG dialout "$USER"  and log out and back in.'
)


def _ensure_vendor_path() -> None:
    if (VENDOR_DIR / "meshtastic").is_dir() and str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="task-mesh", description=f"{APP_NAME} — Meshtastic field station")
    p.add_argument("--version", action="store_true", help="print version and exit")
    p.add_argument("--debug", action="store_true", help="DEBUG log level for T.A.S.K. (library stays at WARNING)")
    p.add_argument("--no-autoconnect", action="store_true", help="start without connecting to a radio")
    p.add_argument("--open-message", type=int, metavar="ID",
                   help="open at the conversation of this internal message id (used by notification clicks)")
    p.add_argument("--forget-user-data", action="store_true",
                   help="delete this user's T.A.S.K. config, state, logs, cache and database (asks to confirm)")
    return p.parse_args(list(argv))


def is_root(geteuid: Callable[[], int] = os.geteuid) -> bool:
    return geteuid() == 0


def forget_user_data(paths: Any, ask: Callable[[str], str] = input, out=sys.stdout) -> int:
    dirs = [d for d in paths.all_dirs() if d.exists()]
    if not dirs:
        print("No T.A.S.K. user data found.", file=out)
        return 0
    print("This permanently deletes:", file=out)
    for d in dirs:
        print(f"  {d}", file=out)
    if ask("Type 'yes' to delete: ").strip() != "yes":
        print("Nothing deleted.", file=out)
        return 1
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    print("Deleted.", file=out)
    return 0


def library_versions() -> dict[str, str]:
    out: dict[str, str] = {"python": sys.version.split()[0]}
    for mod in ("meshtastic", "PySide6", "google.protobuf", "pubsub", "serial", "pyudev"):
        try:
            m = __import__(mod, fromlist=["__name__"])
            ver = getattr(m, "__version__", None) or getattr(m, "VERSION", None)
            if ver is None and mod == "meshtastic":
                from importlib.metadata import version

                try:
                    ver = version("meshtastic")
                except Exception:  # noqa: BLE001
                    ver = "?"
            out[mod] = f"{ver} ({os.path.dirname(getattr(m, '__file__', '') or '')})"
        except Exception as exc:  # noqa: BLE001
            out[mod] = f"unavailable: {type(exc).__name__}"
    return out


@dataclass
class AppContext:
    paths: Any
    config: Any
    writer: Any
    radio: Any
    nodes: Any
    status: Any
    window: Any
    model: Any
    hotplug: Any
    warnings: list

    def shutdown(self) -> None:
        try:
            self.radio.stop()
        except Exception:  # noqa: BLE001
            log.exception("radio stop failed")
        try:
            self.status.stop()
        except Exception:  # noqa: BLE001
            pass
        if self.writer is not None:
            self.writer.stop()
        hub = getattr(self.window, "_hub", None)
        if hub is not None:
            try:
                hub[2].shutdown()
            except Exception:  # noqa: BLE001
                log.exception("hub controller stop failed")
        if hub is not None and hub[0].local is not None:
            try:
                hub[0].local.shutdown()
                hub[0].local.store.close()
            except Exception:  # noqa: BLE001
                log.exception("hub stop failed")
        extra = getattr(self.window, "_phase4c", None)
        if extra:
            messages, card, feed, _hb = extra
            try:
                card.remove()
                if feed.enabled:
                    feed.set_enabled(False)
                if messages is not None:
                    messages.gate.sign_out()
            except Exception:  # noqa: BLE001
                pass


def build_application(
    env: Optional[Mapping[str, str]] = None,
    no_autoconnect: bool = False,
    debug: bool = False,
    provider_factory: Optional[Callable[[Any], Any]] = None,
    discover: Optional[Callable[[], Any]] = None,
    hotplug: Any = "auto",
    console_log: bool = True,
    path_exists: Callable[[str], bool] = os.path.exists,
    preflight_fn: Optional[Callable[[str], Any]] = None,
    hub_mode: str = "auto",
    hub_kwargs: Optional[dict] = None,
) -> AppContext:
    """Wire everything (QApplication must already exist). Tests inject provider/discovery/hotplug."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from task_mesh.core.config import StateStore, load_config
    from task_mesh.core.logging_setup import setup_logging
    from task_mesh.core.paths import resolve_paths
    from task_mesh.database.writer import DbWriter
    from task_mesh.radio.hotplug import create_hotplug_watcher
    from task_mesh.services.node_service import NodeService
    from task_mesh.services.radio_service import RadioService, RadioWorker
    from task_mesh.services.status_service import StatusService
    from task_mesh.ui.main_window import MainWindow
    from task_mesh.ui.node_table import NodeTableModel
    from task_mesh.ui.theme import metrics_for, stylesheet

    from task_mesh.services.integration import MapFeed, StatusCard, copy_legacy_dirs

    paths = resolve_paths(env)
    copied = copy_legacy_dirs(paths.all_dirs())
    paths.ensure()
    config, warnings = load_config(paths.config_file)
    level = "DEBUG" if debug else config.logging.level
    setup_logging(paths.log_file, level, console=console_log)
    app = QApplication.instance()
    log.info("%s %s starting", APP_NAME, __version__,
             extra={"event": "app.start", "versions": library_versions(),
                    "qt_platform": QGuiApplication.platformName(), "sys_path": sys.path[:6]})
    log.info("qt.platform=%s", QGuiApplication.platformName(), extra={"event": "app.platform"})
    for w in warnings:
        log.warning("config: %s", w, extra={"event": "config.warning"})
    if copied:
        warnings.append("copied data from rain-mesh 0.1.0 (" + ", ".join(copied) + "); the old folders were kept")

    writer = DbWriter(paths.db_file, config.retention)
    writer.start()
    if not writer.wait_ready(15.0):
        warnings.append("database did not open within 15 s")
    state = StateStore(paths.state_file)
    if state.load_warning:
        warnings.append(state.load_warning)

    screen = app.primaryScreen() if app is not None else None
    height = screen.availableGeometry().height() if screen is not None else 600
    metrics = metrics_for(config.ui.density, height)
    if app is not None:
        app.setStyleSheet(stylesheet(metrics))

    radio_cfg = config.radio
    # 0.3.0: if task-mesh-service owns the radios, this window attaches to it and never opens a port itself.
    if hub_mode == "auto":
        from task_mesh.hub.locks import service_running
        probe = (hub_kwargs or {}).get("service_running") or (lambda: service_running(env))
        hub_mode = "service" if probe() else "direct"
    if hub_mode == "service":
        no_autoconnect = True
        warnings.append("task-mesh-service is running: it owns the radios; this window shows its data "
                        "(Network Status tab). Meshtastic connect here is disabled.")
    if no_autoconnect:
        radio_cfg = replace(radio_cfg, autoconnect=False)
    record = writer.submit if writer.open_error is None else None
    worker = RadioWorker(radio_cfg, state, record=record, provider_factory=provider_factory,
                         discover=discover, path_exists=path_exists,
                         **({"preflight_fn": preflight_fn} if preflight_fn is not None else {}))
    radio = RadioService(worker)
    nodes = NodeService(record)
    status = StatusService(writer)
    model = NodeTableModel()
    window = MainWindow(model, metrics)

    # wiring (all queued from the radio thread into the GUI thread)
    radio.state_changed.connect(nodes.on_state)
    radio.state_changed.connect(window.radio_panel.render)
    radio.nodes_snapshot.connect(nodes.on_snapshot)
    radio.nodeinfo.connect(nodes.on_nodeinfo)
    radio.observation.connect(nodes.on_observation)
    radio.counters_changed.connect(status.on_counters)
    nodes.rows_changed.connect(model.apply)
    nodes.counts_changed.connect(status.on_counts)
    status.changed.connect(window.status.render)
    p = window.radio_panel
    # Connect/Retry go through the hub controller (below) so they never open a port the service owns.
    _connect_target = {"fn": radio.connect_radio}
    p.connect_clicked.connect(lambda *_: _connect_target["fn"]())
    p.retry_clicked.connect(lambda *_: _connect_target["fn"]())
    p.disconnect_clicked.connect(radio.disconnect_radio)
    p.rescan_clicked.connect(lambda: radio.rescan("user_rescan"))
    p.candidate_chosen.connect(radio.select)

    if writer.open_error:
        window.banner.show_message(f"Database unavailable: {writer.open_error}. Nodes will not be saved.")
    elif writer.open_result is not None and writer.open_result.quarantined is not None:
        window.banner.show_message(
            f"The database was damaged and has been moved aside to {writer.open_result.quarantined}. "
            "A new, empty database was created. Nothing was deleted.")
    for w in warnings:
        window.banner.show_message(f"Configuration: {w}")

    # Phase 4C: messaging (own task-core session), launcher status card, optional Maps feed
    messages = None
    try:
        from task_comms.auth import SessionGate
        from task_comms.core import CoreClient
        from task_mesh.messaging.service import MessageService, node_id
        from task_mesh.messaging.store import MessageStore
        from task_mesh.ui.messages_panel import MessagesPanel

        gate = SessionGate(CoreClient(), idle_lock_s=15 * 60)
        messages = MessageService(MessageStore(paths.data_dir / "messages.sqlite3"), gate, radio.send_text)
        radio.text_received.connect(messages.on_text)
        radio.routing_received.connect(messages.on_routing)
        radio.state_changed.connect(lambda snap: setattr(messages, "local_num", radio.local_node_num()))

        def dm_targets():
            return [(r.node_id, r.short_name or r.long_name or r.node_id) for r in nodes.nodes.values()
                    if r.node_id and r.node_num != radio.local_node_num()][:200]
        panel = MessagesPanel(messages, radio.channels, dm_targets)
        window.add_messages(panel)
        radio.state_changed.connect(lambda _s: panel.refresh_conversations())
    except ImportError as exc:
        window.banner.show_message(f"Messaging unavailable: python3-task-comms is not installed ({exc.name})")
    card = StatusCard()
    radio.state_changed.connect(card.on_state)

    def _card_counts(*_a):
        card.nodes = len(nodes.nodes)
        card.unread = messages.unread if messages is not None else 0
        card.flush()
    nodes.counts_changed.connect(_card_counts)
    from PySide6.QtCore import QTimer
    hb = QTimer(window)
    hb.timeout.connect(_card_counts)
    hb.start(5000)
    feed = MapFeed()

    def _toggle_feed(on: bool) -> None:
        try:
            feed.set_enabled(bool(on), list(nodes.nodes.values()))
        except Exception as exc:  # noqa: BLE001
            window.banner.show_message(f"Maps feed unavailable: {type(exc).__name__}")
            window.map_toggle.setChecked(False)
    window.map_toggle.toggled.connect(_toggle_feed)
    nodes.rows_changed.connect(lambda rows: [feed.update(r) for r in rows] if feed.enabled else None)
    window._phase4c = (messages, card, feed, hb)

    window._hub = _build_hub_tabs(window, paths, radio, messages, hub_mode, hub_kwargs or {}, env)
    if window._hub is not None:
        _connect_target["fn"] = window._hub[2].connect_requested
        def _card_unread(*_a):
            try:
                card.unread = window._hub[0].call("unread")["total"]
                card.flush()
            except Exception:  # noqa: BLE001
                pass
        hb.timeout.connect(_card_unread)

    nodes.load_persisted(writer.initial_nodes)

    watcher = None
    if hotplug == "auto":
        watcher = create_hotplug_watcher(window)
    elif hotplug is not None:
        watcher = hotplug
    if watcher is not None:
        radio.attach_hotplug(watcher)
    status.start()
    radio.start()
    if config.ui.fullscreen:
        window.showFullScreen()
    return AppContext(paths, config, writer, radio, nodes, status, window, model, watcher, warnings)


def _service_toggle(on: bool) -> str:
    import subprocess
    # start/stop only: never `enable` (that would start it at every login) — 4F.1 rule "no boot enable"
    verb = ["start"] if on else ["stop"]
    try:
        r = subprocess.run(["/usr/bin/systemctl", "--user", *verb, "task-mesh-service.service"], capture_output=True,
                           text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"systemctl failed: {type(exc).__name__}"
    if r.returncode != 0:
        return f"systemctl --user {' '.join(verb)} failed: {(r.stderr or '').strip()[:200]}"
    return ("Background service " + ("started for this session; this window attaches to it automatically."
                                    if on else "stopped; this window takes over the radios after 15 s (click Connect)."))


def _build_hub_tabs(window, paths, radio, messages, hub_mode: str, hub_kwargs: dict, env):
    """0.3.1 tab set + HubController. service: attached to task-mesh-service (never opens ports). direct:
    in-process hub (MeshCore adapters; Meshtastic stays with the 0.2.0 RadioWorker and feeds the hub).
    The controller switches live when the service starts/stops. off: 0.2.0 layout (tests).
    -> (access, tabs, controller)"""
    if hub_mode == "off":
        return None
    from PySide6.QtCore import QEvent, QObject, Signal

    from task_mesh.hub.ipc import HubClient, HubSubscriber, socket_path
    from task_mesh.hub.locks import service_running
    from task_mesh.hub.notifier import JeepneySender
    from task_mesh.protocols.meshcore.adapter import MeshCoreAdapter
    from task_mesh.protocols.meshtastic_adapter import text_to_hub
    from task_mesh.service import build_hub
    from task_mesh.ui.hub_controller import HubController
    from task_mesh.ui.hub_panels import HubAccess, HubTabs

    class _Bridge(QObject):
        action = Signal(int, str)
    bridge = _Bridge(window)
    holder: dict = {}
    sender = hub_kwargs.pop("sender", None) or JeepneySender(on_action=lambda nid, act: bridge.action.emit(nid, act))
    running = hub_kwargs.pop("service_running", None) or (lambda: service_running(env))
    sub_factory = hub_kwargs.pop("subscriber_factory", None) or (lambda cb: HubSubscriber(cb, socket_path(env)))
    client_factory = hub_kwargs.pop("client_factory", None) or (lambda: HubClient(socket_path(env), timeout=1.0))
    hub_kwargs.setdefault("factories", {"meshcore": lambda path, key, sink: MeshCoreAdapter(path, key, sink)})

    def local_factory():
        h = build_hub(paths, "gui", sender=sender, **hub_kwargs)
        h.opener = lambda ref: holder["ctl"].open_ref(ref) or True
        return h
    mt_widgets = [(window.tabs.widget(0), "Nodes (this window's radio)")]
    if messages is not None and window.messages is not None:
        mt_widgets.append((window.messages, "Messages & ACK (this window's radio)"))
    gate = messages.gate if messages is not None else None
    access = HubAccess()
    tabs = HubTabs(window.tabs, access, gate, mt_widgets, _service_toggle, getattr(sender, "server_information", None))
    ctl = HubController(window, tabs, access, radio, local_factory, running, client_factory, sub_factory,
                        window.banner.show_message, hub_mode)
    holder["ctl"] = ctl
    bridge.action.connect(lambda nid, act: access.local.on_notification_action(nid, act)
                          if ctl.mode == "direct" and access.local is not None else None)
    sess = {"start": None}

    def on_state(snap):
        if getattr(snap, "state", "") == "CONNECTED" and sess["start"] is None:
            sess["start"] = time.time()
        elif getattr(snap, "state", "") != "CONNECTED":
            sess["start"] = None
    radio.state_changed.connect(on_state)

    def on_text(t):
        if ctl.mode != "direct" or access.local is None:      # service mode: the service is the only writer
            return
        me = radio.local_node_num()
        if (me is not None and t.from_num == me) or (me is not None and t.is_direct and t.to_num != me):
            return
        access.local.on_message(text_to_hub(t, "meshtastic-gui", time.time(), sess["start"]))
    radio.text_received.connect(on_text)

    class _FocusFilter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate, QEvent.Type.WindowStateChange,
                             QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close):
                QTimer.singleShot(0, ctl.report_focus)
            return False
    from PySide6.QtCore import QTimer
    window._focus_filter = _FocusFilter(window)
    window.installEventFilter(window._focus_filter)
    return access, tabs, ctl


def _install_excepthook(ctx_holder: dict) -> None:
    def hook(etype, value, tb) -> None:
        log.critical("unhandled exception", exc_info=(etype, value, tb), extra={"event": "app.unhandled"})
        ctx = ctx_holder.get("ctx")
        if ctx is not None:
            try:
                ctx.window.banner.show_message(
                    f"Internal error: {etype.__name__}. The app keeps running; details are in {ctx.paths.log_file}")
            except Exception:  # noqa: BLE001
                pass

    sys.excepthook = hook
    threading.excepthook = lambda args: log.critical(
        "unhandled exception in thread %s", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback), extra={"event": "app.thread_unhandled"})


def _show_root_refusal() -> None:
    print(ROOT_MESSAGE, file=sys.stderr)
    headless = os.environ.get("QT_QPA_PLATFORM", "").split(":")[0] in ("offscreen", "minimal")
    if not headless and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication([APP_ID])
            QMessageBox.critical(None, APP_NAME, ROOT_MESSAGE)
            del app
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[Sequence[str]] = None, geteuid: Callable[[], int] = os.geteuid) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(f"{APP_ID} {__version__}")
        return 0
    if is_root(geteuid):
        _show_root_refusal()
        return 2
    if args.forget_user_data:
        from task_mesh.core.paths import resolve_paths

        return forget_user_data(resolve_paths())
    _ensure_vendor_path()
    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setApplicationName(APP_ID)
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else APP_ID])
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    icon_path = Path(__file__).resolve().parents[1] / "assets" / "icons" / "task-mesh.svg"  # source tree
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(icon_path)) if icon_path.exists() else QIcon()))
    holder: dict = {}
    _install_excepthook(holder)
    try:
        ctx = build_application(no_autoconnect=args.no_autoconnect, debug=args.debug)
    except Exception as exc:  # noqa: BLE001
        log.critical("startup failed", exc_info=True, extra={"event": "app.startup_failed"})
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(None, APP_NAME, f"{APP_NAME} could not start:\n{type(exc).__name__}: {exc}")
        return 1
    holder["ctx"] = ctx
    app.aboutToQuit.connect(ctx.shutdown)
    if not ctx.config.ui.fullscreen:
        ctx.window.resize(1024, 600)
        ctx.window.show()
    if args.open_message is not None and args.open_message > 0 and getattr(ctx.window, "_hub", None):
        QTimer.singleShot(800, lambda: ctx.window._hub[2].open_message(args.open_message))
    # Let Python handle SIGINT promptly (Ctrl+C in a terminal).
    import signal

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(250)
    tick.timeout.connect(lambda: None)
    rc = app.exec()
    log.info("exit %d", rc, extra={"event": "app.exit"})
    time.sleep(0)
    return rc
