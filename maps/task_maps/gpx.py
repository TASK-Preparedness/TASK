# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GPX 1.1 import/export (stdlib ElementTree).

Extension namespace: ``urn:rain:task:gpx-ext:1`` (prefix ``rain``), resolving the placeholder of
docs/MISSION-PLANNER-INTERFACE.md. It is a URN, so no domain is needed and nothing is fetched.

Import safety: files larger than 16 MiB are refused; any DOCTYPE or ENTITY declaration is
refused before parsing (no DTDs, no external or internal entities, so no billion-laughs or XXE);
element counts are capped; coordinates are range-checked. Export never overwrites an existing
file unless the caller passes ``overwrite=True`` after asking the user.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from task_maps import APP_NAME, __version__, atomic
from task_maps.waypoints import TrackPoint

GPX_NS = "http://www.topografix.com/GPX/1/1"
GPX10_NS = "http://www.topografix.com/GPX/1/0"
RAIN_NS = "urn:rain:task:gpx-ext:1"
MAX_BYTES = 16 * 1024 * 1024
MAX_WPT = 50_000
MAX_TRK = 1_000
MAX_POINTS = 1_000_000
_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


class GpxError(ValueError):
    pass


def _f(v):
    return f"{v:.7f}".rstrip("0").rstrip(".")


def export(waypoints, tracks, name="T.A.S.K. export", now_iso="") -> bytes:
    ET.register_namespace("", GPX_NS)
    ET.register_namespace("rain", RAIN_NS)
    g = ET.Element(f"{{{GPX_NS}}}gpx", {"version": "1.1", "creator": f"{APP_NAME} {__version__}"})
    md = ET.SubElement(g, f"{{{GPX_NS}}}metadata")
    ET.SubElement(md, f"{{{GPX_NS}}}name").text = name
    if now_iso:
        ET.SubElement(md, f"{{{GPX_NS}}}time").text = now_iso
    for w in waypoints:
        e = ET.SubElement(g, f"{{{GPX_NS}}}wpt", {"lat": _f(w.lat), "lon": _f(w.lon)})
        if w.ele is not None:
            ET.SubElement(e, f"{{{GPX_NS}}}ele").text = f"{w.ele:.1f}"
        if w.time:
            ET.SubElement(e, f"{{{GPX_NS}}}time").text = w.time
        ET.SubElement(e, f"{{{GPX_NS}}}name").text = w.name
        if w.desc:
            ET.SubElement(e, f"{{{GPX_NS}}}desc").text = w.desc
        if w.sym:
            ET.SubElement(e, f"{{{GPX_NS}}}sym").text = w.sym
        ext = ET.SubElement(e, f"{{{GPX_NS}}}extensions")
        ET.SubElement(ext, f"{{{RAIN_NS}}}id").text = w.id
        ET.SubElement(ext, f"{{{RAIN_NS}}}source").text = w.source
        if w.accuracy_m is not None:
            ET.SubElement(ext, f"{{{RAIN_NS}}}accuracy_m").text = f"{w.accuracy_m:.1f}"
    for t in tracks:
        te = ET.SubElement(g, f"{{{GPX_NS}}}trk")
        ET.SubElement(te, f"{{{GPX_NS}}}name").text = t.name
        ext = ET.SubElement(te, f"{{{GPX_NS}}}extensions")
        ET.SubElement(ext, f"{{{RAIN_NS}}}id").text = t.id
        ET.SubElement(ext, f"{{{RAIN_NS}}}source").text = t.source
        seg = ET.SubElement(te, f"{{{GPX_NS}}}trkseg")
        for p in t.points:
            pe = ET.SubElement(seg, f"{{{GPX_NS}}}trkpt", {"lat": _f(p.lat), "lon": _f(p.lon)})
            if p.ele is not None:
                ET.SubElement(pe, f"{{{GPX_NS}}}ele").text = f"{p.ele:.1f}"
            if p.time:
                ET.SubElement(pe, f"{{{GPX_NS}}}time").text = p.time
    ET.indent(g)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(g, encoding="utf-8") + b"\n"


