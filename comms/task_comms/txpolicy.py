# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Transmit-policy engine for task-aprs: two independent services, AMATEUR and GMRS.

The engine decides; it never transmits. Every evaluation (allowed or refused) is meant to be
written to the audit log by the caller. The two services share no configuration: an amateur
profile can never authorise a GMRS transmission or vice versa.

AMATEUR (47 CFR Part 97, APRS via the existing Direwolf):
  operator session, TX enabled in settings, user-configured callsign (format check only),
  typed licence attestation, a radio profile the operator marked verified, Direwolf PTT
  configured, explicit user action, local-UI origin (no relay), APRS 1.0.1 text limits,
  duplicate guard (60 s, second confirmation), one frame in flight per channel,
  periodic beacon off by default and >= 10 min.

GMRS (47 CFR Part 95 Subpart E, eCFR text as of 2026-10-08):
  * §95.1731(d) / §95.1787(a)(1): content only location, location request, or brief text to a
    specific GMRS/FRS unit; hand-held portable units only.
  * §95.1787(a)(2): <= 1 s per transmission; (a)(3): not more than once per 30 s
    (automatic reply to a location request is the only exception).
  * §95.1787(a)(4): non-removable integral antenna; (a)(5) and §95.1773(c): never the 467 MHz
    main channels; data only on 462 MHz main + 462/467 MHz interstitial channels.
  * §95.1733(a)(9): no messages to amateur stations; (a)(8): nothing conveyed by a wireline
    control link (no relay); (a)(3): no coded messages.
  * §§95.335/95.337/95.339: certified, unmodified equipment and no external modem/accessory:
    the RADIO's own integrated data function must generate the transmission. The Direwolf
    path is always refused for GMRS (reason gmrs-external-modem).
  * §95.1705: individual GMRS licence (attested, typed GMRS call sign).
  * §95.1751: station ID by voice or Morse -> voice-ID reminder every 15 min and after a series.
  Automatic GMRS TX is off by default; every GMRS transmission needs an explicit user action.
