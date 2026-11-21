# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Display rules: unknown is an em dash, never 0; calculated values are labelled (design report §1.4)."""

from __future__ import annotations

import time
from typing import Optional

from task_mesh.core.clock import plausible_epoch
from task_mesh.domain.models import NodeRecord, Source

DASH = "—"


def text(v: Optional[str]) -> str:
    return v if v else DASH


def local_time(epoch: int, now: int) -> str:
    t = time.localtime(epoch)
    if time.strftime("%Y-%m-%d", t) == time.strftime("%Y-%m-%d", time.localtime(now)):
        return time.strftime("%H:%M:%S", t)
    return time.strftime("%Y-%m-%d %H:%M", t)


def age_text(seconds: int) -> str:
    if seconds < 0:
        return "in the future (clock skew)"
    if seconds < 90:
        return f"{seconds} s ago"
    if seconds < 5400:
        return f"{round(seconds / 60)} min ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} d ago"


def last_heard(rec: NodeRecord, now: int) -> tuple[str, str]:
    """Return (display, tooltip). Radio clock preferred; this computer's receive time as fallback."""
    radio, local = rec.last_heard_radio, rec.last_rx_local
    if plausible_epoch(radio):
        tip = "Source: radio clock (node DB lastHeard / packet rxTime)."
        if plausible_epoch(now):
            tip += f"\nAge: {age_text(now - radio)} (calculated against this computer's clock)."
        if radio is not None and local is not None:
            tip += f"\nLast packet received here: {local_time(local, now)} (this computer's clock)."
        return local_time(radio, now), tip
    if plausible_epoch(local):
        tip = "Source: this computer's clock when the last packet arrived (radio time unavailable)."
        if radio is not None:
            tip += f"\nRadio reported an implausible time ({radio}); its clock may be unset."
        tip += f"\nAge: {age_text(now - local)} (calculated)."
        return local_time(local, now), tip
    if radio is not None:
        return DASH, f"Radio reported an implausible time ({radio}); its clock may be unset."
    return DASH, "Not heard yet."


def rssi(rec: NodeRecord) -> tuple[str, str]:
    if rec.rssi_last is None:
        return DASH, "No packet received from this node since launch (RSSI is per packet only)."
    return f"{rec.rssi_last} dBm", "Last packet, dBm (measured by the connected radio)."


def snr(rec: NodeRecord) -> tuple[str, str]:
    if rec.snr is None:
        return DASH, "Unknown."
    src = "last packet" if rec.snr_source is Source.PACKET else "radio node database"
    return f"{rec.snr:.2f} dB", f"Source: {src}."


def hops(rec: NodeRecord) -> tuple[str, str]:
    if rec.hops_away is None:
        return DASH, "Unknown."
    if rec.hops_source is Source.CALCULATED:
        return f"{rec.hops_away} calc", "Calculated by T.A.S.K. from the last packet (hopStart − hopLimit)."
    return str(rec.hops_away), "Source: radio node database (hopsAway)."


def battery(rec: NodeRecord) -> tuple[str, str]:
    v = rec.voltage
    vtxt = f"Voltage: {v:.2f} V" if v is not None else "Voltage: " + DASH
    if rec.battery_level is None:
        return DASH, vtxt
    if rec.battery_level > 100:
        return "Powered", f"Externally powered (raw level {rec.battery_level}). {vtxt}"
    return f"{rec.battery_level} %", vtxt


def coordinate(value: Optional[float]) -> str:
    return DASH if value is None else f"{value:.5f}"


def position_tooltip(rec: NodeRecord) -> str:
    if rec.latitude is None or rec.longitude is None:
        return "No position reported."
    parts = []
    if rec.latitude == 0.0 and rec.longitude == 0.0:
        parts.append("Reported 0,0 — the node may have no GPS fix.")
    if rec.position_precision_bits is not None:
        parts.append(f"Precision bits: {rec.position_precision_bits} (positions may be deliberately coarsened).")
    if rec.altitude_m is not None:
        parts.append(f"Altitude: {rec.altitude_m} m")
    return "\n".join(parts) or "Source: radio."
