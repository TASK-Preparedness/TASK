# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Reception: decode frames, keep a station table, publish positions to the task-geofeed.
Third-party ('}') packets came from APRS-IS through an IGate and are labelled "via APRS-IS", never RF."""

import time
from dataclasses import dataclass

from task_comms import aprs as codec
from task_comms.feeds import Entity

STATION_STALE_S = 3600


@dataclass
class Station:
    call: str
    last_heard: float
    lat: float = None
    lon: float = None
    kind: str = ""
    via: str = "RF"           # "RF" | "via APRS-IS"
    path: str = ""
    count: int = 0


def parse_third_party(p: codec.AprsPacket, now=None):
    """Inner packet of a '}' third-party packet, or None."""
    body = p.raw[1:]
    if ":" not in body or ">" not in body.split(":", 1)[0]:
        return None
    hdr, info = body.split(":", 1)
    src, rest = hdr.split(">", 1)
    parts = rest.split(",")
    try:
        f = codec.Frame(codec.parse_callsign(parts[0]), codec.parse_callsign(src.rstrip("*")), [],
                        control=0x03, pid=0xF0, info=info.encode("latin-1", "replace"))
    except ValueError:
        return None
    inner = codec.parse_aprs(f, p.port, now)
    inner.path = ",".join(parts[1:])
    return inner


class Receiver:
    def __init__(self, feed=None, clock=time.time, on_packet=None, on_station=None, on_message=None):
        self.feed, self.clock = feed, clock
        self.on_packet, self.on_station, self.on_message = on_packet, on_station, on_message
        self.stations = {}
        self.frames = 0
        self.errors = 0
        self.last_frame_ts = None

    def handle(self, channel: int, raw: bytes, mycall: str = ""):
        now = self.clock()
        try:
            frame = codec.decode_ax25(raw)
        except codec.AX25Error:
            self.errors += 1
            return None
        self.frames += 1
        self.last_frame_ts = now
        p = codec.parse_aprs(frame, channel, now)
        via = "RF"
        if p.kind == "third-party":
            inner = parse_third_party(p, now)
            if inner is not None:
                p, via = inner, "via APRS-IS"
        if self.on_packet:
            self.on_packet(frame, p, via)
        self._station(p, via, now)
        if p.kind == "message" and mycall and p.addressee.upper() == mycall.upper() \
                and codec.parse_ack(p) is None and self.on_message:
            self.on_message(p, via)
        return p

    def _station(self, p, via, now):
        s = self.stations.get(p.source) or Station(p.source, now)
        s.last_heard, s.kind, s.via, s.path = now, p.kind, via, p.path
        s.count += 1
        if p.lat is not None and p.lon is not None:
            s.lat, s.lon = p.lat, p.lon
            if self.feed is not None:
                self.feed.upsert(Entity(id=f"aprs:{p.source}", layer="aprs", label=p.source, lat=p.lat, lon=p.lon,
                                        observed_ts=int(now), source="APRS " + via, kind="observed",
                                        stale_after_s=STATION_STALE_S, attrs={"via": via, "type": p.kind}))
        self.stations[p.source] = s
        if self.on_station:
            self.on_station(s)