def write_file(path, data: bytes, overwrite=False):
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists")
    atomic.write_bytes(path, data, 0o644)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _coord(e):
    try:
        lat, lon = float(e.get("lat")), float(e.get("lon"))
    except (TypeError, ValueError):
        raise GpxError("point without valid lat/lon") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise GpxError(f"coordinate out of range: {lat}, {lon}")
    return lat, lon


def _child(e, name):
    for c in e:
        if _local(c.tag) == name:
            return c
    return None


def _text(e, name, maxlen=500):
    c = _child(e, name)
    return (c.text or "").strip()[:maxlen] if c is not None and c.text else ""


def _ele(e):
    t = _text(e, "ele", 32)
    try:
        return float(t) if t else None
    except ValueError:
        return None


def parse(data: bytes):
    """Return (waypoints: list[dict], tracks: list[(name, [TrackPoint])], warnings)."""
    if len(data) > MAX_BYTES:
        raise GpxError(f"file too large (> {MAX_BYTES // (1024 * 1024)} MiB)")
    if _DECL.search(data):
        raise GpxError("DOCTYPE/ENTITY declarations are not allowed in GPX files")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise GpxError(f"not valid XML: {exc}") from None
    if _local(root.tag) != "gpx" or not root.tag.startswith(("{" + GPX_NS, "{" + GPX10_NS)):
        raise GpxError("not a GPX 1.0/1.1 document")
    wpts, trks, warnings = [], [], []
    npts = 0
    for e in root:
        tag = _local(e.tag)
        if tag == "wpt":
            if len(wpts) >= MAX_WPT:
                raise GpxError(f"more than {MAX_WPT} waypoints")
            try:
                lat, lon = _coord(e)
            except GpxError as exc:
                warnings.append(f"waypoint skipped: {exc}")
                continue
            ext = _child(e, "extensions")
            rid = _text(ext, "id", 64) if ext is not None else ""
            wpts.append({"name": _text(e, "name", 40) or f"WPT {len(wpts) + 1}", "lat": lat, "lon": lon,
                         "ele": _ele(e), "time": _text(e, "time", 40), "desc": _text(e, "desc"),
                         "sym": _text(e, "sym", 40), "rain_id": rid})
        elif tag in ("trk", "rte"):
            if len(trks) >= MAX_TRK:
                raise GpxError(f"more than {MAX_TRK} tracks")
            pts = []
            sources = [s for s in e if _local(s.tag) == "trkseg"] if tag == "trk" else [e]
            ptag = "trkpt" if tag == "trk" else "rtept"
            for seg in sources:
                for p in seg:
                    if _local(p.tag) != ptag:
                        continue
                    npts += 1
                    if npts > MAX_POINTS:
                        raise GpxError(f"more than {MAX_POINTS} track points")
                    try:
                        lat, lon = _coord(p)
                    except GpxError as exc:
                        warnings.append(f"point skipped: {exc}")
                        continue
                    pts.append(TrackPoint(lat, lon, _ele(p), _text(p, "time", 40)))
            trks.append((_text(e, "name", 40) or f"{'Track' if tag == 'trk' else 'Route'} {len(trks) + 1}", pts))
    return wpts, trks, warnings


def import_file(path, store):
    """Parse a GPX file and add its contents to the waypoint store. Returns a summary dict."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise GpxError(f"file too large (> {MAX_BYTES // (1024 * 1024)} MiB)")
    wpts, trks, warnings = parse(path.read_bytes())
    src = f"import:{path.name}"[:60]
    for w in wpts:
        store.add_waypoint(w["name"], w["lat"], w["lon"], ele=w["ele"], source=src, desc=w["desc"], sym=w["sym"],
                           time_iso=w["time"])
    for name, pts in trks:
        store.add_track(name, pts, source=src)
    return {"waypoints": len(wpts), "tracks": len(trks), "points": sum(len(p) for _, p in trks), "warnings": warnings}
