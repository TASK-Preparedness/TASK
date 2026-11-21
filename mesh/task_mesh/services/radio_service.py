# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Radio worker (own QThread) and its GUI-thread facade (design report §5.1–§5.6).

Threads:
* GUI thread: RadioService facade, hot-plug watcher, NodeService, widgets.
* "task-radio" QThread: RadioWorker — the state machine, backoff and watchdog timers. All provider calls
  except the blocking constructor run here.
* "task-connect-N" helper threads: run provider.connect() (blocks up to ~31 s) so the worker stays
  responsive and the 45 s deadline can abandon an attempt.
* Library threads ("publishing", "stream reader"): only call the sink, which emits Qt signals
  (queued into the worker / GUI thread). Nothing touches widgets from those threads.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from task_mesh.core.clock import Clock
from task_mesh.core.config import RadioConfig, StateStore
from task_mesh.core.errors import ErrorCode, title_for
from task_mesh.database.writer import OP_CONN_EVENT, OP_RADIO, OP_RADIO_EVENT
from task_mesh.domain.models import (
    ConnectionEventRecord,
    EventLevel,
    NodeInfoData,
    Observation,
    PortCandidate,
    RadioEvent,
    RadioIdentity,
    StateSnapshot,
)
from task_mesh.domain.states import ConnectionState as S
from task_mesh.domain.states import StateMachine
from task_mesh.radio.base import ConnectError
from task_mesh.radio.discovery import ChoiceKind, choose_candidate, enumerate_ports, preflight
from task_mesh.services.backoff import Backoff

log = logging.getLogger(__name__)

WATCHDOG_MS = 2000
NO_DEVICE_POLL_MS = 5000
STABLE_RESET_S = 60.0
CLOSE_JOIN_S = 5.0

ProviderFactory = Callable[[Any], Any]
Recorder = Callable[..., bool]


def _default_provider_factory(sink: Any, cfg: RadioConfig) -> Any:
    from task_mesh.radio.meshtastic.provider import MeshtasticProvider

    return MeshtasticProvider(sink, library_timeout_s=cfg.library_timeout_s)


def _locking(provider: Any) -> Any:
    from task_mesh.radio.locking import LockingProvider  # 0.3.0: one owner per device (GUI vs service)

    return LockingProvider(provider)


class _Sink:
    """RadioEventSink handed to providers. Called on library threads; only emits signals."""

    def __init__(self, worker: "RadioWorker") -> None:
        self._w = worker

    def _current(self, gen: int) -> bool:
        return gen == self._w._gen

    def on_established(self, generation: int) -> None:
        self._w._sig_established.emit(generation)

    def on_lost(self, generation: int) -> None:
        self._w._sig_lost.emit(generation)

    def on_nodeinfo(self, generation: int, info: NodeInfoData) -> None:
        if self._current(generation):
            self._w.nodeinfo.emit(info)

    def on_observation(self, generation: int, obs: Observation) -> None:
        if self._current(generation):
            self._w.observation.emit(obs)

    def on_radio_event(self, generation: int, event: RadioEvent) -> None:
        if self._current(generation):
            self._w._sig_radio_event.emit(event)

    def on_text(self, generation: int, text) -> None:
        if self._current(generation):
            self._w.text_received.emit(text)

    def on_routing(self, generation: int, routing) -> None:
        if self._current(generation):
            self._w.routing_received.emit(routing)


