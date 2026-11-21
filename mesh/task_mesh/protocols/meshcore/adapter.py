# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""MeshCore adapter: one companion radio over USB serial, via meshcore_py's async API in a private event loop.

Read-only on connect: APP_START (session start), DEVICE_QUERY, get_contacts, get_bat, and draining the
device's offline queue (get_msg). Messages drained during that initial sync are origin=SYNC (not counted as
new). Afterwards MESSAGES_WAITING pushes are drained as LIVE. Sending only via send_text() (explicit user
action, gated by the hub). No set_*/reboot/advert/key/CLI/raw commands are ever called (COMMANDS_USED).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable, Optional

from task_mesh.hub.model import LIVE, SYNC, HubMessage, HubNode, dedupe_key

log = logging.getLogger(__name__)
ROLES = {1: "chat", 2: "repeater", 3: "room", 4: "sensor"}
COMMANDS_USED = frozenset({"send_appstart", "send_device_query", "get_contacts", "get_bat", "get_msg",
                           "send_msg", "send_chan_msg"})
BACKOFF = (2, 5, 10, 30, 60)


async def default_connect(path: str):
    from task_mesh.protocols.meshcore.compat import import_meshcore
    mc = import_meshcore()
    return await mc.MeshCore.create_serial(path, 115200, auto_reconnect=False)


def message_key(kind: str, who: str, sender_ts, text: str) -> str:
    return dedupe_key("meshcore", kind, who, sender_ts, text)


