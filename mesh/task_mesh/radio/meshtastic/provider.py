# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""MeshtasticProvider: owns one SerialInterface (vendored meshtastic 2.7.11) at a time.

All methods except the pubsub callbacks are called from T.A.S.K.'s radio worker (or its helper
threads), never the GUI thread: the constructor blocks 0.5–31 s and close() sleeps and joins.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any, Callable, Optional

from task_mesh.core.errors import ErrorCode
from task_mesh.domain.models import NodeInfoData, PortCandidate, RadioIdentity
from task_mesh.radio.base import ConnectError, RadioEventSink
from task_mesh.radio.discovery import is_busy_error
from task_mesh.radio.meshtastic.nodes import snapshot
from task_mesh.radio.meshtastic.packets import parse_user
from task_mesh.radio.meshtastic.pubsub_bridge import PubSubBridge

log = logging.getLogger(__name__)
InterfaceFactory = Callable[..., Any]


def default_interface_factory(devPath: str, timeout: int) -> Any:  # noqa: N803 - library naming
    import meshtastic.serial_interface  # vendored; imported lazily

    return meshtastic.serial_interface.SerialInterface(devPath=devPath, timeout=timeout)


def _map_exception(exc: BaseException) -> ConnectError:
    name = type(exc).__name__
    text = str(exc) or name
    if isinstance(exc, FileNotFoundError):
        return ConnectError(ErrorCode.NO_DEVICE, f"device disappeared: {text}")
    if isinstance(exc, PermissionError):
        return ConnectError(ErrorCode.PERMISSION_DENIED, text)
    if name == "MeshInterfaceError" and "Timed out" in text:
        return ConnectError(ErrorCode.HANDSHAKE_TIMEOUT, text)
    if name == "SerialException" or isinstance(exc, OSError):
        if is_busy_error(exc):
            return ConnectError(ErrorCode.PORT_BUSY, text)
        return ConnectError(ErrorCode.SERIAL_ERROR, text)
    if isinstance(exc, SystemExit):
        return ConnectError(ErrorCode.UNEXPECTED, f"library attempted to exit the process (code {exc.code})")
    if isinstance(exc, ImportError):
        return ConnectError(ErrorCode.LIBRARY_MISSING, text)
    return ConnectError(ErrorCode.UNEXPECTED, f"{name}: {text}")