class RadioWorker(QObject):
    # public (consumed in the GUI thread through queued connections)
    state_changed = Signal(object)        # StateSnapshot
    nodes_snapshot = Signal(object)       # list[NodeInfoData]
    nodeinfo = Signal(object)             # NodeInfoData
    observation = Signal(object)          # Observation
    radio_event = Signal(object)          # RadioEvent
    counters_changed = Signal(object)     # dict
    text_received = Signal(object)        # messaging.packets.TextPacket
    routing_received = Signal(object)     # messaging.packets.RoutingPacket
    stopped = Signal()
    # internal (into the worker thread)
    _sig_connect_finished = Signal(int, object, object, object)  # gen, provider, identity, ConnectError
    _sig_established = Signal(int)
    _sig_lost = Signal(int)
    _sig_radio_event = Signal(object)

    def __init__(
        self,
        config: RadioConfig,
        state: StateStore,
        record: Optional[Recorder] = None,
        provider_factory: Optional[ProviderFactory] = None,
        discover: Optional[Callable[[], Sequence[PortCandidate]]] = None,
        clock: Optional[Clock] = None,
        backoff: Optional[Backoff] = None,
        path_exists: Callable[[str], bool] = os.path.exists,
        preflight_fn: Callable[[str], Any] = preflight,
        watchdog_ms: int = WATCHDOG_MS,
        no_device_poll_ms: int = NO_DEVICE_POLL_MS,
    ) -> None:
        super().__init__()
        self._watchdog_ms = watchdog_ms
        self._poll_ms = no_device_poll_ms
        self._cfg = config
        self._state_store = state
        self._record = record
        self._factory = provider_factory or (lambda sink: _locking(_default_provider_factory(sink, config)))
        self._discover = discover or (lambda: enumerate_ports())
        self._clock = clock or Clock()
        self._backoff = backoff or Backoff()
        self._path_exists = path_exists
        self._preflight = preflight_fn
        self._sink = _Sink(self)
        self._sm = StateMachine(S.IDLE, self._on_transition)
        self._gen = 0
        self._provider: Any = None
        self._pending: dict[int, Any] = {}
        self._port: Optional[PortCandidate] = None
        self._identity: Optional[RadioIdentity] = None
        self._candidates: tuple[PortCandidate, ...] = ()
        self._reason: Optional[str] = None
        self._err_code: Optional[ErrorCode] = None
        self._err_msg: Optional[str] = None
        self._err_at: Optional[int] = None
        self._retry_at: Optional[int] = None
        self._since: int = self._clock.now()
        self._entered_mono = self._clock.monotonic()
        self._connected_mono: Optional[float] = None
        self._last_probe_mono: Optional[float] = None
        self._shutting_down = False
        self.counters: dict[str, int] = {"connect_attempts": 0, "bad_packets": 0, "reconnects": 0}
        self._timers_made = False
        self._sig_connect_finished.connect(self._on_connect_finished)
        self._sig_established.connect(self._on_established)
        self._sig_lost.connect(self._on_lost)
        self._sig_radio_event.connect(self._on_radio_event)

    # ----- helpers ------------------------------------------------------------------------------
    @property
    def state(self) -> S:
        return self._sm.state

    @property
    def history(self) -> list:
        return list(self._sm.history)

    def _make_timers(self) -> None:
        if self._timers_made:
            return
        self._timers_made = True
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(self._watchdog_ms)
        self._watchdog.timeout.connect(self._on_watchdog)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(lambda: self._scan("backoff_expired"))
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._poll_ms)
        self._poll_timer.timeout.connect(self._on_no_device_poll)
        self._watchdog.start()

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            state=self.state.value, reason=self._reason, port=self._port, identity=self._identity,
            error_code=self._err_code.value if self._err_code else None, error_message=self._err_msg,
            error_at_local=self._err_at, retry_at_local=self._retry_at if self.state is S.BACKOFF else None,
            candidates=self._candidates, since_local=self._since,
        )

    def _emit_state(self) -> None:
        self.state_changed.emit(self.snapshot())

    def _go(self, dst: S, reason: Optional[str] = None) -> bool:
        self._reason = reason
        ok = self._sm.transition(dst, reason)
        if ok:
            self._since = self._clock.now()
            self._entered_mono = self._clock.monotonic()
            if dst is not S.NO_DEVICE and self._timers_made:
                self._poll_timer.stop()
            self._emit_state()
        return ok

    def _on_transition(self, src: S, dst: S, reason: Optional[str]) -> None:
        if self._record is not None:
            self._record(OP_CONN_EVENT, ConnectionEventRecord(
                self._clock.now(), src.value, dst.value, reason, self._port,
                self._identity.node_num if self._identity else None))

    def _set_error(self, code: ErrorCode, message: str) -> None:
        self._err_code, self._err_msg, self._err_at = code, message, self._clock.now()
        if self._record is not None:
            self._record(OP_RADIO_EVENT, RadioEvent(self._clock.now(), EventLevel.WARNING, "connection_error",
                                                    f"{title_for(code)}: {message}"[:300], {"code": code.value}),
                         self._identity.node_num if self._identity else None)

    # ----- slots: commands ----------------------------------------------------------------------
    @Slot()
    def start(self) -> None:
        self._make_timers()
        if self._cfg.autoconnect:
            self._scan("startup")
        else:
            self._refresh_candidates()
            self._emit_state()

    @Slot()
    def request_connect(self) -> None:
        """Connect / Retry now."""
        if self.state in (S.CONNECTED, S.CONNECTING, S.DEVICE_REBOOTING, S.DISCONNECTING, S.SCANNING):
            return
        self._retry_timer.stop()
        if self.state is S.ERROR:
            self._go(S.BACKOFF, "user_retry")
        self._scan("user_connect")

    @Slot()
    def request_disconnect(self) -> None:
        self._retry_timer.stop()
        self._poll_timer.stop()
        st = self.state
        if st in (S.CONNECTED, S.DEVICE_REBOOTING):
            self._teardown("user_disconnect", user=True)
        elif st is S.CONNECTING:
            self._abandon_attempt()
            self._go(S.DISCONNECTING, "user_disconnect")
            self._go(S.IDLE, "user_disconnect")
        elif st is S.ERROR:
            self._go(S.IDLE, "user_disconnect")
        elif st is not S.IDLE:
            self._go(S.IDLE, "user_disconnect")

    @Slot(str)
    def request_rescan(self, reason: str = "hotplug") -> None:
        st = self.state
        if st in (S.CONNECTED, S.DEVICE_REBOOTING):
            self._check_link(reason)
        elif st in (S.NO_DEVICE, S.BACKOFF, S.PERMISSION_DENIED, S.AWAITING_SELECTION):
            self._retry_timer.stop()
            self._scan(reason)
        elif st is S.IDLE:
            self._refresh_candidates()
            self._emit_state()

    @Slot(object, bool)
    def select_candidate(self, cand: PortCandidate, remember: bool) -> None:
        if self.state not in (S.AWAITING_SELECTION, S.IDLE, S.NO_DEVICE, S.BACKOFF, S.PERMISSION_DENIED):
            return
        if remember:
            self._state_store.set("pinned_port", cand.identity())
        self._retry_timer.stop()
        if self.state is not S.AWAITING_SELECTION:
            if self.state is S.ERROR:
                self._go(S.BACKOFF, "user_select")
            self._go(S.SCANNING, "user_select")
        self._connect(cand)

    @Slot()
    def forget_pinned(self) -> None:
        self._state_store.set("pinned_port", None)
        self._emit_state()

    @Slot()
    def shutdown(self) -> None:
        self._shutting_down = True
        if self._timers_made:
            for t in (self._watchdog, self._retry_timer, self._poll_timer):
                t.stop()
        st = self.state
        if st in (S.CONNECTED, S.DEVICE_REBOOTING):
            self._teardown("app_quit", user=True)
        elif st is S.CONNECTING:
            self._abandon_attempt()
            self._go(S.DISCONNECTING, "app_quit")
            self._go(S.IDLE, "app_quit")
        elif st is not S.IDLE:
            self._go(S.IDLE, "app_quit")
        for prov in list(self._pending.values()):
            self._close_provider(prov, wait=False)
        self._pending.clear()
        self.stopped.emit()

    # ----- discovery / connect ------------------------------------------------------------------
    def _refresh_candidates(self) -> tuple[PortCandidate, ...]:
        try:
            self._candidates = tuple(self._discover())
        except Exception as exc:  # noqa: BLE001
            log.exception("discovery failed")
            self._set_error(ErrorCode.UNEXPECTED, f"discovery failed: {type(exc).__name__}: {exc}")
            self._candidates = ()
            raise
        return self._candidates

    def _scan(self, reason: str) -> None:
        if self._shutting_down or not self._go(S.SCANNING, reason):
            return
        try:
            cands = self._refresh_candidates()
        except Exception:  # noqa: BLE001
            self._go(S.ERROR, "discovery_failed")
            self._schedule_backoff()
            return
        log.info("discovered %d candidate port(s)", len(cands),
                 extra={"event": "radio.discovery", "count": len(cands)})
        choice = choose_candidate(cands, self._state_store.get("pinned_port"), self._state_store.get("last_success"))
        if choice.kind is ChoiceKind.NONE:
            self._port = None
            self._go(S.NO_DEVICE, choice.why)
            self._poll_timer.start()
        elif choice.kind is ChoiceKind.SELECT:
            self._go(S.AWAITING_SELECTION, choice.why)
        else:
            self._connect(choice.candidate)

    def _connect(self, cand: PortCandidate) -> None:
        path = cand.open_path or cand.device
        self._port = cand
        pf = self._preflight(path)
        if not pf.ok:
            code = pf.code or ErrorCode.SERIAL_ERROR
            self._set_error(code, pf.message)
            if code is ErrorCode.PERMISSION_DENIED:
                self._go(S.PERMISSION_DENIED, "EACCES")
            elif code is ErrorCode.NO_DEVICE:
                self._go(S.NO_DEVICE, "device_vanished")
                self._poll_timer.start()
            else:
                self._go(S.ERROR, code.value)
                self._schedule_backoff()
            return
        self._gen += 1
        gen = self._gen
        if not self._go(S.CONNECTING, f"open {path}"):
            return
        self.counters["connect_attempts"] += 1
        try:
            provider = self._factory(self._sink)
        except Exception as exc:  # noqa: BLE001
            self._sig_connect_finished.emit(gen, None, None, ConnectError(ErrorCode.LIBRARY_MISSING, str(exc)))
            return
        self._pending[gen] = provider

        def run() -> None:
            ident, err = None, None
            try:
                ident = provider.connect(cand, gen)
            except ConnectError as exc:
                err = exc
            except BaseException as exc:  # noqa: BLE001
                err = ConnectError(ErrorCode.UNEXPECTED, f"{type(exc).__name__}: {exc}")
            self._sig_connect_finished.emit(gen, provider, ident, err)

        threading.Thread(target=run, name=f"task-connect-{gen}", daemon=True).start()

    @Slot(int, object, object, object)
    def _on_connect_finished(self, gen: int, provider: Any, ident: Optional[RadioIdentity],
                             err: Optional[ConnectError]) -> None:
        self._pending.pop(gen, None)
        if gen != self._gen or self.state is not S.CONNECTING or self._shutting_down:
            log.info("discarding stale connect result (gen %d)", gen, extra={"event": "radio.stale_connect"})
            if provider is not None:
                self._close_provider(provider, wait=False)
            return
        if err is not None:
            if provider is not None:
                self._close_provider(provider, wait=False)
            self._fail(err.code, err.message)
            return
        self._provider = provider
        self._identity = ident
        now = self._clock.now()
        self._connected_mono = self._clock.monotonic()
        self._last_probe_mono = self._connected_mono
        if self._port is not None:
            self._state_store.set("last_success", self._port.identity())
        if self._record is not None and ident is not None:
            self._record(OP_RADIO, ident, self._port, now)
        self._go(S.CONNECTED, "handshake_complete")
        self._emit_snapshot()

    def _emit_snapshot(self) -> None:
        if self._provider is None:
            return
        try:
            self.nodes_snapshot.emit(self._provider.snapshot_nodes())
        except Exception:  # noqa: BLE001
            log.exception("node snapshot failed")

    def _fail(self, code: ErrorCode, message: str) -> None:
        self._set_error(code, message)
        if code is ErrorCode.NO_DEVICE:
            self._go(S.NO_DEVICE, "device_vanished")
            self._poll_timer.start()
        elif code is ErrorCode.PERMISSION_DENIED:
            self._go(S.PERMISSION_DENIED, "EACCES")
        elif code is ErrorCode.PORT_BUSY:
            self._go(S.PORT_BUSY, "port_locked")
            self._schedule_backoff()
        else:
            self._go(S.BACKOFF, code.value.lower())
            self._schedule_backoff(already_in_backoff=True)

    def _schedule_backoff(self, already_in_backoff: bool = False) -> None:
        if self._shutting_down:
            return
        delay = self._backoff.next_delay()
        self._retry_at = self._clock.now() + int(round(delay))
        if not already_in_backoff:
            self._go(S.BACKOFF, self._reason)
        else:
            self._emit_state()
        self._retry_timer.start(int(delay * 1000))

    def _abandon_attempt(self) -> None:
        # Bump the generation: the helper's eventual result is discarded and its provider closed.
        self._gen += 1

    # ----- library events -----------------------------------------------------------------------
    @Slot(int)
    def _on_established(self, gen: int) -> None:
        if gen != self._gen:
            return
        if self.state is S.DEVICE_REBOOTING:
            self._go(S.CONNECTED, "radio_reestablished")
            self._connected_mono = self._clock.monotonic()
            self._emit_snapshot()

    @Slot(int)
    def _on_lost(self, gen: int) -> None:
        if gen != self._gen or self.state is not S.CONNECTED:
            return
        prov = self._provider
        path = self._port.open_path if self._port else ""
        if prov is not None and prov.port_open() and prov.is_alive() and self._path_exists(path):
            # The library is re-handshaking on the same open port (firmware 'rebooted').
            self._go(S.DEVICE_REBOOTING, "connection_lost_port_open")
        else:
            self._teardown("connection_lost", user=False, code=ErrorCode.CONNECTION_LOST,
                           message="radio connection lost (device unplugged or reader stopped)")

    @Slot(object)
    def _on_radio_event(self, ev: RadioEvent) -> None:
        if ev.kind == "bad_packet":
            self.counters["bad_packets"] += 1
        if self._record is not None:
            self._record(OP_RADIO_EVENT, ev, self._identity.node_num if self._identity else None)
        self.radio_event.emit(ev)

    # ----- watchdog -----------------------------------------------------------------------------
    def _check_link(self, reason: str) -> None:
        prov = self._provider
        path = self._port.open_path if self._port else ""
        if prov is None:
            return
        if not self._path_exists(path):
            self._teardown(f"{reason}: device node gone", user=False, code=ErrorCode.CONNECTION_LOST,
                           message=f"{path} disappeared")
        elif not prov.is_alive():
            self._teardown(f"{reason}: reader stopped", user=False, code=ErrorCode.WATCHDOG,
                           message="the library reader thread stopped")

    @Slot()
    def _on_watchdog(self) -> None:
        now_m = self._clock.monotonic()
        st = self.state
        if st is S.CONNECTING and now_m - self._entered_mono > self._cfg.handshake_deadline_s:
            self._abandon_attempt()
            self._fail(ErrorCode.HANDSHAKE_TIMEOUT,
                       f"no handshake within {self._cfg.handshake_deadline_s} s; attempt abandoned")
        elif st is S.CONNECTED:
            self._check_link("watchdog")
            if self.state is S.CONNECTED:
                if self._connected_mono is not None and now_m - self._connected_mono >= STABLE_RESET_S:
                    self._backoff.reset()
                probe = self._cfg.link_probe_s
                if probe and self._last_probe_mono is not None and now_m - self._last_probe_mono >= probe:
                    self._last_probe_mono = now_m
                    try:
                        self._provider.send_heartbeat()
                    except BaseException as exc:  # noqa: BLE001
                        self._teardown("link_probe_failed", user=False, code=ErrorCode.SERIAL_ERROR,
                                       message=f"heartbeat write failed: {type(exc).__name__}")
        elif st is S.DEVICE_REBOOTING:
            prov = self._provider
            if prov is None or not prov.is_alive():
                self._teardown("reboot: reader stopped", user=False, code=ErrorCode.CONNECTION_LOST,
                               message="radio did not come back after reboot")
            elif now_m - self._entered_mono > self._cfg.reboot_grace_s:
                self._teardown("reboot_timeout", user=False, code=ErrorCode.CONNECTION_LOST,
                               message=f"radio did not finish rebooting within {self._cfg.reboot_grace_s} s")
        prov = self._provider
        counters = dict(self.counters)
        if prov is not None and hasattr(prov, "counters"):
            try:
                counters.update({f"lib_{k}": v for k, v in prov.counters.items()})
            except Exception:  # noqa: BLE001
                pass
        self.counters_changed.emit(counters)

    @Slot()
    def _on_no_device_poll(self) -> None:
        if self.state is not S.NO_DEVICE:
            self._poll_timer.stop()
            return
        try:
            cands = tuple(self._discover())
        except Exception:  # noqa: BLE001
            return
        if cands:
            self._scan("poll_found_device")

    # ----- teardown -----------------------------------------------------------------------------
    def _close_provider(self, prov: Any, wait: bool = True) -> None:
        def run() -> None:
            try:
                if hasattr(prov, "shutdown"):
                    prov.shutdown()
                else:
                    prov.close()
            except BaseException:  # noqa: BLE001
                log.exception("provider close failed")

        t = threading.Thread(target=run, name="task-close", daemon=True)
        t.start()
        if wait:
            t.join(CLOSE_JOIN_S)
            if t.is_alive():
                log.warning("provider close did not finish within %.0f s", CLOSE_JOIN_S,
                            extra={"event": "radio.close_timeout"})

    def _teardown(self, reason: str, user: bool, code: Optional[ErrorCode] = None,
                  message: Optional[str] = None) -> None:
        if not self._go(S.DISCONNECTING, reason):
            return
        prov, self._provider = self._provider, None
        self._gen += 1  # late events from the old interface are ignored from here on
        self._connected_mono = None
        if prov is not None:
            self._close_provider(prov, wait=True)
        if code is not None:
            self._set_error(code, message or reason)
        if user or self._shutting_down:
            self._go(S.IDLE, reason)
        else:
            self.counters["reconnects"] += 1
            self._go(S.BACKOFF, reason)
            self._schedule_backoff(already_in_backoff=True)


