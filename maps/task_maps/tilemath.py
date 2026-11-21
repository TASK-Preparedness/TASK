# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Web Mercator (EPSG:3857) slippy-map tile math, XYZ <-> TMS, bbox tile counts, scale and
coordinate formatting. Pure Python, no Qt."""

import math
from dataclasses import dataclass

MAX_LAT = 85.0511287798066          # atan(sinh(pi)) in degrees: the Web Mercator limit
TILE = 256
EARTH_CIRC = 40075016.68557849      # metres, WGS-84 equator (2 * pi * 6378137)


def clamp_lat(lat: float) -> float:
    return max(-MAX_LAT, min(MAX_LAT, lat))


def wrap_lon(lon: float) -> float:
    """Normalise to [-180, 180)."""
    lon = (lon + 180.0) % 360.0 - 180.0
    return lon


def lonlat_to_world(lon: float, lat: float, zoom: float):
    """Fractional tile coordinates (x, y) at ``zoom`` (x unbounded only if lon is)."""
    lat = clamp_lat(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def world_to_lonlat(x: float, y: float, zoom: float):
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def lonlat_to_tile(lon: float, lat: float, z: int):
    n = 2 ** z
    x, y = lonlat_to_world(wrap_lon(lon) if lon != 180.0 else 179.9999999999, lat, z)
    return min(n - 1, max(0, int(math.floor(x)))), min(n - 1, max(0, int(math.floor(y))))


def tile_bounds(z: int, x: int, y: int):
    """(west, south, east, north) of a tile."""
    w, n = world_to_lonlat(x, y, z)
    e, s = world_to_lonlat(x + 1, y + 1, z)
    return w, s, e, n


def xyz_to_tms(z: int, y: int) -> int:
    """XYZ (origin top-left) <-> TMS (origin bottom-left) row flip; the mapping is its own inverse."""
    return (2 ** z) - 1 - y


tms_to_xyz = xyz_to_tms


@dataclass(frozen=True)
class BBox:
    """Geographic box. ``west > east`` means the box crosses the antimeridian."""
    west: float
    south: float
    east: float
    north: float

    def normalized(self) -> "BBox":
        s, n = sorted((clamp_lat(self.south), clamp_lat(self.north)))
        w, e = self.west, self.east
        if e - w >= 360.0:
            return BBox(-180.0, s, 180.0, n)
        w, e = wrap_lon(w), wrap_lon(e)
        if e == -180.0 and self.east > self.west:
            e = 180.0
        return BBox(w, s, e, n)

    @property
    def crosses_antimeridian(self) -> bool:
        return self.west > self.east

    def as_tuple(self):
        return (self.west, self.south, self.east, self.north)


def x_ranges(bbox: BBox, z: int):
    """Inclusive tile-column ranges for a bbox at zoom z (two ranges across the antimeridian)."""
    b = bbox.normalized()
    n = 2 ** z
    if b.crosses_antimeridian:
        x0, _ = lonlat_to_tile(b.west, b.north, z)
        x1, _ = lonlat_to_tile(b.east, b.north, z)
        return [(x0, n - 1), (0, x1)]
    x0, _ = lonlat_to_tile(b.west, b.north, z)
    x1, _ = lonlat_to_tile(b.east if b.east < 180.0 else 180.0, b.north, z)
    return [(x0, x1)]


def y_range(bbox: BBox, z: int):
    b = bbox.normalized()
    _, y0 = lonlat_to_tile(0.0, b.north, z)
    _, y1 = lonlat_to_tile(0.0, b.south, z)
    return y0, y1


def count_tiles(bbox: BBox, minz: int, maxz: int) -> int:
    total = 0
    for z in range(minz, maxz + 1):
        y0, y1 = y_range(bbox, z)
        rows = y1 - y0 + 1
        for x0, x1 in x_ranges(bbox, z):
            total += (x1 - x0 + 1) * rows
    return total


def count_per_zoom(bbox: BBox, minz: int, maxz: int):
    return {z: count_tiles(bbox, z, z) for z in range(minz, maxz + 1)}


def iter_tiles(bbox: BBox, minz: int, maxz: int, start: int = 0):
    """Deterministic order (z, then column ranges, then x, then y) yielding (index, z, x, y).
    ``start`` skips the first ``start`` tiles arithmetically (resume cursor)."""
    index = 0
    for z in range(minz, maxz + 1):
        y0, y1 = y_range(bbox, z)
        rows = y1 - y0 + 1
        for x0, x1 in x_ranges(bbox, z):
            block = (x1 - x0 + 1) * rows
            if index + block <= start:
                index += block
                continue
            skip = max(0, start - index)
            cx, cy = divmod(skip, rows)
            index += skip
            for x in range(x0 + cx, x1 + 1):
                for y in range(y0 + (cy if x == x0 + cx else 0), y1 + 1):
                    yield index, z, x, y
                    index += 1


def ground_resolution(lat: float, zoom: float) -> float:
    """Metres per pixel (256-px tiles) at a latitude."""
    return EARTH_CIRC * math.cos(math.radians(clamp_lat(lat))) / (TILE * 2.0 ** zoom)


def nice_scale(max_metres: float):
    """Largest 1/2/5 x 10^n distance <= max_metres. Returns (metres, label)."""
    if max_metres <= 0:
        return 0.0, "—"
    exp = math.floor(math.log10(max_metres))
    for m in (5, 2, 1):
        v = m * 10 ** exp
        if v <= max_metres:
            break
    return v, (f"{v / 1000:g} km" if v >= 1000 else f"{v:g} m")


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def fmt_decimal(lat: float, lon: float) -> str:
    return f"{lat:.5f}, {lon:.5f}"


def _dms(v: float, pos: str, neg: str) -> str:
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v)
    m_full = (v - d) * 60
    m = int(m_full)
    s = (m_full - m) * 60
    if s >= 59.95:
        s, m = 0.0, m + 1
    if m >= 60:
        m, d = 0, d + 1
    return f"{d}°{m:02d}′{s:04.1f}″{h}"


def fmt_dms(lat: float, lon: float) -> str:
    return f"{_dms(lat, 'N', 'S')} {_dms(lon, 'E', 'W')}"


def fmt_coord(lat: float, lon: float, style: str = "decimal") -> str:
    return fmt_dms(lat, lon) if style == "dms" else fmt_decimal(lat, lon)


def parse_coord(text: str):
    """Parse "lat, lon" in decimal degrees. Returns (lat, lon) or raises ValueError."""
    parts = [p for p in text.replace(";", ",").replace(" ", ",").split(",") if p]
    if len(parts) != 2:
        raise ValueError("enter latitude, longitude in decimal degrees")
    lat, lon = float(parts[0]), float(parts[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or math.isnan(lat) or math.isnan(lon):
        raise ValueError("latitude must be -90..90 and longitude -180..180")
    return lat, lon
