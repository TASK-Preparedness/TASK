# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GUI ↔ hub controller (0.3.1).

* **service-client mode** whenever task-mesh-service holds its instance lock: this window never opens a serial
  port (Connect is refused, the Meshtastic worker is disconnected, local MeshCore adapters are stopped and their
  port locks released). Data comes from the service over the private socket; a live subscription refreshes the
  tabs immediately; sends go to the service (explicit Send + Core session checked by the service).
  The service is the only writer of hub.sqlite3 in this mode.
* **direct mode** when the service is not running (after a grace period, so a service restart does not make the
  window grab the radio): in-process hub as in 0.3.0. Connect is never automatic on that switch.
* Focus rule: the window reports "focused" (active and not minimised) with a 15 s lease, renewed every 5 s, on its
  own socket connection (closing or crashing drops it immediately). While any lease is live: no pop-ups, nothing
  is marked read automatically.
* Notification click: opens this window at the conversation given by an internal message row id.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

SERVICE_GONE_GRACE_S = 15.0
FOCUS_TTL_S = 15.0
FOCUS_RENEW_MS = 5000


class HubController(QObject):
    event = Signal(str, dict)          # from reader / D-Bus threads → GUI thread
    mode_changed = Signal(str)

    def __init__(self, window, tabs, access, radio, local_factory: Callable[[], object],
                 service_running: Callable[[], bool], client_factory: Callable[[], object],
                 subscriber_factory: Callable[[Callable], object], banner: Callable[[str], None],
                 initial_mode: str, clock=time.monotonic) -> None:
        super().__init__(window)
        self.window, self.tabs, self.access, self.radio = window, tabs, access, radio
        self.local_factory, self.service_running = local_factory, service_running
        self.client_factory, self.subscriber_factory = client_factory, subscriber_factory
        self.banner, self.clock = banner, clock
        self.mode = None
        self.sub = None
        self._gone_since: Optional[float] = None
        self._focused: Optional[bool] = None
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll_devices)
        self.event.connect(self._on_event)
        self.watch = QTimer(self)
        self.watch.timeout.connect(self.check)
        self.watch.start(2000)
        self.renew = QTimer(self)
        self.renew.timeout.connect(lambda: self.report_focus(force=True))
        self.renew.start(FOCUS_RENEW_MS)
        if initial_mode == "service":
            self.to_service(initial=True)
        else:
            self.to_direct(initial=True)

    # --- mode -------------------------------------------------------------------------------------
    def check(self) -> None:
        running = self.service_running()
        if running:
            self._gone_since = None
            if self.mode != "service":
                self.to_service()
        elif self.mode == "service":
            if self._gone_since is None:
                self._gone_since = self.clock()
                self.banner("task-mesh-service is not responding; waiting for it to come back…")
            elif self.clock() - self._gone_since >= SERVICE_GONE_GRACE_S:
                self.to_direct()

    def to_service(self, initial: bool = False) -> None:
        if self.mode == "service":
            return
        was_direct = self.mode == "direct"
        if not initial:                            # the worker is not started yet at construction time
            try:
                self.radio.disconnect_radio()     # release the Meshtastic port if this window held it
            except Exception:  # noqa: BLE001
                log.exception("radio release failed")
        self.poll.stop()
        if self.access.local is not None:
            self.access.local.devices.shutdown()   # stops MeshCore adapters, releases port locks
            self.access.local.drop_client("local")
        self.access.client = self.client_factory()
        self.sub = self.subscriber_factory(lambda kind, data: self.event.emit(kind, dict(data)))
        self.sub.start()
        self._set_radio_panel(False)
        self.mode = "service"
        self._focused = None
        self.report_focus(force=True)
        self.banner("task-mesh-service is running: this window is attached to it and does not open radios."
                    + (" The radio was handed over to the service." if was_direct else ""))
        self.mode_changed.emit("service")
        self.tabs.refresh()

    def to_direct(self, initial: bool = False) -> None:
        if self.sub is not None:
            self.sub.stop()
            self.sub = None
        self.access.client = None
        if self.access.local is None:
            self.access.local = self.local_factory()
        self._set_radio_panel(True)
        self.poll.start(3000)
        QTimer.singleShot(0, self._poll_devices)
        self.mode = "direct"
        self._gone_since = None
        self._focused = None
        self.report_focus(force=True)
        if not initial:
            self.banner("task-mesh-service stopped: this window can use the radios directly. Click Connect to "
                        "connect the Meshtastic radio (nothing reconnects automatically).")
        self.mode_changed.emit("direct")
        self.tabs.refresh()

    def _poll_devices(self) -> None:
        if self.mode == "direct" and self.access.local is not None and not self.service_running():
            self.access.local.devices.poll()

    def _set_radio_panel(self, enabled: bool) -> None:
        p = getattr(self.window, "radio_panel", None)
        if p is not None:
            p.setEnabled(enabled)
            p.setToolTip("" if enabled else "The background service owns the radios (see Network Status).")

    def connect_requested(self) -> None:
        """Connect / Retry button. Never opens a port while the service runs."""
        if self.mode == "service" or self.service_running():
            if self.mode != "service":
                self.to_service()
            self.banner("Not connecting: task-mesh-service owns the radios. Stop it in Network Status to use the "
                        "radio from this window.")
            return
        self.radio.connect_radio()

    # --- live events ----------------------------------------------------------------------------
    def _on_event(self, kind: str, data: dict) -> None:
        if kind == "_connected":
            self.report_focus(force=True)
            self.tabs.reset_auth()
        if kind == "open":
            self.open_ref(data)
            return
        if kind in ("message", "read", "device", "node", "_connected", "_disconnected"):
            self.tabs.refresh()

    # --- focus lease ----------------------------------------------------------------------------
    def window_focused(self) -> bool:
        w = self.window
        try:
            return bool(w.isVisible() and w.isActiveWindow() and not w.isMinimized())
        except RuntimeError:
            return False

    def report_focus(self, force: bool = False) -> None:
        f = self.window_focused()
        if not force and f == self._focused:
            return
        self._focused = f
        try:
            if self.mode == "service" and self.sub is not None:
                self.sub.focus(f, FOCUS_TTL_S)
            elif self.access.local is not None:
                self.access.local.set_focus("local", f, FOCUS_TTL_S)
        except Exception:  # noqa: BLE001
            pass

    # --- open at a conversation (notification click / --open-message) ----------------------------------
    def open_message(self, row_id: int) -> bool:
        try:
            ref = self.access.call("message_ref", id=int(row_id))
        except Exception:  # noqa: BLE001
            ref = None
        if not ref:
            return False
        self.open_ref(ref)
        return True

    def open_ref(self, ref: dict) -> None:
        w = self.window
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()
        self.tabs.select(str(ref.get("protocol", "")), str(ref.get("conversation", "")))

    def shutdown(self) -> None:
        self.watch.stop()
        self.renew.stop()
        self.poll.stop()
        if self.sub is not None:
            self.sub.stop()
            self.sub = None
        local = self.access.local
        if local is not None:
            local.drop_client("local")
