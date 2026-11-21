# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import math

import pytest

from task_maps import tilemath as tm
from task_maps.tilemath import BBox


def test_known_tiles():
    assert tm.lonlat_to_tile(0, 0, 0) == (0, 0)
    assert tm.lonlat_to_tile(-180, 85.0511, 1) == (0, 0)
    assert tm.lonlat_to_tile(179.99, -85.0511, 1) == (1, 1)
    # Seattle at z10 (slippy-map formula, OSM wiki example values)
    assert tm.lonlat_to_tile(-122.3321, 47.6062, 10) == (164, 357)


def test_lat_clamp_and_poles():
    assert tm.clamp_lat(90) == pytest.approx(tm.MAX_LAT)
    assert tm.clamp_lat(-90) == pytest.approx(-tm.MAX_LAT)
    for z in (0, 5, 12):
        n = 2 ** z
        assert tm.lonlat_to_tile(10, 89.9, z)[1] == 0
        assert tm.lonlat_to_tile(10, -89.9, z)[1] == n - 1
    x, y = tm.lonlat_to_world(0, 85.0511287798066, 3)
    assert y == pytest.approx(0, abs=1e-9)
    lon, lat = tm.world_to_lonlat(0, 0, 0)
    assert lat == pytest.approx(85.0511287798066) and lon == -180


def test_lon_wrap_and_180():
    assert tm.wrap_lon(190) == pytest.approx(-170)
    assert tm.wrap_lon(-190) == pytest.approx(170)
    assert tm.wrap_lon(180) == -180
    assert tm.lonlat_to_tile(180, 0, 4)[0] == 15      # east edge stays in the last column


def test_roundtrip_world():
    for lon, lat, z in ((-122.3, 47.6, 12.5), (151.2, -33.9, 7), (0.0, 0.0, 0)):
        x, y = tm.lonlat_to_world(lon, lat, z)
        lon2, lat2 = tm.world_to_lonlat(x, y, z)
        assert lon2 == pytest.approx(lon) and lat2 == pytest.approx(lat)


def test_tile_bounds_contains():
    w, s, e, n = tm.tile_bounds(10, 164, 357)
    assert w <= -122.3321 <= e and s <= 47.6062 <= n


def test_xyz_tms_flip():
    assert tm.xyz_to_tms(0, 0) == 0
    assert tm.xyz_to_tms(3, 0) == 7
    assert tm.xyz_to_tms(3, 7) == 0
    for z in range(6):
        for y in range(2 ** z):
            assert tm.tms_to_xyz(z, tm.xyz_to_tms(z, y)) == y


def test_count_simple():
    world = BBox(-180, -85.06, 180, 85.06)
    for z in range(5):
        assert tm.count_tiles(world, z, z) == 4 ** z
    assert tm.count_tiles(world, 0, 3) == 1 + 4 + 16 + 64


def test_antimeridian_box():
    b = BBox(170, -20, -170, -10)          # crosses 180
    assert b.normalized().crosses_antimeridian
    rs = tm.x_ranges(b, 4)
    assert rs == [(15, 15), (0, 0)]
    tiles = [(z, x, y) for _, z, x, y in tm.iter_tiles(b, 4, 4)]
    assert {x for _, x, _ in tiles} == {0, 15}
    assert len(tiles) == tm.count_tiles(b, 4, 4)
    # the same width on one side is the same count
    assert tm.count_tiles(b, 2, 6) == tm.count_tiles(BBox(-10, -20, 10, -10), 2, 6)


def test_iter_resume_matches_full():
    b = BBox(-123.0, 47.0, -121.5, 48.2)
    full = list(tm.iter_tiles(b, 5, 11))
    assert len(full) == tm.count_tiles(b, 5, 11)
    assert [i for i, *_ in full] == list(range(len(full)))
    assert len(set(t[1:] for t in full)) == len(full)
    for start in (0, 1, 7, len(full) // 3, len(full) - 1, len(full)):
        assert list(tm.iter_tiles(b, 5, 11, start)) == full[start:]


def test_scale_and_distance():
    assert tm.ground_resolution(0, 0) == pytest.approx(156543.03, rel=1e-4)
    m, label = tm.nice_scale(1234)
    assert m <= 1234 and label in ("1 km", "1000 m")
    assert tm.haversine_m(0, 0, 0, 1) == pytest.approx(111195, rel=1e-3)


def test_formats_and_parse():
    assert tm.fmt_decimal(47.6062, -122.3321).startswith("47.60620")
    d = tm.fmt_dms(47.6062, -122.3321)
    assert "47°" in d and "N" in d and "W" in d and "122°" in d
    assert tm.parse_coord("47.6062, -122.3321") == pytest.approx((47.6062, -122.3321))
    for bad in ("", "abc", "91, 0", "0, 181"):
        with pytest.raises(ValueError):
            tm.parse_coord(bad)
    assert not math.isnan(tm.parse_coord("-33.9 151.2")[0])
