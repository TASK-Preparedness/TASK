# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Channel messages and direct messages with honest delivery states (Qt-free core).

Outgoing states (r2 §6.1, design report §5.8):
  queued     handed to the radio worker, not yet accepted by the library
  sent       the library wrote the packet to the radio (has a packet id)
  relayed    implicit ACK: our own radio heard a neighbour rebroadcast it (DM or channel)
  delivered  explicit ACK from the DM destination node itself (DMs only)
  failed     NAK from the mesh, with the radio's reason (e.g. NO_ROUTE, MAX_RETRANSMIT)
  no-ack     nothing heard within ACK_TIMEOUT_S
Channel broadcasts are never "delivered": nobody acknowledges on behalf of every member.
Sending needs an operator session; history needs a session. Nothing is sent automatically.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from task_mesh.messaging.packets import BROADCAST_NUM, MAX_TEXT_BYTES, RoutingPacket, TextPacket
from task_mesh.messaging.store import MessageStore

log = logging.getLogger(__name__)
ACK_TIMEOUT_S = 180
BROADCAST_PEER = "^all"
FINAL = ("delivered", "failed", "no-ack")


def node_id(num: int) -> str:
    return f"!{num:08x}"


def parse_node_id(text: str) -> int:
    t = text.strip().lower()
    if not (len(t) == 9 and t.startswith("!")):
        raise ValueError("node id must look like !1a2b3c4d")
    return int(t[1:], 16)


class MessageError(Exception):
    pass


class MessageService:
    def __init__(self, store: MessageStore, gate, sender: Optional[Callable] = None,
                 clock: Callable[[], float] = time.time, run_async: Optional[Callable] = None) -> None:
        self.store = store
        self.gate = gate
        self.sender = sender            # sender(text, dest_num_or_broadcast, channel) -> packet_id ; may raise
        self.clock = clock
        self.local_num: Optional[int] = None
        self._run = run_async or (lambda fn: threading.Thread(target=fn, name="task-send", daemon=True).start())
        self._lock = threading.Lock()
        self._by_packet: dict[int, int] = {}
        self.listeners: list[Callable[[str, dict], None]] = []
        self.unread = 0
        gate.listeners.append(self._session_ended)

    # ------------------------------------------------------------------ session
    def unlock(self) -> None:
        if not self.gate.unlocked:
            raise MessageError("sign in to open message history")
        self.store.open()
        with self._lock:
            for row in self.store.pending():
                if row["packet_id"]:
                    self._by_packet[row["packet_id"]] = row["local_id"]

    def _session_ended(self, reason: str) -> None:
        self.store.close()
        with self._lock:
            self._by_packet.clear()
        self._emit("locked", {"reason": reason})

    def _emit(self, kind: str, data: dict) -> None:
        for cb in list(self.listeners):
            try:
                cb(kind, data)
            except Exception:  # noqa: BLE001
                log.exception("message listener failed")

    # ------------------------------------------------------------------ send
    def validate(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise MessageError("message is empty")
        n = len(text.encode("utf-8"))
        if n > MAX_TEXT_BYTES:
            raise MessageError(f"message is {n} bytes (max {MAX_TEXT_BYTES})")
        return text

    def send(self, text: str, *, channel: int = 0, dest: Optional[str] = None) -> int:
        """Explicit user action only. dest None = channel broadcast; else '!xxxxxxxx' DM."""
        ok, why = self.gate.require("operator")
        if not ok:
            raise MessageError(why)
        if not self.store.is_open:
            self.unlock()
        if self.sender is None:
            raise MessageError("no radio connected")
        text = self.validate(text)
        if not 0 <= channel <= 7:
            raise MessageError("channel index must be 0-7")
        dest_num = BROADCAST_NUM if dest is None else parse_node_id(dest)
        if self.local_num is not None and dest_num == self.local_num:
            raise MessageError("that is this radio")
        peer = BROADCAST_PEER if dest is None else node_id(dest_num)
        lid = self.store.add(direction="out", channel=channel, peer=peer,
                             from_id=node_id(self.local_num) if self.local_num else "local",
                             text=text, ts=int(self.clock()), state="queued")
        self._emit("added", self.store.get(lid))

        def work() -> None:
            try:
                pid = self.sender(text, dest_num, channel)
            except Exception as exc:  # noqa: BLE001
                self._set(lid, "failed", f"radio refused: {type(exc).__name__}")
                return
            if not isinstance(pid, int) or pid <= 0:
                self._set(lid, "failed", "radio returned no packet id")
                return
            with self._lock:
                self._by_packet[pid] = lid
            self._set(lid, "sent", None, packet_id=pid)

        self._run(work)
        return lid

    def _set(self, lid: int, state: str, detail: Optional[str], **extra) -> None:
        if not self.store.is_open:
            return
        self.store.update(lid, state=state, detail=detail, **extra)
        self._emit("updated", self.store.get(lid))

    # ------------------------------------------------------------------ receive
    def on_routing(self, r: RoutingPacket) -> None:
        with self._lock:
            lid = self._by_packet.get(r.request_id)
        if lid is None or not self.store.is_open:
            return
        row = self.store.get(lid)
        if row is None or row["state"] in FINAL:
            return
        direct = row["peer"] != BROADCAST_PEER
        if r.error_reason != "NONE":
            self._set(lid, "failed", r.error_reason)
        elif direct and r.from_num == parse_node_id(row["peer"]):
            self._set(lid, "delivered", "ACK from destination")
        elif r.from_num == self.local_num or not direct:
            self._set(lid, "relayed", "heard rebroadcast (implicit ACK)")
        else:
            self._set(lid, "relayed", f"ACK from {node_id(r.from_num)}")
        if self.store.get(lid)["state"] in FINAL:
            with self._lock:
                self._by_packet.pop(r.request_id, None)

    def on_text(self, t: TextPacket) -> Optional[int]:
        if self.local_num is not None and t.from_num == self.local_num:
            return None
        if self.local_num is not None and t.is_direct and t.to_num != self.local_num:
            return None  # a DM for someone else that our radio forwarded
        if not self.store.is_open:
            self.unread += 1
            self._emit("unread", {"count": self.unread})  # no content while locked
            return None
        peer = node_id(t.from_num) if t.is_direct else BROADCAST_PEER
        lid = self.store.add(direction="in", channel=t.channel, peer=peer, from_id=node_id(t.from_num), text=t.text,
                             ts=int(self.clock()), packet_id=t.packet_id, state="received",
                             detail="via MQTT" if t.via_mqtt else None, via_mqtt=int(t.via_mqtt))
        self._emit("added", self.store.get(lid))
        return lid

    def check_timeouts(self) -> None:
        if not self.store.is_open:
            return
        now = self.clock()
        for row in self.store.pending():
            if row["state"] in ("sent", "queued") and now - row["ts"] > ACK_TIMEOUT_S:
                self._set(row["local_id"], "no-ack", f"no ACK within {ACK_TIMEOUT_S} s")

    # ------------------------------------------------------------------ history
    def conversation(self, channel: int, peer: str) -> list[dict]:
        if not self.gate.unlocked:
            raise MessageError("sign in to view messages")
        if not self.store.is_open:
            self.unlock()
        return self.store.conversation(channel, peer)
