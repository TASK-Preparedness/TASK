# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""USB serial hot-plug notification.

Primary: pyudev netlink monitor via pyudev.pyside6.MonitorObserver (QSocketNotifier, zero CPU idle).
Fallback: QTimer polling of the sysfs port list. Both emit `changed(reason)` after a debounce.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)


class HotplugWatcher(QObject):
    changed = Signal(str)
    mode = "none"

    def __init__(self, debounce_ms: int = 750, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(debounce_ms)
        self._pending = "hotplug"
        self._debounce.timeout.connect(lambda: self.changed.emit(self._pending))

    def _poke(self, reason: str) -> None:
        self._pending = reason
        self._debounce.start()

    def start(self) -> None:  # pragma: no cover - overridden
        pass

    def stop(self) -> None:
        self._debounce.stop()


class UdevHotplugWatcher(HotplugWatcher):
    mode = "udev"

    def __init__(self, debounce_ms: int = 750, parent: Optional[QObject] = None) -> None:
        super().__init__(debounce_ms, parent)
        import pyudev
        from pyudev.pyside6 import MonitorObserver

        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by("tty")
        self._observer = MonitorObserver(self._monitor)
        self._observer.deviceEvent.connect(self._on_event)

    def _on_event(self, device) -> None:  # pyudev passes the Device; action is device.action
        action = getattr(device, "action", "change") or "change"
        node = getattr(device, "device_node", None) or ""
        if node.startswith(("/dev/ttyUSB", "/dev/ttyACM")):
            log.info("hotplug %s %s", action, node, extra={"event": "radio.hotplug", "port": node})
            self._poke(f"hotplug_{action}")

    def start(self) -> None:
        self._monitor.start()
        self._observer.enabled = True

    def stop(self) -> None:
        super().stop()
        try:
            self._observer.enabled = False
        except Exception:  # noqa: BLE001
            pass


class PollingHotplugWatcher(HotplugWatcher):
    mode = "polling"

    def __init__(
        self,
        signature: Callable[[], tuple],
        interval_ms: int = 2000,
        debounce_ms: int = 750,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(debounce_ms, parent)
        self._signature = signature
        self._last: Optional[tuple] = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        try:
            sig = self._signature()
        except Exception:  # noqa: BLE001
            return
        if self._last is not None and sig != self._last:
            self._poke("poll_change")
        self._last = sig

    def start(self) -> None:
        self._tick()
        self._timer.start()

    def stop(self) -> None:
        super().stop()
        self._timer.stop()


def port_signature() -> tuple:
    import serial.tools.list_ports

    return tuple(sorted(p.device for p in serial.tools.list_ports.comports()))


def udevd_running(control: str = "/run/udev/control") -> bool:
    """Netlink opens fine without udevd (containers) but then never delivers events."""
    return os.path.exists(control)


def create_hotplug_watcher(parent: Optional[QObject] = None, prefer_udev: bool = True) -> HotplugWatcher:
    if prefer_udev and not udevd_running():
        log.warning("udevd not running; hot-plug falls back to polling every 2 s",
                    extra={"event": "radio.hotplug_mode"})
        prefer_udev = False
    if prefer_udev:
        try:
            watcher: HotplugWatcher = UdevHotplugWatcher(parent=parent)
            log.info("hotplug via udev netlink", extra={"event": "radio.hotplug_mode"})
            return watcher
        except Exception as exc:  # noqa: BLE001 - containers, missing libudev, etc.
            log.warning("udev hotplug unavailable (%s); polling every 2 s", exc,
                        extra={"event": "radio.hotplug_mode"})
    return PollingHotplugWatcher(port_signature, parent=parent)