class MeshCoreAdapter:
    protocol = "meshcore"

    def __init__(self, path: str, key: str, sink, connect: Optional[Callable] = None, backoff=BACKOFF,
                 clock: Callable[[], float] = time.time, sync_limit: int = 200) -> None:
        self.path, self.key, self.sink = path, key, sink
        self._connect = connect or default_connect
        self.backoff = backoff
        self.clock = clock
        self.sync_limit = sync_limit
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.mc = None
        self.syncing = False
        self.connected = threading.Event()
        self._stop: Optional[asyncio.Event] = None
        self._thread: Optional[threading.Thread] = None
        self.counters = {"live": 0, "sync": 0, "sessions": 0}

    # --- lifecycle --------------------------------------------------------------------------------
    def start(self) -> None:
        ready = threading.Event()

        def run() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._stop = asyncio.Event()
            ready.set()
            try:
                self.loop.run_until_complete(self._main())
            finally:
                self.loop.close()

        self._thread = threading.Thread(target=run, name=f"meshcore-{self.key}", daemon=True)
        self._thread.start()
        ready.wait(5)

    def stop(self, timeout: float = 10) -> None:
        if self.loop is not None and self._stop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout)

    def _status(self, **f) -> None:
        try:
            self.sink.on_adapter_status(self.key, **f)
        except Exception:  # noqa: BLE001
            log.exception("status sink failed")

    async def _main(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._session()
                attempt = 0
            except Exception as exc:  # noqa: BLE001 - never crash the service
                self._status(state="error", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
                log.warning("meshcore session ended (%s)", type(exc).__name__, extra={"event": "meshcore.session_error"})
            self.connected.clear()
            if self._stop.is_set():
                break
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            self._status(state="backoff", detail=f"reconnecting in {delay} s")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _session(self) -> None:
        from task_mesh.protocols.meshcore.compat import import_meshcore
        EventType = import_meshcore().EventType
        self._status(state="connecting", detail="")
        mc = await self._connect(self.path)
        if mc is None:
            raise ConnectionError("no MeshCore companion answered (is this a serial companion firmware?)")
        self.mc = mc
        self.counters["sessions"] += 1
        lost = asyncio.Event()
        subs = [mc.subscribe(EventType.DISCONNECTED, lambda e: lost.set()),
                mc.subscribe(EventType.CONTACT_MSG_RECV, lambda e: self._on_msg("dm", e.payload)),
                mc.subscribe(EventType.CHANNEL_MSG_RECV, lambda e: self._on_msg("channel", e.payload)),
                mc.subscribe(EventType.NEW_CONTACT, lambda e: self._on_contact(e.payload)),
                mc.subscribe(EventType.ADVERTISEMENT, lambda e: self._on_advert(e.payload))]
        try:
            info = dict(getattr(mc, "self_info", None) or {})
            dev = await mc.commands.send_device_query()
            d = dict(dev.payload) if dev is not None and dev.type == EventType.DEVICE_INFO else {}
            d.pop("ble_pin", None)                       # secret: dropped immediately, never stored/logged
            bat = await mc.commands.get_bat()
            level = bat.payload.get("level") if bat is not None and bat.type == EventType.BATTERY else None
            self._status(state="connected", model=str(d.get("model", ""))[:40],
                         firmware=" ".join(str(x) for x in (d.get("ver", ""), d.get("fw_build", "")) if x)[:40],
                         name=str(info.get("name", ""))[:32], battery=level if isinstance(level, int) else None,
                         detail="", extra={"radio_freq_mhz": info.get("radio_freq"), "radio_bw_khz": info.get("radio_bw"),
                                           "radio_sf": info.get("radio_sf"), "fw_ver": d.get("fw ver"),
                                           "max_channels": d.get("max_channels")})
            res = await mc.commands.get_contacts()
            if res is not None and res.type == EventType.CONTACTS:
                for c in (res.payload or {}).values():
                    self._on_contact(c)
            self.syncing = True
            await self._drain(EventType)
            self.syncing = False
            self.connected.set()

            async def on_waiting(_e):
                await self._drain(EventType)
            subs.append(mc.subscribe(EventType.MESSAGES_WAITING, on_waiting))
            stop_task = asyncio.ensure_future(self._stop.wait())
            lost_task = asyncio.ensure_future(lost.wait())
            await asyncio.wait({stop_task, lost_task}, return_when=asyncio.FIRST_COMPLETED)
            for t in (stop_task, lost_task):
                t.cancel()
            if lost.is_set() and not self._stop.is_set():
                raise ConnectionError("radio disconnected")
        finally:
            self.syncing = False
            for s in subs:
                try:
                    mc.unsubscribe(s)
                except Exception:  # noqa: BLE001
                    pass
            try:
                await mc.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.mc = None

    async def _drain(self, EventType) -> None:
        for _ in range(self.sync_limit):
            r = await self.mc.commands.get_msg()
            if r is None or r.type in (EventType.NO_MORE_MSGS, EventType.ERROR):
                return
        await asyncio.sleep(0)

    # --- normalisation (event loop thread) ---------------------------------------------------------
    def _name_for_prefix(self, prefix: str) -> str:
        for k, c in (getattr(self.mc, "contacts", None) or {}).items():
            if isinstance(k, str) and k.startswith(prefix):
                return str(c.get("adv_name") or "")[:32]
        return ""

    def _on_msg(self, kind: str, p: dict) -> None:
        if not isinstance(p, dict) or not isinstance(p.get("text"), str):
            return
        origin = SYNC if self.syncing else LIVE
        self.counters["live" if origin == LIVE else "sync"] += 1
        text = p["text"].replace("\x00", "")[:1000]
        sts = p.get("sender_timestamp") if isinstance(p.get("sender_timestamp"), int) else None
        snr = p.get("SNR") if isinstance(p.get("SNR"), (int, float)) else None
        path_len = p.get("path_len")
        hops = path_len if isinstance(path_len, int) and 0 <= path_len < 64 else None
        if kind == "dm":
            prefix = str(p.get("pubkey_prefix") or "")[:12]
            if not prefix:
                return
            label = self._name_for_prefix(prefix) or prefix
            m = HubMessage(protocol="meshcore", device=self.key, key=message_key("dm", prefix, sts, text),
                           direction="in", kind="dm", conversation=f"dm:{prefix}", sender=prefix, sender_label=label,
                           text=text, ts=self.clock(), sender_ts=sts, origin=origin, snr=snr, hops=hops)
        else:
            idx = p.get("channel_idx")
            if not isinstance(idx, int):
                return
            name, sep, rest = text.partition(": ")
            claimed = name.strip()[:32] if sep and 0 < len(name.strip()) <= 32 else ""
            m = HubMessage(protocol="meshcore", device=self.key, key=message_key("ch", idx, sts, text),
                           direction="in", kind="channel", conversation=f"ch:{idx}", sender="",
                           sender_label=f"{claimed} (claimed)" if claimed else "unknown sender",
                           text=text, ts=self.clock(), sender_ts=sts, origin=origin, snr=snr, hops=hops)
        self.sink.on_message(m)

    def _on_contact(self, c: dict) -> None:
        if not isinstance(c, dict) or not isinstance(c.get("public_key"), str):
            return
        lat, lon = c.get("adv_lat"), c.get("adv_lon")
        ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and (lat, lon) != (0, 0) \
            and -90 <= lat <= 90 and -180 <= lon <= 180
        plen = c.get("out_path_len")
        self.sink.on_node(HubNode(protocol="meshcore", key=c["public_key"][:64], name=str(c.get("adv_name") or "")[:32],
                                  role=ROLES.get(c.get("type"), "unknown"),
                                  last_heard=float(c["last_advert"]) if isinstance(c.get("last_advert"), int) and c["last_advert"] > 0 else None,
                                  hops=plen if isinstance(plen, int) and plen >= 0 else None,
                                  lat=lat if ok else None, lon=lon if ok else None, device=self.key))

    def _on_advert(self, p: dict) -> None:
        if isinstance(p, dict) and isinstance(p.get("public_key"), str):
            self.sink.on_node(HubNode(protocol="meshcore", key=p["public_key"][:64], last_heard=self.clock(),
                                      device=self.key))

    # --- explicit user action --------------------------------------------------------------------------
    def send_text(self, conversation: str, text: str, timeout: float = 20) -> str:
        if self.loop is None or self.mc is None or not self.connected.is_set():
            raise ConnectionError("MeshCore radio not connected")
        fut = asyncio.run_coroutine_threadsafe(self._send(conversation, text), self.loop)
        return fut.result(timeout)

    async def _send(self, conversation: str, text: str) -> str:
        from task_mesh.protocols.meshcore.compat import import_meshcore
        EventType = import_meshcore().EventType
        if conversation.startswith("dm:"):
            prefix = conversation[3:]
            if len(prefix) != 12 or any(ch not in "0123456789abcdef" for ch in prefix):
                raise ValueError("bad MeshCore contact prefix")
            r = await self.mc.commands.send_msg(prefix, text)
            return "sent" if r is not None and r.type == EventType.MSG_SENT else "failed"
        if conversation.startswith("ch:"):
            r = await self.mc.commands.send_chan_msg(int(conversation[3:]), text)
            return "sent" if r is not None and r.type == EventType.OK else "failed"
        raise ValueError("bad conversation")