class RadioService(QObject):
    """GUI-thread facade: owns the worker thread and forwards commands as queued signals."""

    state_changed = Signal(object)
    nodes_snapshot = Signal(object)
    nodeinfo = Signal(object)
    observation = Signal(object)
    radio_event = Signal(object)
    counters_changed = Signal(object)
    text_received = Signal(object)
    routing_received = Signal(object)

    _cmd_start = Signal()
    _cmd_connect = Signal()
    _cmd_disconnect = Signal()
    _cmd_rescan = Signal(str)
    _cmd_select = Signal(object, bool)
    _cmd_forget = Signal()
    _cmd_shutdown = Signal()

    def __init__(self, worker: RadioWorker, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.thread = QThread()
        self.thread.setObjectName("task-radio")
        worker.moveToThread(self.thread)
        self.last_snapshot: StateSnapshot = worker.snapshot()
        for name in ("state_changed", "nodes_snapshot", "nodeinfo", "observation", "radio_event",
                     "counters_changed", "text_received", "routing_received"):
            getattr(worker, name).connect(getattr(self, name))
        worker.state_changed.connect(self._remember)
        self._cmd_start.connect(worker.start)
        self._cmd_connect.connect(worker.request_connect)
        self._cmd_disconnect.connect(worker.request_disconnect)
        self._cmd_rescan.connect(worker.request_rescan)
        self._cmd_select.connect(worker.select_candidate)
        self._cmd_forget.connect(worker.forget_pinned)
        self._cmd_shutdown.connect(worker.shutdown)
        self._stopped = threading.Event()
        worker.stopped.connect(self._stopped.set, type=_direct())
        self._watcher = None

    def _remember(self, snap: StateSnapshot) -> None:
        self.last_snapshot = snap

    def attach_hotplug(self, watcher: Any) -> None:
        self._watcher = watcher
        watcher.changed.connect(self.rescan)

    def start(self) -> None:
        self.thread.start()
        self._cmd_start.emit()
        if self._watcher is not None:
            self._watcher.start()

    def send_text(self, text: str, dest_num: int, channel: int) -> int:
        """Called from a helper thread by MessageService; uses the currently connected provider only."""
        prov = self.worker._provider
        if prov is None or not hasattr(prov, "send_text"):
            raise RuntimeError("no radio connected")
        return prov.send_text(text, dest_num, channel)

    def channels(self) -> list:
        prov = self.worker._provider
        try:
            return prov.channels() if prov is not None and hasattr(prov, "channels") else []
        except Exception:  # noqa: BLE001
            return []

    def local_node_num(self):
        ident = getattr(self.last_snapshot, "identity", None)
        return getattr(ident, "node_num", None)

    def connect_radio(self) -> None:
        self._cmd_connect.emit()

    def disconnect_radio(self) -> None:
        self._cmd_disconnect.emit()

    def rescan(self, reason: str = "user_rescan") -> None:
        self._cmd_rescan.emit(reason)

    def select(self, cand: PortCandidate, remember: bool) -> None:
        self._cmd_select.emit(cand, remember)

    def forget_pinned(self) -> None:
        self._cmd_forget.emit()

    def stop(self, timeout_s: float = 8.0) -> None:
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.thread.isRunning():
            self._stopped.clear()
            self._cmd_shutdown.emit()
            self._stopped.wait(timeout_s)
            self.thread.quit()
            self.thread.wait(int(timeout_s * 1000))


def _direct():
    from PySide6.QtCore import Qt

    return Qt.ConnectionType.DirectConnection