"""

import re
import time
from dataclasses import dataclass, field

# 47 CFR §95.1763(a)/(b) channel table, MHz. 467 main (channels 15R-22R inputs) are NOT data channels.
GMRS_462_MAIN = (462.5500, 462.5750, 462.6000, 462.6250, 462.6500, 462.6750, 462.7000, 462.7250)
GMRS_462_INTERSTITIAL = (462.5625, 462.5875, 462.6125, 462.6375, 462.6625, 462.6875, 462.7125)
GMRS_467_INTERSTITIAL = (467.5625, 467.5875, 467.6125, 467.6375, 467.6625, 467.6875, 467.7125)
GMRS_467_MAIN = (467.5500, 467.5750, 467.6000, 467.6250, 467.6500, 467.6750, 467.7000, 467.7250)
GMRS_DATA_CHANNELS = GMRS_462_MAIN + GMRS_462_INTERSTITIAL + GMRS_467_INTERSTITIAL

AMATEUR_CALL = re.compile(r"^(?=[A-Z0-9]{3,6}$)[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$")
GMRS_CALL = re.compile(r"^(?:[A-Z]{4}[0-9]{3}|[A-Z]{3}[0-9]{4})$")  # e.g. WRxx123, legacy KAE1234

DUPLICATE_WINDOW_S = 60
BEACON_MIN_INTERVAL_S = 600
GMRS_MAX_DURATION_S = 1.0
GMRS_MIN_SPACING_S = 30.0
GMRS_VOICE_ID_INTERVAL_S = 15 * 60
RETRY_SPACING_S = (30, 60, 120)
RETRY_DEFAULT, RETRY_MAX = 3, 5


def valid_amateur_callsign(text: str) -> bool:
    call, _, ssid = (text or "").upper().partition("-")
    if ssid and not (ssid.isdigit() and 0 <= int(ssid) <= 15):
        return False
    return bool(AMATEUR_CALL.match(call))


def valid_gmrs_callsign(text: str) -> bool:
    return bool(GMRS_CALL.match((text or "").upper()))


def is_gmrs_data_channel(mhz) -> bool:
    try:
        f = float(mhz)
    except (TypeError, ValueError):
        return False
    return any(abs(f - c) < 0.00005 for c in GMRS_DATA_CHANNELS)


@dataclass
class Decision:
    allowed: bool
    reasons: list = field(default_factory=list)
    needs_confirmation: list = field(default_factory=list)
    reminders: list = field(default_factory=list)

    @property
    def code(self):
        return "allowed" if self.allowed else (self.reasons[0].split(":")[0] if self.reasons else "refused")


@dataclass
class AmateurConfig:
    tx_enabled: bool = False
    callsign: str = ""
    attestation: str = ""          # typed text, e.g. "I hold amateur licence N0CALL"
    attestation_date: str = ""


@dataclass
class AmateurRadio:
    id: str
    verified: bool = False         # operator marked it verified after acceptance test A5
    ptt_configured: bool = False   # Direwolf config shows a PTT for the channel
    channel: int = 0


@dataclass
class GmrsConfig:
    tx_enabled: bool = False       # separate switch, off by default
    callsign: str = ""
    attestation: str = ""
    attestation_date: str = ""
    auto_reply_location: bool = False  # §95.1787(a)(3) exception; off by default


@dataclass
class GmrsEquipment:
    """Facts about a certified GMRS hand-held with built-in data (from its driver + operator)."""
    model: str
    fcc_id: str = ""
    handheld: bool = False
    integral_antenna: bool = False
    builtin_data: bool = False
    software_tx_supported: bool = False   # driver can ask the RADIO to send its own data packet
    driver_verified: bool = False         # verified on real hardware (bench), never assumed
    simulated: bool = False


@dataclass
class TxRequest:
    service: str                   # "amateur" | "gmrs"
    kind: str                      # amateur: message|position|ack|beacon ; gmrs: location|location-request|text
    user_initiated: bool
    origin: str = "local-ui"       # anything else = relay -> refused
    role: str = None               # Core session role of the module's own session
    text: str = ""
    addressee: str = ""
    recipient_service: str = ""    # gmrs: "gmrs"|"frs"; refuse "amateur"
    transport: str = ""            # amateur: "direwolf-agw"|"direwolf-kiss"; gmrs: "radio-integrated"
    channel_mhz: float = None
    duration_s: float = None       # gmrs: radio/driver-reported duration of the data burst
    beacon_interval_s: float = None
    confirmed: tuple = ()          # confirmations the user gave for needs_confirmation items
    is_auto_reply: bool = False


class TxPolicy:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.recent = []           # (t, service, addressee, text)
        self.in_flight = {}        # channel -> request id
        self.last_gmrs_tx = None
        self.last_voice_id = None
        self.gmrs_series = 0

    # ------------------------------------------------------------------ shared
    def _common(self, req: TxRequest, d: Decision):
        if req.origin != "local-ui":
            d.reasons.append("relay-refused: text must be typed in this app (no mesh/LAN/internet relay)")
        if not req.user_initiated and not (req.is_auto_reply and req.service == "gmrs"):
            d.reasons.append("not-user-initiated: every transmission needs an explicit action")
        if req.role not in ("operator", "administrator"):
            d.reasons.append("no-session: sign in with an operator account")

    def _duplicate(self, req, d):
        now = self.clock()
        self.recent = [r for r in self.recent if now - r[0] < DUPLICATE_WINDOW_S]
        if req.text and any(r[1:] == (req.service, req.addressee.upper(), req.text) for r in self.recent):
            if "duplicate" not in req.confirmed:
                d.needs_confirmation.append("duplicate: same addressee and text within 60 s")

    # ------------------------------------------------------------------ amateur
    def evaluate_amateur(self, req: TxRequest, cfg: AmateurConfig, radio: AmateurRadio) -> Decision:
        d = Decision(False)
        if req.service != "amateur":
            d.reasons.append("wrong-service")
            return d
        self._common(req, d)
        if not cfg.tx_enabled:
            d.reasons.append("tx-disabled: amateur transmit is off in Settings")
        if not valid_amateur_callsign(cfg.callsign):
            d.reasons.append("no-callsign: configure your own amateur callsign (never defaulted)")
        if not cfg.attestation.strip() or not cfg.attestation_date:
            d.reasons.append("no-attestation: type the licence attestation")
        if radio is None or not radio.verified:
            d.reasons.append("radio-unverified: mark the radio profile verified after acceptance test A5")
        if radio is not None and not radio.ptt_configured:
            d.reasons.append("no-ptt: Direwolf has no PTT for this channel, it cannot key a radio")
        if req.transport not in ("direwolf-agw", "direwolf-kiss"):
            d.reasons.append("bad-transport")
        if radio is not None and self.in_flight.get(radio.channel):
            d.reasons.append("busy: a frame is already in flight on this channel")
        if req.kind in ("message", "ack"):
            from task_comms import aprs
            try:
                aprs.check_text(req.addressee.strip().upper(), aprs.ADDRESSEE_MAX, "addressee")
                if req.kind == "message":
                    aprs.check_text(req.text, aprs.MSG_MAX, "message text")
            except ValueError as exc:
                d.reasons.append(f"bad-content: {exc}")
        elif req.kind == "beacon":
            if req.beacon_interval_s is None or req.beacon_interval_s < BEACON_MIN_INTERVAL_S:
                d.reasons.append("beacon-interval: periodic beacons need >= 10 min")
        elif req.kind != "position":
            d.reasons.append("bad-kind")
        self._duplicate(req, d)
        d.allowed = not d.reasons and not d.needs_confirmation
        return d

    # ------------------------------------------------------------------ gmrs
    def evaluate_gmrs(self, req: TxRequest, cfg: GmrsConfig, eq: GmrsEquipment) -> Decision:
        d = Decision(False)
        if req.service != "gmrs":
            d.reasons.append("wrong-service")
            return d
        self._common(req, d)
        if req.is_auto_reply and not cfg.auto_reply_location:
            d.reasons.append("auto-reply-off: automatic location replies are disabled")
        if req.is_auto_reply and req.kind != "location":
            d.reasons.append("auto-reply-kind: only a location reply may be automatic (§95.1787(a)(3))")
        if not cfg.tx_enabled:
            d.reasons.append("tx-disabled: GMRS data transmit is off in Settings")
        if not valid_gmrs_callsign(cfg.callsign):
            d.reasons.append("no-callsign: configure your GMRS call sign (§95.1705; never defaulted)")
        if not cfg.attestation.strip() or not cfg.attestation_date:
            d.reasons.append("no-attestation: type the GMRS licence attestation")
        if req.transport != "radio-integrated":
            d.reasons.append("gmrs-external-modem: GMRS data must be generated by the certified radio itself "
                             "(§95.339, §95.337); Direwolf/sound-card modems are refused")
        if eq is None:
            d.reasons.append("no-equipment: no GMRS radio with integrated data connected")
        else:
            if not eq.handheld:
                d.reasons.append("not-handheld: §95.1731(d) allows data only from hand-held portable units")
            if not eq.integral_antenna:
                d.reasons.append("antenna: §95.1787(a)(4) requires a non-removable integral antenna")
            if not eq.builtin_data:
                d.reasons.append("no-builtin-data: radio has no certified data function")
            if not eq.software_tx_supported:
                d.reasons.append("driver-no-tx: this radio's interface cannot request a data transmission")
            if not eq.driver_verified and not eq.simulated:
                d.reasons.append("driver-unverified: UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST")
        if not is_gmrs_data_channel(req.channel_mhz):
            d.reasons.append("channel: data only on 462 MHz main or 462/467 MHz interstitial channels "
                             "(§95.1773(c)); never 467 MHz main")
        if req.kind == "text":
            if not req.addressee.strip():
                d.reasons.append("no-recipient: GMRS text must go to a specific unit (§95.1731(d))")
            if not req.text or len(req.text) > 64 or any(not 0x20 <= ord(c) <= 0x7E for c in req.text):
                d.reasons.append("bad-content: brief plain text only (no codes/encryption, §95.1733(a)(3))")
        elif req.kind not in ("location", "location-request"):
            d.reasons.append("bad-kind: only location, location request or brief text (§95.1731(d))")
        if req.recipient_service not in ("gmrs", "frs", ""):
            d.reasons.append("amateur-recipient: no messages to amateur stations (§95.1733(a)(9))")
        if req.duration_s is None or req.duration_s > GMRS_MAX_DURATION_S:
            d.reasons.append("duration: data bursts must not exceed 1 s (§95.1787(a)(2))")
        now = self.clock()
        if self.last_gmrs_tx is not None and now - self.last_gmrs_tx < GMRS_MIN_SPACING_S and not req.is_auto_reply:
            d.reasons.append(f"spacing: wait {GMRS_MIN_SPACING_S - (now - self.last_gmrs_tx):.0f} s "
                             "(one data transmission per 30 s, §95.1787(a)(3))")
        if self.last_voice_id is None or now - self.last_voice_id >= GMRS_VOICE_ID_INTERVAL_S:
            d.reminders.append("voice-id: identify by voice (or Morse) with your GMRS call sign (§95.1751)")
        self._duplicate(req, d)
        d.allowed = not d.reasons and not d.needs_confirmation
        return d

    # ------------------------------------------------------------------ bookkeeping
    def record_sent(self, req: TxRequest, channel=None, request_id=None):
        now = self.clock()
        self.recent.append((now, req.service, req.addressee.upper(), req.text))
        if req.service == "gmrs":
            self.last_gmrs_tx = now
            self.gmrs_series += 1
        elif channel is not None:
            self.in_flight[channel] = request_id or True

    def frame_done(self, channel):
        self.in_flight.pop(channel, None)

    def voice_id_done(self):
        self.last_voice_id = self.clock()
        self.gmrs_series = 0


def retry_schedule(count: int = RETRY_DEFAULT):
    """User-chosen retries (default 3, max 5): seconds after the first send."""
    if not 0 <= count <= RETRY_MAX:
        raise ValueError(f"retries must be 0..{RETRY_MAX}")
    out, t = [], 0
    for i in range(count):
        t += RETRY_SPACING_S[min(i, len(RETRY_SPACING_S) - 1)]
        out.append(t)
    return out
