# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""H1 test harness: the real UdevEnumerator with a stand-in pyudev Monitor.

The stand-in Monitor delivers queued udev events from ``poll()``, can raise
OSError(ENOBUFS) as pyudev 0.24 does on a netlink receive-buffer overflow, and
``from_netlink`` can fail as it does when the socket cannot be created. No real
netlink socket and no hardware are used. Shared by the core and console tests
(it imports nothing from either conftest).
"""

import errno
import threading
import time

from task_core.enumerator import UdevEnumerator

SDR_SYS_PATH = "/sys/devices/platform/axi/1000120000.pcie/1f00300000.usb/xhci-hcd.1/usb3/3-1"


class Udev:
    """The pyudev.Device surface task_core.enumerator reads (as in test_hotplug_parent_dedup)."""

    def __init__(self, subsystem, sys_path, properties, device_type=None, device_node=None, action=None):
        self.subsystem = subsystem
        self.sys_path = sys_path
        self.sys_name = sys_path.rsplit("/", 1)[-1]
        self.properties = properties
        self.device_type = device_type
        self.device_node = device_node
        self.attributes = {}
        self.action = action

    def find_parent(self, subsystem, device_type=None):
        return None

    def at(self, action):
        return Udev(self.subsystem, self.sys_path, self.properties, self.device_type, self.device_node, action)


def sdr_udev():
    """RTL-SDR Blog V4 exactly as test_hotplug_parent_dedup.rtlsdr() (TEST DATA)."""
    return Udev("usb", SDR_SYS_PATH, {
        "ID_VENDOR_ID": "0bda", "ID_MODEL_ID": "2838", "ID_SERIAL_SHORT": "00000001",
        "ID_VENDOR": "RTLSDRBlog", "ID_MODEL": "Blog_V4", "ID_PATH": "platform-xhci-hcd.1-usb-0:1",
    }, device_type="usb_device", device_node="/dev/bus/usb/003/002")


class FakeMonitor:
    """The pyudev.Monitor surface the enumerator uses: start, poll, close.

    Like a netlink multicast socket, it only receives events published after it
    was started and before it was closed; an overflow (``context.blocked``) drops
    what it had queued and makes ``poll`` raise OSError(ENOBUFS).
    """

    def __init__(self, context):
        self.context = context
        self.started = False
        self.closed = False
        self.queue = []

    def start(self):
        with self.context._cond:
            if not self.started:
                self.started = True
                self.context.monitors.append(self)

    def close(self):
        with self.context._cond:
            self.closed = True
            if self in self.context.monitors:
                self.context.monitors.remove(self)

    def poll(self, timeout=None):
        if not self.started:
            raise RuntimeError("poll before start")
        cond = self.context._cond
        with cond:
            deadline = time.monotonic() + (timeout or 0)
            while not self.queue and not self.context.blocked and time.monotonic() < deadline:
                cond.wait(timeout=max(0.0, deadline - time.monotonic()))
            if self.context.blocked:
                self.queue.clear()  # the kernel dropped them
                raise OSError(errno.ENOBUFS, "No buffer space available")
            return self.queue.pop(0) if self.queue else None


class _Context:
    def __init__(self, *args, **kwargs):
        pass


def _pyudev_for(context, opens, failures):
    """A pyudev stand-in whose Monitor.from_netlink consults `failures`, then opens."""

    def from_netlink(_context, source="udev"):
        if failures:
            raise failures.pop(0)
        monitor = FakeMonitor(context)
        opens.append(monitor)
        return monitor

    monitor_type = type("Monitor", (), {"from_netlink": staticmethod(from_netlink)})
    return type("Pyudev", (), {"Context": _Context, "Monitor": monitor_type})


class LiveContext:
    """udev's device list (list_devices) plus multicast delivery of udev events."""

    def __init__(self, devices):
        self.devices = list(devices)
        self.monitors = []
        self._cond = threading.Condition()
        self.blocked = False

    def list_devices(self, subsystem):
        return [item for item in self.devices if item.subsystem == subsystem]

    def push(self, *events):
        """Publish events; only monitors that are open right now receive them."""
        with self._cond:
            for monitor in self.monitors:
                monitor.queue.extend(events)
            self._cond.notify_all()

    def add(self, device):
        self.devices = [item for item in self.devices if item.sys_path != device.sys_path]
        self.devices.append(device)

    def drop(self, device):
        self.devices = [item for item in self.devices if item.sys_path != device.sys_path]


class LiveEnumerator(UdevEnumerator):
    def __init__(self, context, failures=None, **kwargs):
        self.opens = []
        module = _pyudev_for(context, self.opens, failures or [])
        try:
            super().__init__(pyudev_module=module, **kwargs)
        except TypeError:
            # b6dd151 (unfixed) has no injection point: set what its __init__ sets,
            # then run its real start/_watch/_dispatch unchanged (red-run evidence).
            import threading as _threading

            from task_core.enumerator import EnumState

            self._pyudev = module
            self._stop = _threading.Event()
            self._thread = None
            self._on_appear = self._on_disappear = self._on_change = None
            self._state = EnumState()
        self._context = context  # the stand-in, not a real pyudev.Context

    def status(self):
        base = getattr(UdevEnumerator, "status", None)
        if base is None:  # b6dd151: no status at all
            return {"state": "unreported", "restarts": 0, "missed": 0, "events": 0, "last_error": None}
        return base(self)


def _fast(**overrides):
    options = dict(rescan_interval=0.05, confirm_delay=0.02, degraded_interval=0.05,
                   restart_backoff=(0.02, 0.05), poll_timeout=0.02)
    options.update(overrides)
    return options


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


