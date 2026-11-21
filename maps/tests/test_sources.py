# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import os
import stat
import tomllib
from pathlib import Path

import pytest

from mapfix import user_source
from task_maps import paths, sources

SHIPPED = Path(__file__).resolve().parents[1] / "task_maps" / "data" / "sources.d"
EXAMPLE = Path(__file__).resolve().parents[1] / "share" / "examples" / "local-tile-server.toml"


def base(**kw):
    d = {"schema": 1, "id": "abc", "name": "ABC", "url": "https://tiles.example/{z}/{x}/{y}.png", "attribution": "x"}
    d.update(kw)
    return d


def test_shipped_sources_parse_and_cite_terms():
    cat = sources.load(SHIPPED, "/nonexistent")
    assert not cat.problems, cat.problems
    assert {"usgs-topo", "usgs-imagery", "osm-standard"} <= set(cat.sources)
    for s in cat.sources.values():
        ok, why = sources.download_permission(s)
        if s.offline_download_permitted:
            assert ok, why
            assert s.evidence_urls and s.verified_on and s.evidence
            assert all(u.startswith("https://") for u in s.evidence_urls)
            assert s.rate_limit <= 2 and s.max_concurrency <= 2
            assert s.url.startswith("https://")
    usgs = cat.sources["usgs-topo"]
    assert "basemap.nationalmap.gov" in usgs.host
    assert any("usgs.gov/faqs" in u for u in usgs.evidence_urls)


def test_osm_standard_refused_even_if_marked_permitted():
    cat = sources.load(SHIPPED, "/nonexistent")
    ok, why = sources.download_permission(cat.sources["osm-standard"])
    assert not ok and "operations.osmfoundation.org/policies/tiles" in why
    for host in ("tile.openstreetmap.org", "a.tile.openstreetmap.org", "TILE.OpenStreetMap.org"):
        s = user_source(f"https://{host}/{{z}}/{{x}}/{{y}}.png", sid="sneaky")
        assert s.offline_download_permitted and s.user_attests_permission
        ok, why = sources.download_permission(s)
        assert not ok and "§4" in why
    assert not sources.host_refused("tile.openstreetmap.org.evil.example")
    assert not sources.host_refused("opentopomap.org")


def test_package_source_needs_evidence():
    s = sources.parse(base(offline_download_permitted=True), "package")
    ok, why = sources.download_permission(s)
    assert not ok and "cited terms" in why
    s = sources.parse(base(offline_download_permitted=True, evidence_urls=["https://x.example/terms"],
                           verified_on="2026-10-10", evidence="terms say ok"), "package")
    assert sources.download_permission(s)[0]


def test_not_permitted_source_refused():
    s = sources.parse(base(), "package")
    ok, why = sources.download_permission(s)
    assert not ok and "import an MBTiles" in why


def test_user_attested_source_allowed():
    s = sources.parse(base(offline_download_permitted=True), "user")
    assert not sources.download_permission(s)[0]
    s = sources.parse(base(offline_download_permitted=True, user_attests_permission=True,
                           url="http://192.168.1.10/{z}/{x}/{y}.png"), "user")
    ok, why = sources.download_permission(s)
    assert ok and "user-attested" in why


def test_example_user_source_is_valid():
    with open(EXAMPLE, "rb") as fh:
        s = sources.parse(tomllib.load(fh), "user")
    assert sources.download_permission(s)[0]


@pytest.mark.parametrize("doc, msg", [
    (base(schema=2), "schema"),
    (base(foo=1), "unknown"),
    (base(id="Bad ID"), "id"),
    (base(url="ftp://x/{z}/{x}/{y}"), "http"),
    (base(url="https://x/{z}/{x}"), "{y}"),
    (base(rate_limit=50), "rate_limit"),
    (base(max_concurrency=16), "max_concurrency"),
    (base(min_zoom=10, max_zoom=5), "min_zoom"),
    (base(api_key_required=True), "api_key"),
    (base(user_attests_permission=True), "user source"),
    (base(evidence_urls=["http://insecure"]), "https"),
    (base(verified_on="yesterday"), "YYYY"),
])
def test_invalid_definitions(doc, msg):
    with pytest.raises(sources.SourceError, match=msg):
        sources.parse(doc, "package")


def test_package_requires_https():
    with pytest.raises(sources.SourceError, match="https"):
        sources.parse(base(url="http://x.example/{z}/{x}/{y}.png"), "package")


def test_user_cannot_replace_package_id(tmp_path):
    sysd, userd = tmp_path / "sys", tmp_path / "user"
    sysd.mkdir()
    userd.mkdir()
    (sysd / "a.toml").write_text('schema = 1\nid = "abc"\nname = "Pkg"\nurl = "https://p/{z}/{x}/{y}.png"\n'
                                 'attribution = "p"\n')
    (userd / "a.toml").write_text('schema = 1\nid = "abc"\nname = "Mine"\nurl = "http://u/{z}/{x}/{y}.png"\n'
                                  'attribution = "u"\noffline_download_permitted = true\nuser_attests_permission = true\n')
    (userd / "broken.toml").write_text("this is = = not toml")
    cat = sources.load(sysd, userd)
    assert cat.sources["abc"].name == "Pkg"
    assert len(cat.problems) == 2


def test_api_key_placeholder_storage_and_redaction(tmp_path, caplog):
    s = sources.parse(base(url="https://k.example/{z}/{x}/{y}.png?key={api_key}", api_key_required=True,
                           offline_download_permitted=True, user_attests_permission=True), "user")
    ok, why = sources.download_permission(s, "")
    assert not ok and "API key" in why
    sources.save_key("abc", "SECRET-123")
    kp = sources.keys_path()
    assert kp == paths.config_dir() / "keys.toml"
    assert stat.S_IMODE(os.stat(kp).st_mode) == 0o600
    keys = sources.load_keys()
    assert keys == {"abc": "SECRET-123"}
    assert sources.download_permission(s, keys["abc"])[0]
    url = s.tile_url(1, 0, 0, keys["abc"])
    assert "SECRET-123" in url
    assert "SECRET-123" not in s.redact(url, keys["abc"])
    with pytest.raises(sources.SourceError):
        sources.save_key("abc", "evil\n[keys]\nx = 1")
    sources.save_key("abc", "")
    assert sources.load_keys() == {}


def test_tms_url():
    s = sources.parse(base(mechanism="tms"), "package")
    assert s.tile_url(3, 1, 0) == "https://tiles.example/3/1/7.png"
