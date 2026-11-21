# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Udev enumeration. This module never opens a device node.

Hot-plug (H1, 0.2.0 hardware acceptance): the udev netlink monitor is opened
before the initial scan, supervised (an error reopens it with backoff instead of
ending hot-plug for the life of the process), and backed by a periodic rescan
that resynchronises anything the monitor missed. Its state is reported by
``status()`` (v2 ``core.health`` field ``hotplug``).
"""

import errno
import logging
import threading
import time

from task_core.devices import RawDevice
from task_core.errors import EnumeratorError

logger = logging.getLogger("task_core")

# Rescan cadence while the monitor runs: a backstop only. A difference must be
# seen by two scans at least CONFIRM_DELAY apart before it is applied, so an
# event that udev is still processing is never pre-empted.
RESCAN_INTERVAL = 10.0
CONFIRM_DELAY = 2.0
# Rescan cadence while no monitor is available (degraded): applied directly.
DEGRADED_INTERVAL = 3.0
# Delays before reopening the monitor after a failure (the last one repeats).
RESTART_BACKOFF = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
POLL_TIMEOUT = 0.5
# Live events wait until Core has applied the startup list (begin()); this is
# only the fallback if begin() is never called.
BEGIN_TIMEOUT = 5.0


class EnumState:
    """Which USB parents are already represented by a serial interface, and
    the record each present udev device was announced with (by sys_path)."""

    def __init__(self) -> None:
        self.serial_parents: set[str] = set()
        self.emitted_usb: dict[str, RawDevice] = {}
        # usb-serial and net: sys_path -> (raw, parent_sys_path). Removal is
        # resolved against this record, not against the remove event alone.
        self.present: dict[str, tuple] = {}

    def known_paths(self) -> set:
        return set(self.emitted_usb) | set(self.present)


class NullEnumerator:
    def start(self, on_appear, on_disappear, on_change) -> list:
        return []

    def stop(self) -> None:
        return None

    def status(self) -> dict:
        return {"state": "disabled", "restarts": 0, "missed": 0, "last_error": None}


class UdevEnumerator:
    # Defaults for instances built without __init__ (test doubles).
    _rescan_interval = RESCAN_INTERVAL
    _confirm_delay = CONFIRM_DELAY
    _degraded_interval = DEGRADED_INTERVAL
    _restart_backoff = RESTART_BACKOFF
    _poll_timeout = POLL_TIMEOUT
    _supervised = False

    def __init__(
        self,
        pyudev_module=None,
        rescan_interval: float = RESCAN_INTERVAL,
        confirm_delay: float = CONFIRM_DELAY,
        degraded_interval: float = DEGRADED_INTERVAL,
        restart_backoff: tuple = RESTART_BACKOFF,
        poll_timeout: float = POLL_TIMEOUT,
    ) -> None:
        if pyudev_module is None:
            try:
                import pyudev as pyudev_module
            except ImportError as exc:
                raise EnumeratorError("udev unavailable") from exc
        try:
            self._pyudev = pyudev_module
            self._context = pyudev_module.Context()
        except Exception as exc:
            raise EnumeratorError("udev unavailable") from exc
        self._stop = threading.Event()
        self._thread = None
        self._on_appear = None
        self._on_disappear = None
        self._on_change = None
        self._state = EnumState()
        self._supervised = True
        self._rescan_interval = rescan_interval
        self._confirm_delay = confirm_delay
        self._degraded_interval = degraded_interval
        self._restart_backoff = tuple(restart_backoff) or RESTART_BACKOFF
        self._poll_timeout = poll_timeout
        self._apply_lock = threading.RLock()
        self._status_lock = threading.Lock()
        self._status = _initial_status()
        self._monitor = None
        self._go = threading.Event()

    # -- lifecycle -------------------------------------------------------

    def start(self, on_appear, on_disappear, on_change) -> list:
        self._on_appear = on_appear
        self._on_disappear = on_disappear
        self._on_change = on_change
        if not hasattr(self, "_apply_lock"):
            # Constructed without __init__ (test doubles): no supervision, no
            # rescans; the monitor is tried once, exactly as in 0.2.0.
            self._supervised = False
            self._apply_lock = threading.RLock()
            self._status_lock = threading.Lock()
            self._status = _initial_status()
            self._monitor = None
            self._go = threading.Event()
        # The monitor is opened before the scan, so an event that happens while
        # the scan runs is queued in the socket instead of being lost.
        self._monitor = self._open_monitor()
        chosen = self._scan()
        with self._apply_lock:
            self._state = seed_state(chosen)
        self._set_status(state="running" if self._monitor is not None else "degraded")
        self._thread = threading.Thread(target=self._watch, name="task-udev", daemon=True)
        self._thread.start()
        return [raw for raw, _sys, _parent in chosen]

    def begin(self) -> None:
        """Core has applied the list start() returned: deliver live events now.

        Events queued during the scan are held until then, so a removal can never
        be processed before the device it removes was registered."""
        self._go.set()

    def stop(self) -> None:
        self._stop.set()
        go = getattr(self, "_go", None)
        if go is not None:
            go.set()

    def status(self) -> dict:
        """Hot-plug monitor state: running | degraded | restarting | stopped."""
        lock = getattr(self, "_status_lock", None)
        if lock is None:
            return _initial_status()
        with lock:
            return dict(self._status)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # -- monitor ---------------------------------------------------------

    def _open_monitor(self):
        try:
            monitor = self._pyudev.Monitor.from_netlink(self._context)
            monitor.start()
        except Exception as exc:
            self._set_status(last_error=_error_name(exc))
            logger.error("udev monitor unavailable (%s); hot-plug falls back to periodic rescan", _error_name(exc))
            return None
        return monitor

    def _close_monitor(self) -> None:
        monitor, self._monitor = self._monitor, None
        close = getattr(monitor, "close", None)
        if close is None:
            # pyudev.Monitor has no close(); dropping the last reference closes the socket.
            return
        try:
            close()
        except Exception:
            pass

    def _watch(self) -> None:
        clock = time.monotonic
        failures = 0 if self._monitor is not None else 1
        reopen_at = clock() + (self._backoff(1) if self._monitor is None else 0.0)
        pending = None  # (gone, new): a difference seen once, waiting for confirmation
        self._go.wait(BEGIN_TIMEOUT)
        next_scan = clock() + (self._rescan_interval if self._monitor is not None else self._degraded_interval)
        try:
            while not self._stop.is_set():
                if self._monitor is None:
                    if not self._supervised:
                        return
                    now = clock()
                    if now >= reopen_at:
                        self._monitor = self._open_monitor()
                        if self._monitor is not None:
                            failures = 0
                            self._set_status(state="running")
                            logger.warning("udev monitor reopened; resynchronising")
                            self._resync(confirm=False)
                            pending = None
                            next_scan = clock() + self._rescan_interval
                            continue
                        failures += 1
                        reopen_at = now + self._backoff(failures)
                    if now >= next_scan:
                        self._resync(confirm=False)
                        next_scan = clock() + self._degraded_interval
                    self._stop.wait(min(0.25, max(0.01, min(reopen_at, next_scan) - clock())))
                    continue
                try:
                    device = self._monitor.poll(timeout=self._poll_timeout)
                except Exception as exc:
                    name = _error_name(exc)
                    logger.error("udev monitor failed (%s); reopening", name)
                    self._close_monitor()
                    if not self._supervised:
                        self._set_status(state="stopped", last_error=name)
                        return
                    failures += 1
                    self._bump("restarts")
                    self._set_status(state="restarting", last_error=name)
                    reopen_at = clock() + self._backoff(failures)
                    next_scan = clock()  # resync at once while the monitor is down
                    continue
                if device is not None:
                    self._bump("events")
                    try:
                        self._dispatch(device)
                    except Exception:
                        self._bump("dispatch_errors")
                        logger.error("internal error source=udev")
                if self._supervised and self._rescan_interval and clock() >= next_scan:
                    pending = self._resync(confirm=True, pending=pending)
                    next_scan = clock() + (self._confirm_delay if pending else self._rescan_interval)
        finally:
            self._close_monitor()
            self._set_status(state="stopped")

    def _backoff(self, failures: int) -> float:
        steps = self._restart_backoff
        return steps[min(failures, len(steps)) - 1]

    # -- scanning and resynchronisation ------------------------------------

    def _scan(self, skipped: set | None = None) -> list:
        """Scan udev like the 0.1.1 startup scan. With ``skipped`` (resync), devices
        udev has not finished processing are left out and their paths collected."""
        scanned = []
        for subsystem in ("tty", "net", "usb"):
            try:
                devices = self._context.list_devices(subsystem=subsystem)
            except Exception:
                logger.warning("udev enumeration failed")
                continue
            for device in devices:
                if subsystem == "usb" and getattr(device, "device_type", None) not in (
                    None,
                    "usb_device",
                ):
                    continue
                if skipped is not None and not _initialized(device):
                    skipped.add(getattr(device, "sys_path", None))
                    continue
                item = _scan_item(device)
                if item is not None:
                    scanned.append(item)
        return choose_present(scanned)

    def _resync(self, confirm: bool, pending=None):
        """Apply the difference between udev's device list and what was announced.

        With ``confirm`` (monitor running), only a difference that the previous
        scan (``pending``) also saw is applied, and counted as missed; the rest
        is returned as the new ``pending`` (None when there is nothing).
        """
        skipped: set = set()
        try:
            chosen = self._scan(skipped)
        except Exception:
            logger.error("internal error source=udev")
            return None
        current = {sys_path: (raw, parent) for raw, sys_path, parent in chosen if sys_path}
        with self._apply_lock:
            known = self._state.known_paths()
            gone = known - set(current) - skipped
            new = set(current) - known - self._state.serial_parents
            remainder = None
            if confirm:
                previous_gone, previous_new = pending if pending is not None else (set(), set())
                remainder = (gone - previous_gone, new - previous_new)
                gone &= previous_gone
                new &= previous_new
                if not (remainder[0] or remainder[1]):
                    remainder = None
            if gone or new:
                # every change applied here is one the monitor did not deliver
                self._bump("missed", len(gone) + len(new))
                logger.warning("hot-plug monitor missed %d change(s); resynchronised", len(gone) + len(new))
            for sys_path in sorted(gone):
                stored = self._stored(sys_path)
                if stored is not None:
                    self._run(apply_event(self._state, stored[0], sys_path, stored[1], "remove"), stored[0], "remove")
            for raw, sys_path, parent in chosen:
                if sys_path in new:
                    self._run(apply_event(self._state, raw, sys_path, parent, "add"), raw, "add")
        return remainder

    def _stored(self, sys_path):
        if sys_path in self._state.emitted_usb:
            return self._state.emitted_usb[sys_path], None
        return self._state.present.get(sys_path)

    # -- events ------------------------------------------------------------

    def _dispatch(self, device) -> None:
        subsystem = device.subsystem or ""
        if subsystem not in ("tty", "net", "usb"):
            return
        if subsystem == "usb" and getattr(device, "device_type", None) not in (
            None,
            "usb_device",
        ):
            return
        action = getattr(device, "action", None)
        sys_path = getattr(device, "sys_path", None)
        raw = _from_udev(device)
        if raw is None:
            # A remove event can lack the udev properties that classified the
            # device on add; the record it was announced with still identifies it.
            if _action_kind(action) != "remove" or not sys_path:
                return
            with self._apply_lock:
                stored = self._stored(sys_path)
            if stored is None:
                return
            raw = stored[0]
        parent = _usb_parent(device) if raw.subsystem == "usb-serial" else None
        parent_path = getattr(parent, "sys_path", None) if parent is not None else None
        with self._apply_lock:
            if action == "move":
                # a renamed device (e.g. a network interface) leaves its old path
                old = _old_sys_path(device)
                if old:
                    self._state.present.pop(old, None)
                    self._state.emitted_usb.pop(old, None)
            ops = apply_event(self._state, raw, sys_path, parent_path, action)
            self._run(ops, raw, action)

    def _run(self, ops, raw, action) -> None:
        withdrawing_parent = raw.subsystem == "usb-serial" and _action_kind(action) != "remove"
        for kind, item in ops:
            if kind == "disappear":
                if withdrawing_parent and item is not raw:
                    # The USB parent was announced before its serial interface
                    # existed (normal hot-plug order). The interface now represents
                    # the device, so the parent is withdrawn (PHASE-1.md section 2).
                    self._on_disappear(item, replaced=True)
                else:
                    self._on_disappear(item)
            elif kind == "change":
                self._on_change(item)
            else:
                self._on_appear(item)

    # -- status ------------------------------------------------------------

    def _set_status(self, **fields) -> None:
        with self._status_lock:
            self._status.update(fields)

    def _bump(self, name: str, amount: int = 1) -> None:
        with self._status_lock:
            self._status[name] = self._status.get(name, 0) + amount


def _initialized(device) -> bool:
    try:
        return bool(getattr(device, "is_initialized", True))
    except Exception:
        return False


def _old_sys_path(device):
    try:
        old = (getattr(device, "properties", {}) or {}).get("DEVPATH_OLD")
    except Exception:
        return None
    return f"/sys{old}" if old else None


def _initial_status() -> dict:
    return {"state": "starting", "restarts": 0, "missed": 0, "events": 0, "dispatch_errors": 0,
            "last_error": None}


def _error_name(exc: BaseException) -> str:
    code = getattr(exc, "errno", None)
    if isinstance(code, int) and code in errno.errorcode:
        return errno.errorcode[code]
    return type(exc).__name__


def choose_present(items: list[tuple]) -> list[tuple]:
    """Drop a USB parent when its serial interface is already present.

    `items` are `(raw, sys_path, parent_sys_path)`. The serial interface is
    the record that carries the devnode and by-id link. Identity keys are
    not merged.
    """
    parents = {
        parent
        for raw, _sys, parent in items
        if raw.subsystem == "usb-serial" and parent
    }
    chosen = []
    for raw, sys_path, parent in items:
        if raw.subsystem == "usb" and sys_path and sys_path in parents:
            continue
        chosen.append((raw, sys_path, parent))
    return chosen


def seed_state(chosen: list[tuple]) -> EnumState:
    state = EnumState()
    for raw, sys_path, parent in chosen:
        if raw.subsystem == "usb-serial" and parent:
            state.serial_parents.add(parent)
        if raw.subsystem == "usb" and sys_path:
            state.emitted_usb[sys_path] = raw
        elif sys_path:
            state.present[sys_path] = (raw, parent)
    return state


def apply_event(state: EnumState, raw: RawDevice, sys_path, parent_path, action) -> list:
    """Return `("appear"|"change"|"disappear", raw)` operations. Updates `state`.

    A removal is reported with the record the device was announced with (looked
    up by sys_path), so it matches even when the remove event carries fewer
    udev properties than the add did. The event's own record is the fallback.
    """
    kind = _action_kind(action)
    if raw.subsystem == "usb-serial":
        if kind == "remove":
            stored = state.present.pop(sys_path, None) if sys_path else None
            if stored is not None:
                raw = stored[0]
                parent_path = parent_path or stored[1]
            if parent_path:
                state.serial_parents.discard(parent_path)
            return [("disappear", raw)]
        ops = []
        if parent_path:
            state.serial_parents.add(parent_path)
            previous = state.emitted_usb.pop(parent_path, None)
            if previous is not None:
                ops.append(("disappear", previous))
        if sys_path:
            state.present[sys_path] = (raw, parent_path)
        ops.append(("change" if kind == "change" else "appear", raw))
        return ops
    if raw.subsystem == "usb":
        if kind == "remove":
            if sys_path:
                stored = state.emitted_usb.pop(sys_path, None)
                if stored is not None:
                    raw = stored
            return [("disappear", raw)]
        if sys_path and sys_path in state.serial_parents:
            return []
        if sys_path:
            state.emitted_usb[sys_path] = raw
        return [("change" if kind == "change" else "appear", raw)]
    if kind == "remove":
        stored = state.present.pop(sys_path, None) if sys_path else None
        return [("disappear", stored[0] if stored is not None else raw)]
    if sys_path:
        state.present[sys_path] = (raw, None)
    if kind == "change":
        return [("change", raw)]
    return [("appear", raw)]


def _action_kind(action) -> str:
    if action in ("remove", "unbind"):
        return "remove"
    if action == "change":
        return "change"
    return "appear"


def _scan_item(device):
    raw = _from_udev(device)
    if raw is None:
        return None
    parent = _usb_parent(device) if raw.subsystem == "usb-serial" else None
    parent_path = getattr(parent, "sys_path", None) if parent is not None else None
    return raw, getattr(device, "sys_path", None), parent_path


def _from_udev(device) -> RawDevice | None:
    subsystem = device.subsystem or ""
    if subsystem == "net":
        mapped = "net"
    elif subsystem == "tty":
        if not _tty_is_usb(device):
            return None
        mapped = "usb-serial"
    elif subsystem == "usb":
        mapped = "usb"
    else:
        return None
    props = device.properties
    by_id = None
    for link in str(props.get("DEVLINKS", "")).split():
        if "/serial/by-id/" in link:
            by_id = link
            break
    mac = None
    if mapped == "net":
        mac = _sysfs_text(device, "perm_address") or _sysfs_text(device, "address")
    bus_path = props.get("ID_PATH") or getattr(device, "sys_name", None)
    return RawDevice(
        devnode=getattr(device, "device_node", None),
        by_id=by_id,
        vid=props.get("ID_VENDOR_ID"),
        pid=props.get("ID_MODEL_ID"),
        serial=props.get("ID_SERIAL_SHORT") or None,
        manufacturer=props.get("ID_VENDOR") or None,
        product=props.get("ID_MODEL") or None,
        subsystem=mapped,
        mac=mac,
        bus_path=str(bus_path) if bus_path else None,
    )


def _tty_is_usb(device) -> bool:
    """True only when udev or sysfs says this tty is a USB device."""
    props = getattr(device, "properties", {}) or {}
    if str(props.get("ID_BUS") or "").lower() == "usb":
        return True
    if props.get("ID_USB_DRIVER"):
        return True
    if "/serial/by-id/usb-" in str(props.get("DEVLINKS") or ""):
        return True
    return _usb_parent(device) is not None


def _usb_parent(device):
    find = getattr(device, "find_parent", None)
    if find is None:
        return None
    try:
        return find("usb", "usb_device")
    except Exception:
        return None


def _sysfs_text(device, name: str) -> str | None:
    try:
        value = device.attributes.get(name)
    except Exception:
        return None
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).strip()
    return text or None
