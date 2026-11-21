# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import xml.etree.ElementTree as ET

import pytest

from task_maps import gpx
from task_maps.waypoints import Store, TrackFilter, TrackPoint


def test_waypoint_crud_persists(tmp_path):
    db = tmp_path / "w.sqlite"
    s = Store(db)
    a = s.add_waypoint("Camp", 47.6, -122.3, ele=50.0, source="gps", accuracy_m=4.0)
    b = s.add_waypoint("Ridge", 47.7, -122.1, source="map")
    s.update_waypoint(a.id, name="Base camp")
    s.update_waypoint(b.id, lat=47.71, lon=-122.11)
    s.delete_waypoint(b.id)
    with pytest.raises(ValueError):
        s.add_waypoint("bad", 95, 0)
    with pytest.raises(ValueError):
        s.add_waypoint("", 1, 1)
    rev = s.revision()
    s.close()
    s = Store(db)                                   # "reboot"
    wps = s.waypoints()
    assert [w.name for w in wps] == ["Base camp"] and wps[0].accuracy_m == 4.0 and wps[0].source == "gps"
    assert s.revision() == rev
    s.close()


def test_track_recording_persists(tmp_path):
    db = tmp_path / "w.sqlite"
    s = Store(db)
    t = s.start_track("Walk")
    for i in range(5):
        s.append_point(t.id, TrackPoint(47.6 + i * 0.001, -122.3, time=f"2026-10-10T12:00:0{i}Z"))
    assert s.recording_track().id == t.id
    s.close()
    s = Store(db)
    assert s.recording_track().id == t.id            # recording survives a restart
    s.stop_track(t.id)
    s.rename_track(t.id, "Morning walk")
    trk = s.tracks()[0]
    assert trk.name == "Morning walk" and len(trk.points) == 5 and not trk.recording
    assert trk.length_m() == pytest.approx(444.8, rel=0.01)
    s.delete_track(t.id)
    assert s.tracks() == []
    s.close()


def test_track_filter():
    f = TrackFilter()
    assert not f.accept(47.6, -122.3, 0, mode=1)
    assert not f.accept(47.6, -122.3, 0, mode=3, accuracy_m=80)
    assert f.accept(47.6, -122.3, 0)
    assert not f.accept(47.60001, -122.3, 1)          # 1 m jitter
    assert not f.accept(47.60002, -122.3, 40)         # 2 m after 40 s: still jitter
    assert f.accept(47.60004, -122.3, 41)             # 4.4 m after >30 s
    assert f.accept(47.6002, -122.3, 42)              # >10 m


def test_gpx_roundtrip(tmp_path):
    s = Store(tmp_path / "a.sqlite")
    s.add_waypoint("Camp & <Co>", 47.6062, -122.3321, ele=52.5, source="gps", accuracy_m=3.5,
                   time_iso="2026-10-10T12:00:00Z", desc="water \"here\"")
    t = s.add_track("Trail", [TrackPoint(47.6, -122.3, 10.0, "2026-10-10T12:00:00Z"),
                              TrackPoint(47.61, -122.31, 11.0, "2026-10-10T12:01:00Z")], source="gps")
    data = gpx.export(s.waypoints(), s.tracks(), now_iso="2026-10-10T12:00:00Z")
    root = ET.fromstring(data)
    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx" and root.get("version") == "1.1"
    assert gpx.RAIN_NS == "urn:rain:task:gpx-ext:1" and gpx.RAIN_NS.encode() in data
    out = tmp_path / "x.gpx"
    gpx.write_file(out, data)
    s2 = Store(tmp_path / "b.sqlite")
    res = gpx.import_file(out, s2)
    assert res == {"waypoints": 1, "tracks": 1, "points": 2, "warnings": []}
    w = s2.waypoints()[0]
    assert (w.name, w.lat, w.lon, w.ele, w.desc) == ("Camp & <Co>", 47.6062, -122.3321, 52.5, 'water "here"')
    tr = s2.tracks()[0]
    assert tr.name == "Trail" and [(p.lat, p.lon, p.ele) for p in tr.points] == [(47.6, -122.3, 10.0),
                                                                                (47.61, -122.31, 11.0)]
    assert w.source.startswith("import:")
    assert t.id != tr.id


def test_no_overwrite_without_confirmation(tmp_path):
    out = tmp_path / "keep.gpx"
    out.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        gpx.write_file(out, b"<gpx/>")
    assert out.read_bytes() == b"original"
    gpx.write_file(out, b"<gpx/>", overwrite=True)
    assert out.read_bytes() == b"<gpx/>"


BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1"><wpt lat="1" lon="1"><name>&lol2;</name></wpt></gpx>"""
XXE = b"""<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1"><wpt lat="1" lon="1"><name>&xxe;</name></wpt></gpx>"""


@pytest.mark.parametrize("data, msg", [
    (BILLION_LAUGHS, "DOCTYPE"),
    (XXE, "DOCTYPE"),
    (b"<?xml version='1.0'?><!doctype gpx><gpx/>", "DOCTYPE"),
    (b"<gpx><unclosed>", "not valid XML"),
    (b"<kml xmlns='http://www.opengis.net/kml/2.2'/>", "not a GPX"),
    (b"<gpx version='1.1'/>", "not a GPX"),
])
def test_malicious_or_invalid_xml_rejected(data, msg):
    with pytest.raises(gpx.GpxError, match=msg):
        gpx.parse(data)


def test_oversize_and_bad_points(tmp_path, monkeypatch):
    monkeypatch.setattr(gpx, "MAX_BYTES", 1000)
    with pytest.raises(gpx.GpxError, match="too large"):
        gpx.parse(b" " * 1001)
    monkeypatch.setattr(gpx, "MAX_BYTES", 16 * 1024 * 1024)
    doc = (b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">'
           b'<wpt lat="91" lon="0"><name>bad</name></wpt><wpt lat="1" lon="2"><name>ok</name></wpt>'
           b'<wpt lat="x" lon="2"/></gpx>')
    w, t, warn = gpx.parse(doc)
    assert [x["name"] for x in w] == ["ok"] and len(warn) == 2
    monkeypatch.setattr(gpx, "MAX_WPT", 2)
    many = (b'<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">' +
            b'<wpt lat="1" lon="1"/>' * 3 + b"</gpx>")
    with pytest.raises(gpx.GpxError, match="more than 2"):
        gpx.parse(many)


def test_gpx10_routes_accepted():
    doc = (b'<gpx xmlns="http://www.topografix.com/GPX/1/0" version="1.0"><rte><name>R</name>'
           b'<rtept lat="1" lon="1"/><rtept lat="2" lon="2"/></rte></gpx>')
    w, t, warn = gpx.parse(doc)
    assert t[0][0] == "R" and len(t[0][1]) == 2
