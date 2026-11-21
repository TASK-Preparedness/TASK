# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GMRS data TX/RX through a radio-integration driver. Independent from the amateur controller:
own config (gmrs.toml), own attestation, own audit stream (audit-gmrs.jsonl), own Send buttons."""

import time

from task_comms.audit import payload_digest
from task_comms.feeds import Entity
from task_comms.txpolicy import GmrsEquipment, TxRequest


def equipment_from(driver, profile) -> GmrsEquipment:
    """Policy facts: both the driver AND the operator's profile (from the FCC grant) must agree."""
    c = driver.capabilities()
    return GmrsEquipment(model=c.model, fcc_id=c.fcc_id or getattr(profile, "fcc_id", ""),
                         handheld=c.handheld and bool(getattr(profile, "handheld", c.simulated)),
                         integral_antenna=c.integral_antenna and bool(getattr(profile, "integral_antenna", c.simulated)),
                         builtin_data=c.builtin_data,
                         software_tx_supported=c.can_send_location or c.can_send_text,
                         driver_verified=c.verified_on_hardware and bool(getattr(profile, "verified", False)),
                         simulated=c.simulated)


class GmrsTx:
    def __init__(self, policy, audit, driver_getter, config_getter, profile_getter, role_getter,
                 clock=time.monotonic, feed=None, on_receive=None):
        self.policy, self.audit = policy, audit
        self.driver, self.config, self.profile, self.role = driver_getter, config_getter, profile_getter, role_getter
        self.clock, self.feed, self.on_receive = clock, feed, on_receive
        self.received = []

    def status(self):
        d = self.driver()
        if d is None:
            return "No GMRS radio driver selected"
        c = d.capabilities()
        if c.simulated:
            return "SIMULATION — nothing is transmitted"
        if not c.verified_on_hardware:
            return "Driver UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST; transmit blocked"
        return f"{c.model} connected" if d.connected else f"{c.model} not connected"

    def send(self, kind, *, recipient="", text="", lat=None, lon=None, confirmed=(), is_auto_reply=False):
        d = self.driver()
        cfg = self.config()
        eq = equipment_from(d, self.profile()) if d is not None else None
        caps = d.capabilities() if d is not None else None
        req = TxRequest(service="gmrs", kind=kind, user_initiated=not is_auto_reply, role=self.role(), text=text,
                        addressee=recipient, recipient_service="gmrs", transport="radio-integrated",
                        channel_mhz=d.current_channel_mhz() if d is not None and d.connected else None,
                        duration_s=caps.max_burst_s if caps else None, confirmed=tuple(confirmed),
                        is_auto_reply=is_auto_reply)
        dec = self.policy.evaluate_gmrs(req, cfg, eq)
        if caps is not None:
            need = {"location": caps.can_send_location, "text": caps.can_send_text,
                    "location-request": caps.can_request_location}.get(kind, False)
            if not need:
                dec.allowed = False
                dec.reasons.append(f"driver-no-tx: this radio cannot send '{kind}'")
            if kind == "text" and len(text) > caps.max_text_chars:
                dec.allowed = False
                dec.reasons.append("bad-content: longer than the radio's text limit")
        if d is None or not d.connected:
            dec.allowed = False
            dec.reasons.append("disconnected: GMRS radio not connected")
        digest = payload_digest(f"{kind}|{recipient}|{text}|{lat}|{lon}".encode())
        base = dict(service="gmrs", kind=kind, decision=dec.code, reasons=[r.split(":")[0] for r in dec.reasons],
                    simulated=bool(caps and caps.simulated), **digest)
        if not dec.allowed:
            self.audit.append(action="refused", **base)
            return False, dec
        try:
            dur = d.request_transmit(kind, recipient=recipient, text=text, lat=lat, lon=lon)
        except OSError as exc:
            self.audit.append(action="failed", **base)
            dec.allowed = False
            dec.reasons.append(f"radio-error: {exc}")
            return False, dec
        self.policy.record_sent(req)
        self.audit.append(action="requested-from-radio", burst_s=dur, **base)
        return True, dec

    def voice_id_done(self):
        self.policy.voice_id_done()
        self.audit.append(service="gmrs", action="voice-id-confirmed")

    def handle_receive(self, pkt):
        self.received.append(pkt)
        if pkt.kind == "location" and pkt.lat is not None and self.feed is not None:
            self.feed.upsert(Entity(id=f"gmrs:{pkt.sender}", layer="gmrs", label=pkt.sender, lat=pkt.lat,
                                    lon=pkt.lon, observed_ts=int(pkt.ts), source="GMRS radio", kind="observed"))
        if self.on_receive:
            self.on_receive(pkt)
