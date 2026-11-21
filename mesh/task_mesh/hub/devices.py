# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Device manager: /dev/serial/by-id scan, explicit protocol assignments, one owner per device.

Safety rule: the manager opens ONLY devices the user explicitly assigned to a protocol (Devices tab,
$XDG_CONFIG_HOME/task-mesh/radio-protocols.json). Unassigned ports (GPS, TNC, SDR, APRS radios, ...) are listed but
never opened. "Identify" (read-only probe) runs only on an explicit user click. task-mesh never writes
/var/lib/rain/devices.json, /etc/rain/* or any radio/GPS configuration.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from task_mesh.hub.locks import Busy, device_lock
from task_mesh.hub.model import PROTOCOLS, DeviceStatus

log = logging.getLogger(__name__)
BY_ID = Path("/dev/serial/by-id")
IGNORE = "ignore"


def scan_by_id(directory: Path = BY_ID) -> dict[str, str]:
    """{key (by-id basename): open path}. Missing directory -> {}. Never opens anything."""
    try:
        return {e.name: str(e) for e in sorted(Path(directory).iterdir())}
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return {}


class Assignments:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        out = {}
        for k, v in (data.get("devices") or {}).items() if isinstance(data, dict) else ():
            if isinstance(k, str) and v in (*PROTOCOLS, IGNORE):
                out[k] = v
        return out

    def set(self, key: str, protocol: Optional[str]) -> None:
        """Explicit user action. protocol None removes the assignment."""
        if protocol is not None and protocol not in (*PROTOCOLS, IGNORE):
            raise ValueError("protocol")
        with self._lock:
            cur = self.load()
            if protocol is None:
                cur.pop(key, None)
            else:
                cur[key] = protocol
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump({"schema": 1, "devices": cur}, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)


AdapterFactory = Callable[..., object]   # factory(path=, key=, sink=) -> adapter with start()/stop()/send_text()


class DeviceManager:
    def __init__(self, assignments: Assignments, factories: dict[str, AdapterFactory], sink, role: str,
                 scan: Callable[[], dict] = scan_by_id, lock_factory=device_lock, clock=time.time) -> None:
        self.assignments = assignments
        self.factories = factories
        self.sink = sink
        self.role = role
        self.scan = scan
        self.lock_factory = lock_factory
        self.clock = clock
        self._lock = threading.RLock()
        self.status: dict[str, DeviceStatus] = {}
        self.adapters: dict[str, object] = {}
        self._locks: dict[str, object] = {}

    def _set(self, key: str, path: str, **fields) -> DeviceStatus:
        st = self.status.get(key) or DeviceStatus(key=key, path=path)
        st.path = path or st.path
        for k, v in fields.items():
            setattr(st, k, v)
        st.last_change = self.clock()
        self.status[key] = st
        try:
            self.sink.on_device(st)
        except Exception:  # noqa: BLE001
            log.exception("device listener failed")
        return st

    def on_adapter_status(self, key: str, **fields) -> None:
        with self._lock:
            st = self.status.get(key)
            if st is not None:
                self._set(key, st.path, **fields)

    def poll(self) -> None:
        present = self.scan()
        assigned = self.assignments.load()
        with self._lock:
            for key in list(self.adapters):
                if key not in present or assigned.get(key) != getattr(self.adapters[key], "protocol", None):
                    self._stop(key, "removed" if key not in present else "unassigned")
            for key in list(self.status):
                if key not in present:
                    del self.status[key]
            for key, path in present.items():
                proto = assigned.get(key)
                if key in self.adapters:
                    continue
                if proto in PROTOCOLS and proto not in self.factories:
                    self._set(key, path, protocol=proto, protocol_source="user", state="external", owner="",
                              detail="handled by the Meshtastic panel (GUI direct mode)")
                elif proto in PROTOCOLS:
                    self._start(key, path, proto)          # also retries a device another process held
                else:
                    self._set(key, path, protocol=None, protocol_source="user" if proto else "unknown",
                              state="ignored" if proto == IGNORE else "unassigned", owner="", detail="")

    def _start(self, key: str, path: str, proto: str) -> None:
        lock = self.lock_factory(path, self.role)
        try:
            lock.acquire()
        except Busy as b:
            self._set(key, path, protocol=proto, protocol_source="user", state="busy", owner=b.owner,
                      detail=f"in use by {b.owner}")
            return
        self._locks[key] = lock
        self._set(key, path, protocol=proto, protocol_source="user", state="connecting", owner=self.role, detail="")
        adapter = self.factories[proto](path=path, key=key, sink=self)
        self.adapters[key] = adapter
        adapter.start()

    def _stop(self, key: str, why: str) -> None:
        adapter = self.adapters.pop(key, None)
        if adapter is not None:
            try:
                adapter.stop()
            except Exception:  # noqa: BLE001
                log.exception("adapter stop failed")
        lock = self._locks.pop(key, None)
        if lock is not None:
            lock.release()
        st = self.status.get(key)
        if st is not None:
            self._set(key, st.path, state="idle", owner="", detail=why)

    # sink passthrough for adapters
    def on_message(self, m):
        return self.sink.on_message(m)

    def on_node(self, n):
        return self.sink.on_node(n)

    def adapter_for(self, protocol: str, device: Optional[str] = None):
        with self._lock:
            for key, a in self.adapters.items():
                if a.protocol == protocol and (device is None or key == device):
                    return a
        return None

    def shutdown(self) -> None:
        with self._lock:
            for key in list(self.adapters):
                self._stop(key, "shutdown")
