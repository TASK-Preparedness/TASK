# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Amateur APRS transmit controller (through an existing Direwolf only).

Every frame is the result of one explicit user action (Send / Send position now / Send ack), is checked by
task_comms.txpolicy and is written to the hash-chained audit log (allowed or refused; payload digest only).
Retries are chosen by the user at send time. Nothing is ever sent on start-up, automatically or for a relay.

Delivery states (no state ever claims "on air"):
  submitted        frame accepted by Direwolf's AGW/KISS socket
  queue-progress   AGW 'y' count for the channel fell: queue progress inside Direwolf only — NOT proof of RF
  heard-digipeated our own frame came back with a used digipeater — evidence that it went out over RF
  acked / rejected the addressee answered
  no-ack           all user-chosen attempts done without an answer
  failed           socket closed, Direwolf gone or queue never drained within 30 s (never retried silently)
  cancelled        the user cancelled the retries
  complete         a position/ack frame was handed over (no answer is expected for those)
"""

import itertools
import time
from dataclasses import dataclass, field

from task_comms import aprs as codec
from task_comms.audit import payload_digest
from task_comms.txpolicy import TxRequest, retry_schedule

TOCALL = "APZTSK"            # APZxxx = experimental software tocall (APRS 1.0.1 ch. 4)
QUEUE_DRAIN_TIMEOUT_S = 30.0
FINAL_WAIT_S = 120.0
MAX_PATH_HOPS = 2
TERMINAL = ("complete", "acked", "rejected", "no-ack", "failed", "cancelled")


def parse_path(text: str):
    items = [t.strip().upper() for t in text.split(",") if t.strip()]
    if len(items) > MAX_PATH_HOPS:
        raise ValueError(f"at most {MAX_PATH_HOPS} digipeater hops")
    return [codec.parse_callsign(t) for t in items]


@dataclass
class Outgoing:
    local_id: int
    kind: str                 # message | position | ack
    addressee: str
    msg_id: str
    frame: bytes
    channel: int
    schedule: list            # seconds after first send
    text: str = ""            # kept in memory only (never audited/logged)
    state: str = "submitted"
    attempts: int = 0
    first_ts: float = None
    last_ts: float = None
    queue_wait_since: float = None
    history: list = field(default_factory=list)   # (ts, state, note)

    @property
    def done(self):
        return self.state in TERMINAL


class AmateurTx:
    def __init__(self, policy, audit, transport_getter, config_getter, radio_getter, role_getter,
                 clock=time.monotonic, on_change=None):
        self.policy, self.audit = policy, audit
        self.transport = transport_getter
        self.config, self.radio, self.role = config_getter, radio_getter, role_getter
        self.clock, self.on_change = clock, on_change or (lambda o: None)
        self.items = {}
        self._ids = itertools.count(1)
        self._msg_seq = itertools.count(1)

    # ---------------------------------------------------------------- helpers
    def _msg_id(self):
        return str(next(self._msg_seq) % 100000 or 1)

    def _set(self, o: Outgoing, state, note=""):
        o.state = state
        o.history.append((self.clock(), state, note))
        self.on_change(o)

    def queued(self):
        """True while any of our frames is still waiting in Direwolf's queue (QUEUED indicator)."""
        return any(o.queue_wait_since is not None and not o.done for o in self.items.values())

    def _evaluate(self, kind, addressee="", text="", confirmed=(), transport_name=None):
        cfg, radio = self.config(), self.radio()
        t = self.transport()
        req = TxRequest(service="amateur", kind=kind, user_initiated=True, role=self.role(), text=text,
                        addressee=addressee, transport=transport_name or (t.name if t else ""),
                        confirmed=tuple(confirmed))
        d = self.policy.evaluate_amateur(req, cfg, radio)
        if t is None or not t.connected:
            d.allowed = False
            d.reasons.append("disconnected: Direwolf is not connected")
        return req, d, cfg, radio, t

    def _audit(self, action, d, kind, info: str, radio, extra=None):
        rec = dict(service="amateur", action=action, kind=kind, decision=d.code,
                   reasons=[r.split(":")[0] for r in d.reasons],
                   needs_confirmation=[r.split(":")[0] for r in d.needs_confirmation],
                   radio=getattr(radio, "id", None), **payload_digest(info.encode("latin-1", "replace")))
        rec.update(extra or {})
        self.audit.append(**rec)

    def preview(self, kind, addressee="", text="", lat=None, lon=None, comment="", path="WIDE1-1,WIDE2-1"):
        """Exact frame that Send would hand to Direwolf (no side effects)."""
        cfg = self.config()
        info = self._info(kind, addressee, text, lat, lon, comment, msg_id="1")
        src = codec.parse_callsign(cfg.callsign) if cfg.callsign else codec.Address("NOCALL", 0)
        hdr = f"{src}>{TOCALL}" + ("," + ",".join(str(a) for a in parse_path(path)) if path else "")
        return f"{hdr}:{info}", len(info)

    def _info(self, kind, addressee, text, lat, lon, comment, msg_id):
        if kind == "message":
            return codec.message_info(addressee, text, msg_id)
        if kind == "ack":
            return codec.ack_info(addressee, msg_id)
        if kind == "position":
            return codec.position_info(lat, lon, comment=comment)
        raise ValueError("bad kind")

    # ---------------------------------------------------------------- user actions
    def send(self, kind, *, addressee="", text="", lat=None, lon=None, comment="", ack_id=None,
             retries=3, path="WIDE1-1,WIDE2-1", confirmed=()):
        """One explicit user action. Returns (Outgoing|None, Decision)."""
        if kind == "position" and (lat is None or lon is None):
            raise ValueError("position needs a fix or a typed position")
        sched = retry_schedule(retries if kind == "message" else 0)
        req, d, cfg, radio, t = self._evaluate(kind, addressee, text, confirmed)
        msg_id = ack_id if kind == "ack" else (self._msg_id() if kind == "message" else "")
        try:
            info = self._info(kind, addressee, text, lat, lon, comment, msg_id)
            hops = parse_path(path)
        except ValueError as exc:
            d.allowed = False
            d.reasons.append(f"bad-content: {exc}")
            info, hops = "", []
        if not d.allowed:
            self._audit("refused", d, kind, info, radio)
            return None, d
        frame = codec.encode_ax25(codec.parse_callsign(cfg.callsign), codec.Address(TOCALL, 0), hops,
                                  info.encode("ascii"))
        o = Outgoing(next(self._ids), kind, addressee.strip().upper(), msg_id, frame, radio.channel, sched, text)
        self.items[o.local_id] = o
        self._audit("allowed", d, kind, info, radio, {"local_id": o.local_id, "retries": len(sched)})
        self._transmit(o, req, t)
        return o, d

    def cancel(self, local_id):
        o = self.items.get(local_id)
        if o and not o.done:
            self.policy.frame_done(o.channel)
            o.queue_wait_since = None
            self._set(o, "cancelled", "retries cancelled by the user")
            self.audit.append(service="amateur", action="cancelled", local_id=local_id)

    # ---------------------------------------------------------------- transmission
    def _transmit(self, o: Outgoing, req, t):
        now = self.clock()
        try:
            t.send_raw(o.channel, o.frame)
        except (OSError, ValueError) as exc:
            self._set(o, "failed", f"Direwolf write failed: {exc}")
            self.audit.append(service="amateur", action="failed", local_id=o.local_id, reason="write")
            return
        o.attempts += 1
        o.first_ts = o.first_ts or now
        o.last_ts = now
        self.policy.record_sent(req, channel=o.channel, request_id=o.local_id)
        if getattr(t, "has_queue_feedback", False):
            o.queue_wait_since = now
            self._set(o, "submitted", f"attempt {o.attempts}: in Direwolf's queue (QUEUED)")
        else:
            self.policy.frame_done(o.channel)
            self._set(o, "submitted", f"attempt {o.attempts}: written to KISS (no queue feedback)")

    def tick(self):
        """Poll queue progress and run user-chosen retries. Call about once per second."""
        now = self.clock()
        t = self.transport()
        for o in list(self.items.values()):
            if o.done:
                continue
            if o.queue_wait_since is not None:
                if t is None or not t.connected:
                    self._fail(o, "Direwolf connection lost")
                    continue
                try:
                    n = t.outstanding(o.channel)
                except OSError as exc:
                    self._fail(o, f"queue query failed: {exc}")
                    continue
                if n == 0:
                    o.queue_wait_since = None
                    self.policy.frame_done(o.channel)
                    self._set(o, "queue-progress", "left Direwolf's queue — queue progress only, NOT proof of RF")
                elif now - o.queue_wait_since > QUEUE_DRAIN_TIMEOUT_S:
                    self._fail(o, "Direwolf's queue did not drain within 30 s")
                continue
            if o.kind != "message":
                self._set(o, "complete", "single frame handed to Direwolf; no acknowledgement expected")
                continue
            if o.attempts <= len(o.schedule):
                if o.first_ts + o.schedule[o.attempts - 1] > now:
                    continue
                req, d, cfg, radio, tt = self._evaluate("message", o.addressee, o.text, ("duplicate",))
                if d.allowed:
                    self.audit.append(service="amateur", action="retry", local_id=o.local_id, attempt=o.attempts + 1)
                    self._transmit(o, req, tt)
                elif any(r.startswith("busy") for r in d.reasons):
                    continue
                else:
                    self._fail(o, "retry refused: " + ", ".join(r.split(":")[0] for r in d.reasons))
            elif now - o.last_ts >= FINAL_WAIT_S:
                self._set(o, "no-ack", f"no acknowledgement after {o.attempts} attempt(s)")

    def _fail(self, o, why):
        o.queue_wait_since = None
        self.policy.frame_done(o.channel)
        self._set(o, "failed", why)
        self.audit.append(service="amateur", action="failed", local_id=o.local_id, reason=why[:60])

    # ---------------------------------------------------------------- reception hooks
    def on_packet(self, frame, packet):
        """Called for every decoded RF frame (not for APRS-IS third-party content)."""
        cfg = self.config()
        if not cfg.callsign:
            return
        mine = cfg.callsign.strip().upper()
        if str(frame.source).rstrip("*") == mine and any(a.repeated for a in frame.path):
            for o in self.items.values():
                if o.state not in ("failed", "cancelled", "heard-digipeated", "acked", "rejected") \
                        and o.frame.endswith(frame.info):
                    note = f"heard via {','.join(str(a) for a in frame.path)} (evidence of RF)"
                    if o.state == "complete":
                        o.history.append((self.clock(), "heard-digipeated", note))
                        self.on_change(o)
                    else:
                        self._set(o, "heard-digipeated", note)
        ack = codec.parse_ack(packet)
        if ack and packet.addressee.upper() == mine:
            kind, mid = ack
            for o in self.items.values():
                if o.kind == "message" and not o.done and o.msg_id == mid and o.addressee == packet.source.upper():
                    o.queue_wait_since = None
                    self.policy.frame_done(o.channel)
                    self._set(o, "acked" if kind == "ack" else "rejected", f"{kind} from {packet.source}")