class MeshtasticProvider:
    def __init__(
        self,
        sink: RadioEventSink,
        interface_factory: Optional[InterfaceFactory] = None,
        library_timeout_s: int = 300,
        now: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        self._factory = interface_factory or default_interface_factory
        self._timeout = library_timeout_s
        self._bridge = PubSubBridge(sink, now)  # strong reference (pypubsub holds weak refs)
        self._lock = threading.Lock()
        self._iface: Any = None
        self._generation: Optional[int] = None

    @property
    def counters(self) -> dict:
        return dict(self._bridge.counters)

    @property
    def current_generation(self) -> Optional[int]:
        return self._generation

    def connect(self, candidate: PortCandidate, generation: int) -> RadioIdentity:
        self.close()
        self._bridge.subscribe()
        self._bridge.begin(generation)
        self._generation = generation
        path = candidate.open_path or candidate.device
        log.info("opening %s", path, extra={"event": "radio.connect", "port": path})
        try:
            iface = self._factory(devPath=path, timeout=self._timeout)
        except BaseException as exc:  # noqa: BLE001 - includes SystemExit from the library
            self._bridge.detach()
            self._generation = None
            err = _map_exception(exc)
            log.warning("connect failed: %s", err.code.value,
                        extra={"event": "radio.connect_failed", "port": path, "err_type": type(exc).__name__})
            raise err from None
        if getattr(iface, "isConnected", None) is None:
            # Half-built object (only possible with devPath=None, which we never pass).
            self._bridge.detach()
            raise ConnectError(ErrorCode.UNEXPECTED, "library returned an unconnected interface")
        with self._lock:
            self._iface = iface
        self._bridge.attach(iface)
        return self.identity()

    def identity(self) -> RadioIdentity:
        iface = self._iface
        if iface is None:
            raise ConnectError(ErrorCode.UNEXPECTED, "not connected")
        my = getattr(iface, "myInfo", None)
        num = getattr(my, "my_node_num", None)
        if not isinstance(num, int) or num <= 0:
            raise ConnectError(ErrorCode.UNEXPECTED, "radio did not report its node number")
        meta = getattr(iface, "metadata", None)
        fw = getattr(meta, "firmware_version", None) or None
        user = None
        try:
            node = (getattr(iface, "nodesByNum", None) or {}).get(num)
            if isinstance(node, dict):
                user = parse_user(copy.deepcopy(node.get("user")), num)
        except Exception:  # noqa: BLE001
            user = None
        return RadioIdentity(
            node_num=num,
            node_id=(user.node_id if user else None) or f"!{num:08x}",
            long_name=user.long_name if user else None,
            short_name=user.short_name if user else None,
            hw_model=user.hw_model if user else None,
            firmware_version=fw if isinstance(fw, str) else None,
        )

    def snapshot_nodes(self) -> list[NodeInfoData]:
        iface = self._iface
        if iface is None:
            return []
        nodes, bad = snapshot(iface)
        self._bridge.counters["bad_packets"] += bad
        return nodes

    def is_alive(self) -> bool:
        iface = self._iface
        if iface is None:
            return False
        rx = getattr(iface, "_rxThread", None)  # private; pinned by a contract test
        if isinstance(rx, threading.Thread):
            return rx.is_alive()
        ev = getattr(iface, "isConnected", None)
        return bool(ev is not None and ev.is_set())

    def port_open(self) -> bool:
        iface = self._iface
        return iface is not None and getattr(iface, "stream", None) is not None

    def send_heartbeat(self) -> None:
        iface = self._iface
        if iface is None or getattr(iface, "stream", None) is None:
            raise ConnectError(ErrorCode.CONNECTION_LOST, "no open stream")
        iface.sendHeartbeat()

    def send_text(self, text: str, dest_num: int, channel: int) -> int:
        """Explicit user message (wantAck so the mesh reports ACK/NAK). Returns the packet id."""
        iface = self._iface
        if iface is None or getattr(iface, "stream", None) is None:
            raise ConnectError(ErrorCode.CONNECTION_LOST, "no open stream")
        pkt = iface.sendText(text, destinationId=dest_num, wantAck=True, channelIndex=channel)
        pid = getattr(pkt, "id", None)
        if pid is None and isinstance(pkt, dict):
            pid = pkt.get("id")
        log.info("message sent", extra={"event": "mesh.send", "channel": channel,
                                        "direct": dest_num != 0xFFFFFFFF, "bytes": len(text.encode())})
        return int(pid) if isinstance(pid, int) else 0

    def channels(self) -> list[tuple[int, str, str]]:
        """[(index, name, role)] of enabled channels. The PSK is never read."""
        iface = self._iface
        node = getattr(iface, "localNode", None) if iface is not None else None
        out = []
        for ch in list(getattr(node, "channels", None) or []):
            role = getattr(ch, "role", 0)
            role_name = {1: "PRIMARY", 2: "SECONDARY"}.get(role if isinstance(role, int) else 0)
            if role_name is None:
                continue
            settings = getattr(ch, "settings", None)
            name = getattr(settings, "name", "") if settings is not None else ""
            idx = getattr(ch, "index", None)
            if isinstance(idx, int):
                out.append((idx, (name or ("Primary" if role == 1 else f"Channel {idx}"))[:16], role_name))
        return out

    def close(self) -> None:
        with self._lock:
            iface, self._iface = self._iface, None
        self._bridge.detach()
        self._generation = None
        if iface is None:
            return
        try:
            iface.close()
        except BaseException as exc:  # noqa: BLE001
            log.warning("error while closing interface: %s", type(exc).__name__,
                        extra={"event": "radio.close_error", "err_type": type(exc).__name__})

    def shutdown(self) -> None:
        self.close()
        self._bridge.unsubscribe()
