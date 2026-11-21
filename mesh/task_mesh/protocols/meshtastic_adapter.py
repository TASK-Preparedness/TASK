# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Meshtastic adapter for the hub (headless service mode): the 0.2.0 MeshtasticProvider (vendored meshtastic
2.7.11) on one assigned device, with a watchdog and backoff reconnect.

* Normalises text packets to HubMessage; priority only from protocol metadata (MeshPacket.priority ALERT,
  BEL character), labelled "protocol:...".
* Texts whose radio rxTime is older than the session start (minus 120 s) are origin=SYNC (not new).
* Never changes radio settings: only the connect handshake, node snapshot, heartbeat and explicit send_text.
* In GUI direct mode the 0.2.0 RadioWorker keeps owning Meshtastic (unchanged) and feeds the hub instead.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

from task_mesh.domain.models import PortCandidate
from task_mesh.hub.model import LIVE, SYNC, HubMessage, HubNode, dedupe_key
from task_mesh.messaging.packets import BROADCAST_NUM

log = logging.getLogger(__name__)
BACKOFF = (2, 5, 10, 30, 60)
SYNC_SLACK_S = 120


def default_provider_factory(sink):
    from task_mesh.radio.meshtastic.provider import MeshtasticProvider
    return MeshtasticProvider(sink)


def text_to_hub(t, device: str, clock: float, session_start: Optional[float], names: Optional[dict] = None) -> HubMessage:
    """messaging.packets.TextPacket -> HubMessage (shared by service and GUI direct mode)."""
    from task_comms.notifications import classify_priority
    sender = f"!{t.from_num:08x}"
    conv = f"dm:{sender}" if t.is_direct else f"ch:{t.channel}"
    prio, reason = classify_priority(t.text, t.priority, sender, conv)
    origin = SYNC if (session_start and t.rx_time and t.rx_time < session_start - SYNC_SLACK_S) else LIVE
    key = dedupe_key("meshtastic", t.packet_id, t.from_num) if t.packet_id else dedupe_key("meshtastic", t.from_num,
                                                                                            t.rx_time, t.text)
    return HubMessage(protocol="meshtastic", device=device, key=key, direction="in",
                      kind="dm" if t.is_direct else "channel", conversation=conv, sender=sender,
                      sender_label=(names or {}).get(sender, sender), text=t.text, ts=clock,
                      sender_ts=t.rx_time, origin=origin, priority=prio, priority_source=reason)


class MeshtasticAdapter:
    protocol = "meshtastic"

    def __init__(self, path: str, key: str, sink, provider_factory: Callable = default_provider_factory,
                 backoff=BACKOFF, clock: Callable[[], float] = time.time, watchdog_s: float = 5.0) -> None:
        self.path, self.key, self.sink = path, key, sink
        self.factory = provider_factory
        self.backoff = backoff
        self.clock = clock
        self.watchdog_s = watchdog_s
        self.provider = None
        self.local_num: Optional[int] = None
        self.session_start: Optional[float] = None
        self.names: dict = {}
        self.connected = threading.Event()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._gen = 0
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"meshtastic-{self.key}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15) -> None:
        self._stop.set()
        self._lost.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _status(self, **f) -> None:
        try:
            self.sink.on_adapter_status(self.key, **f)
        except Exception:  # noqa: BLE001
            log.exception("status sink failed")

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            self._gen += 1
            self._lost.clear()
            self._status(state="connecting", detail="")
            prov = self.factory(self)
            self.provider = prov
            try:
                cand = PortCandidate(device=os.path.realpath(self.path), by_id=self.path, open_path=self.path)
                ident = prov.connect(cand, self._gen)
                self.local_num = ident.node_num
                self.session_start = self.clock()
                self._status(state="connected", model=ident.hw_model or "", firmware=ident.firmware_version or "",
                             name=ident.long_name or ident.short_name or ident.node_id or "", detail="")
                for info in prov.snapshot_nodes():
                    self.on_nodeinfo(self._gen, info)
                self.connected.set()
                attempt = 0
                while not self._stop.is_set() and not self._lost.wait(self.watchdog_s):
                    if not prov.is_alive():
                        break
                if not self._stop.is_set():
                    raise ConnectionError("radio link lost")
            except Exception as exc:  # noqa: BLE001
                code = getattr(getattr(exc, "code", None), "value", None)
                self._status(state="error", detail=f"{code or type(exc).__name__}: {getattr(exc, 'message', str(exc))[:120]}")
            finally:
                self.connected.clear()
                try:
                    prov.close()
                except Exception:  # noqa: BLE001
                    pass
                self.provider = None
            if self._stop.is_set():
                break
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            self._status(state="backoff", detail=f"reconnecting in {delay} s")
            self._stop.wait(delay)

    # --- RadioEventSink (library threads) ------------------------------------------------------------
    def on_established(self, generation: int) -> None:
        pass

    def on_lost(self, generation: int) -> None:
        if generation == self._gen:
            self._lost.set()

    def on_nodeinfo(self, generation: int, info) -> None:
        if generation != self._gen:
            return
        u, pos = info.user, info.position
        nid = (u.node_id if u and u.node_id else f"!{info.node_num:08x}")
        name = (u.long_name or u.short_name) if u else None
        if name:
            self.names[nid] = name[:32]
        self.sink.on_node(HubNode(protocol="meshtastic", key=nid, name=(name or "")[:32], role=(u.role or "") if u else "",
                                  last_heard=float(info.last_heard_radio) if info.last_heard_radio else None,
                                  snr=info.snr, hops=info.hops_away,
                                  lat=pos.latitude if pos else None, lon=pos.longitude if pos else None, device=self.key))

    def on_observation(self, generation: int, obs) -> None:
        if generation == self._gen and obs.node_num and obs.node_num != self.local_num:
            self.sink.on_node(HubNode(protocol="meshtastic", key=f"!{obs.node_num:08x}", last_heard=self.clock(),
                                      snr=obs.rx_snr, rssi=obs.rx_rssi, device=self.key))

    def on_radio_event(self, generation: int, event) -> None:
        pass

    def on_text(self, generation: int, t) -> None:
        if generation != self._gen or (self.local_num is not None and t.from_num == self.local_num):
            return
        if self.local_num is not None and t.is_direct and t.to_num != self.local_num:
            return                                   # a DM for someone else that our radio forwarded
        self.sink.on_message(text_to_hub(t, self.key, self.clock(), self.session_start, self.names))

    def on_routing(self, generation: int, routing) -> None:
        pass                                         # ACK tracking stays in the 0.2.0 Messages tab (direct mode)

    # --- explicit user action ----------------------------------------------------------------------
    def send_text(self, conversation: str, text: str) -> str:
        prov = self.provider
        if prov is None or not self.connected.is_set():
            raise ConnectionError("Meshtastic radio not connected")
        if conversation.startswith("ch:"):
            ch = int(conversation[3:])
            if not 0 <= ch <= 7:
                raise ValueError("channel index must be 0-7")
            dest = BROADCAST_NUM
        elif conversation.startswith("dm:!") and len(conversation) == 12:
            dest, ch = int(conversation[4:], 16), 0
        else:
            raise ValueError("bad conversation")
        pid = prov.send_text(text, dest, ch)
        return "sent" if pid else "failed"
