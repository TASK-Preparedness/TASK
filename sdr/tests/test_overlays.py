# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""M3 overlay framework: format, strict validation, malformed-data rejection, loading, UI integration.
Only EXAMPLE fixtures are used (tests/fixtures/overlays); no external dataset is involved."""

import copy
import datetime as dt
import json
import os
import shutil
from pathlib import Path

import pytest

from task_sdr import overlays as O
from task_sdr import prefs as P
from task_sdr.engine import Engine

FX = Path(__file__).parent / "fixtures" / "overlays"
SRC = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 13)


def good(**over):
    d = json.loads((FX / "example-markers.json").read_text())
    d.update(over)
    return d


def ok(d):
    return O.parse_dataset(d, today=TODAY)


def bad(d, fragment):
    with pytest.raises(O.OverlayError) as ei:
        O.parse_dataset(d, today=TODAY)
    assert fragment in str(ei.value), str(ei.value)


# ---------------------------------------------------------------- fixtures are clearly examples
def test_o01_fixtures_are_marked_examples():
    files = sorted(FX.glob("*.json"))
    assert files
    for p in files:
        d = json.loads(p.read_text())
        assert d["id"].startswith("example-") and d["example"] is True
        assert "EXAMPLE" in d["title"] and d["source"]["agency"].startswith("EXAMPLE")
        assert d["source"]["url"].startswith("https://example.invalid/")
        ds = O.load_file(p, today=TODAY)
        assert "example" in ds.status(TODAY)
    assert "NOT REFERENCE DATA" in (FX / "EXAMPLE-README.txt").read_text()


def test_o02_no_dataset_shipped_in_package_tree():
    # the framework ships the schema only; overlays/ holds the schema (+ source snapshots that are never packaged)
    shipped = [p for p in (SRC / "overlays").rglob("*.json") if "sources" not in p.parts]
    assert [p.name for p in shipped] == ["overlay-v1.schema.json"]
    debian = SRC / "debian"
    if debian.exists():
        for p in debian.rglob("*"):
            if p.is_file():
                t = p.read_text(errors="ignore")
                assert "overlays/sources" not in t and "fixtures/overlays" not in t


def test_o03_schema_document_matches_validator():
    s = json.loads((SRC / "overlays" / "schema" / "overlay-v1.schema.json").read_text())
    assert s["$id"] == O.SCHEMA and s["additionalProperties"] is False
    assert tuple(s["required"]) == O.TOP_REQUIRED
    assert set(s["properties"]) == set(O.TOP_REQUIRED + O.TOP_OPTIONAL)
    assert s["properties"]["type"]["enum"] == list(O.TYPES)
    assert s["$defs"]["hz"]["minimum"] == O.MIN_HZ and s["$defs"]["hz"]["maximum"] == O.MAX_HZ
    assert set(s["properties"]["source"]["properties"]) == set(O.SOURCE_KEYS_REQUIRED + O.SOURCE_KEYS_OPTIONAL)
    r, m = s["$defs"]["range"], s["$defs"]["marker"]
    assert set(r["properties"]) == set(O.ITEM_COMMON + O.RANGE_KEYS + O.ITEM_OPTIONAL)
    assert set(m["properties"]) == set(O.ITEM_COMMON + O.MARKER_KEYS + O.MARKER_OPTIONAL + O.ITEM_OPTIONAL)


# ---------------------------------------------------------------- valid parsing / models
def test_o04_parse_valid_and_models():
    ds = ok(good())
    assert ds.type == "channel_plan" and len(ds.items) == 2
    m = ds.items[0]
    assert (m.kind, m.freq_hz, m.bandwidth_hz, m.start_hz, m.end_hz) == ("marker", 146_000_000, 12_500,
                                                                         145_993_750, 146_006_250)
    assert m.tune_hz() == 146_000_000
    r = O.load_file(FX / "example-ranges.json", today=TODAY).items[0]
    assert r.kind == "range" and r.tune_hz() == 146_000_000
    for it in ds.items:
        assert O._item(it.to_json(), "rt") == it


def test_o05_status_unverified_stale():
    d = good(last_verified=None)
    assert "unverified" in ok(d).status(TODAY)
    d = good(last_verified="2025-01-01", stale_after_days=30)
    s = ok(d).status(TODAY)
    assert "stale" in s and "unverified" not in s
    d = good(last_verified="2026-10-01", stale_after_days=30)
    assert ok(d).status(TODAY) == ["example"]
    d = good(last_verified="2025-10-13")
    d.pop("stale_after_days")
    ds = ok(d)
    assert ds.stale_after_days == 365 and "stale" not in ds.status(TODAY)
    assert "stale" in ds.status(TODAY + dt.timedelta(days=1))


# ---------------------------------------------------------------- malformed data (whole-file rejection)
def _items(*its):
    return good(items=list(its))


M = {"kind": "marker", "label": "x", "freq_hz": 146_000_000}
R = {"kind": "range", "label": "x", "start_hz": 146_000_000, "end_hz": 146_100_000}


@pytest.mark.parametrize("doc,frag", [
    (_items({**M, "freq_hz": 146.52e6}), "integer number of Hz"),
    (_items({**M, "freq_hz": 146_000_000.0}), "integer number of Hz"),
    (_items({**M, "freq_hz": "146000000"}), "integer number of Hz"),
    (_items({**M, "freq_hz": True}), "integer number of Hz"),
    (_items({**M, "freq_hz": None}), "integer number of Hz"),
    (_items({**M, "freq_hz": 0}), "outside"),
    (_items({**M, "freq_hz": -1}), "outside"),
    (_items({**M, "freq_hz": 6_000_000_001}), "outside"),
    (_items({**M, "freq_hz": 10**30}), "outside"),
    (_items({**M, "bandwidth_hz": 0}), "outside"),
    (_items({**M, "bandwidth_hz": 1_000_000_001}), "outside"),
    (_items({**M, "freq_hz": 5_999_999_000, "bandwidth_hz": 10_000}), "leaves"),
    (_items({**M, "freq_hz": 1000, "bandwidth_hz": 10_000}), "leaves"),
    (_items({**R, "start_hz": 146_100_000}), "must be below"),
    (_items({**R, "start_hz": 146_200_000}), "must be below"),
    (_items({**R, "end_hz": 146.1e6}), "integer number of Hz"),
    (_items({"kind": "range", "label": "x", "start_hz": 1}), "missing end_hz"),
    (_items({"kind": "marker", "label": "x"}), "missing freq_hz"),
    (_items({**M, "freq_mhz": 146.0}), "unknown key"),
    (_items({**R, "freq_hz": 146_000_000}), "unknown key"),
    (_items({**M, "kind": "polygon"}), "must be 'range' or 'marker'"),
    (_items({**M, "label": ""}), "must not be empty"),
    (_items({**M, "label": "a" * 201}), "longer than"),
    (_items({**M, "label": "bad\x00label"}), "control characters"),
    (_items({**M, "label": 5}), "must be text"),
    (_items({**M, "tags": ["UPPER"]}), "tags"),
    (_items({**M, "tags": "x"}), "tags"),
    (_items(M, dict(M)), "duplicate of an earlier item"),
    (_items("146000000"), "must be an object"),
    (good(items={"a": 1}), "items: must be a list"),
    (good(schema="task-sdr-overlay/2"), "schema"),
    (good(id="Example Bad"), "id:"),
    (good(id="../etc/passwd"), "id:"),
    (good(type="repeater"), "type:"),
    (good(version=""), "version"),
    (good(version=1), "version"),
    (good(title=""), "title"),
    (good(extra=1), "unknown key"),
    (good(stale_after_days=0), "stale_after_days"),
    (good(stale_after_days=True), "stale_after_days"),
    (good(stale_after_days=3651), "stale_after_days"),
    (good(example="yes"), "example"),
    (good(publication_date="2026-13-01"), "invalid date"),
    (good(publication_date="13/10/2026"), "YYYY-MM-DD"),
    (good(publication_date=None), "required"),
    (good(retrieved="2027-01-01"), "in the future"),
    (good(last_verified="2026-10-14"), "in the future"),
    (good(retrieved="2025-12-31"), "earlier than publication_date"),
    (good(source={"agency": "x", "citation": "y"}), "source.url: required"),
    (good(source={"agency": "x", "citation": "y", "url": "http://insecure.example/x"}), "https://"),
    (good(source={"agency": "x", "citation": "y", "url": "javascript:alert(1)"}), "https://"),
    (good(source={"agency": "", "citation": "y", "url": "https://a.example"}), "must not be empty"),
    (good(source={"agency": "x", "citation": "y", "url": "https://a.example", "licence": "?"}), "unknown key"),
    (good(source="FCC"), "must be an object"),
], ids=lambda v: v if isinstance(v, str) else None)
def test_o06_malformed_rejected(doc, frag):
    bad(doc, frag)


def test_o07_missing_required_each():
    for k in O.TOP_REQUIRED:
        d = good()
        d.pop(k)
        bad(d, f"missing {k}")


def test_o08_item_limit():
    d = good(items=[{**M, "freq_hz": 100_000_000 + i} for i in range(O.MAX_ITEMS + 1)])
    bad(d, "more than")


@pytest.mark.parametrize("raw,frag", [
    (b'{"schema": "task-sdr-overlay/1", "schema": "x"}', "duplicate JSON key"),
    (b'{"a": NaN}', "non-finite"),
    (b'{"a": Infinity}', "non-finite"),
    (b'{"a": 1', "invalid JSON"),
    (b'', "invalid JSON"),
    (b'\xff\xfe{}', "not UTF-8"),
    (b'[]', "must be an object"),
    (b'null', "must be an object"),
])
def test_o09_malformed_files(tmp_path, raw, frag):
    p = tmp_path / "x.json"
    p.write_bytes(raw)
    with pytest.raises(O.OverlayError) as ei:
        O.load_file(p, today=TODAY)
    assert frag in str(ei.value)


def test_o10_file_type_and_size(tmp_path):
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (O.MAX_FILE_BYTES + 1))
    with pytest.raises(O.OverlayError, match="larger than"):
        O.load_file(big)
    link = tmp_path / "link.json"
    link.symlink_to(FX / "example-markers.json")
    with pytest.raises(O.OverlayError, match="symlinks"):
        O.load_file(link)
    (tmp_path / "dir.json").mkdir()
    with pytest.raises(O.OverlayError, match="regular file"):
        O.load_file(tmp_path / "dir.json")


# ---------------------------------------------------------------- loading from system + user dirs
def _dirs(tmp_path):
    sysd, usr = tmp_path / "usr-share", tmp_path / "home-share"
    sysd.mkdir()
    usr.mkdir()
    return sysd, usr, [("system", sysd), ("user", usr)]


def test_o11_search_dirs_are_usr_share_and_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    d = dict(O.search_dirs())
    assert d["system"] == Path("/usr/share/task-sdr/overlays")
    assert d["user"] == tmp_path / "xdg" / "task-sdr" / "overlays"


def test_o12_load_all_mixed_good_and_bad(tmp_path):
    sysd, usr, dirs = _dirs(tmp_path)
    shutil.copy(FX / "example-ranges.json", sysd)
    shutil.copy(FX / "example-markers.json", usr)
    (sysd / "broken.json").write_text('{"schema": "task-sdr-overlay/1"')
    half = good(id="example-half", items=[M, {**M, "freq_hz": 1.5}])          # one bad item => whole file out
    (usr / "half.json").write_text(json.dumps(half))
    (sysd / "ignored.txt").write_text("not json")
    res = O.load_all(dirs, today=TODAY)
    assert sorted(d.id for d in res.datasets) == ["example-markers", "example-ranges"]
    assert {Path(p).name for p, _ in res.errors} == {"broken.json", "half.json"}
    origins = {d.id: d.origin for d in res.datasets}
    assert origins == {"example-ranges": "system", "example-markers": "user"}
    assert all(len(d.sha256) == 64 for d in res.datasets)


def test_o13_no_shadowing_and_user_type_confined(tmp_path):
    sysd, usr, dirs = _dirs(tmp_path)
    shutil.copy(FX / "example-markers.json", sysd)
    shutil.copy(FX / "example-markers.json", usr / "copy.json")
    ua = {"schema": O.SCHEMA, "id": "example-ua", "title": "EXAMPLE", "type": "user_annotation", "version": "1",
          "source": {"agency": "user", "citation": ""}, "publication_date": None, "retrieved": None,
          "last_verified": None, "items": [M]}
    (sysd / "ua.json").write_text(json.dumps(ua))
    res = O.load_all(dirs, today=TODAY)
    assert [d.id for d in res.datasets] == ["example-markers"] and res.datasets[0].origin == "system"
    why = dict((Path(p).name, w) for p, w in res.errors)
    assert "already loaded" in why["copy.json"] and "only accepted from the user" in why["ua.json"]


def test_o14_updates_without_rebuild(tmp_path):
    sysd, usr, dirs = _dirs(tmp_path)
    assert O.load_all(dirs).datasets == []
    shutil.copy(FX / "example-markers.json", usr)
    assert [d.version for d in O.load_all(dirs).datasets] == ["0.0.1-example"]
    d = good(version="0.0.2-example")
    (usr / "example-markers.json").write_text(json.dumps(d))
    assert [d.version for d in O.load_all(dirs).datasets] == ["0.0.2-example"]


def test_o15_missing_dirs_and_background_loader(tmp_path):
    assert O.load_all([("system", tmp_path / "nope")]).datasets == []
    got = []
    sysd, usr, dirs = _dirs(tmp_path)
    shutil.copy(FX / "example-ranges.json", sysd)
    th = O.BackgroundLoader(got.append, dirs).start()
    th.join(10)
    assert th.name == "overlay-loader" and th.daemon and len(got) == 1 and len(got[0].datasets) == 1


# ---------------------------------------------------------------- query / search / toggles
def _set(tmp_path):
    ds = [O.load_file(FX / f, today=TODAY, origin="system") for f in ("example-ranges.json", "example-markers.json")]
    return O.OverlaySet(ds)


def test_o16_default_off_and_visible(tmp_path):
    s = _set(tmp_path)
    assert s.visible(140_000_000, 150_000_000) == []                     # nothing shown until enabled
    s.set_enabled("example-markers", True)
    v = s.visible(146_000_000, 146_010_000)
    assert [it.label for _, it in v] == ["EXAMPLE ch 1"]
    s.set_enabled("example-ranges", True)
    assert {it.label for _, it in s.visible(146_050_000, 146_450_000)} == {"EXAMPLE range A", "EXAMPLE range B"}
    with pytest.raises(KeyError):
        s.set_enabled("nope", True)


def test_o17_search_filter(tmp_path):
    s = _set(tmp_path)
    assert len(s.search("")) == 4
    assert [it.label for _, it in s.search("ch 2")] == ["EXAMPLE ch 2"]
    assert [it.label for _, it in s.search("example ref 1")] == ["EXAMPLE ch 1"]
    assert {it.label for _, it in s.search("146.5")} == {"EXAMPLE range B"}
    assert {it.label for _, it in s.search("146000 khz")} == {"EXAMPLE ch 1", "EXAMPLE range A"}
    assert {it.label for _, it in s.search("", types=("allocation",))} == {"EXAMPLE range A", "EXAMPLE range B"}
    assert s.search("", enabled_only=True) == []
    assert s.search("zzz") == []


def test_o18_toggles_file(tmp_path):
    p = tmp_path / "cfg" / "overlays.json"
    O.save_toggles({"example-a": True, "example-b": False}, p)
    assert oct(p.stat().st_mode & 0o777) == "0o600" and oct(p.parent.stat().st_mode & 0o777) == "0o700"
    assert O.load_toggles(p) == {"example-a": True, "example-b": False}
    p.write_text('{"Bad Id": true, "example-c": "yes", "example-d": true}')
    assert O.load_toggles(p) == {"example-d": True}
    p.write_text("garbage")
    assert O.load_toggles(p) == {}
    assert O.load_toggles(tmp_path / "missing.json") == {}


# ---------------------------------------------------------------- user annotations
def test_o19_user_annotations_crud(tmp_path):
    u = O.UserAnnotations(tmp_path / "ov")
    u.add_marker(146_520_000, "my note")
    u.add_range(146_000_000, 146_100_000, "my range")
    p = tmp_path / "ov" / O.USER_FILE
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    ds = O.load_file(p, origin="user")
    assert ds.type == "user_annotation" and [i.label for i in ds.items] == ["my note", "my range"]
    assert "user" in ds.status() and "unverified" in ds.status()
    u2 = O.UserAnnotations(tmp_path / "ov")
    u2.edit_label(0, "renamed")
    u2.remove(1)
    assert [i.label for i in O.UserAnnotations(tmp_path / "ov").items] == ["renamed"]


def test_o20_user_annotations_validated_before_write(tmp_path):
    u = O.UserAnnotations(tmp_path / "ov")
    u.add_marker(146_520_000, "keep")
    before = (tmp_path / "ov" / O.USER_FILE).read_bytes()
    for call in (lambda: u.add_marker(146.5e6, "float"), lambda: u.add_marker(0, "zero"),
                 lambda: u.add_marker(146_000_000, ""), lambda: u.add_range(2, 1, "backwards"),
                 lambda: u.add_marker(146_520_000, "keep"), lambda: u.edit_label(0, "x" * 500)):
        with pytest.raises(O.OverlayError):
            call()
    assert (tmp_path / "ov" / O.USER_FILE).read_bytes() == before and [i.label for i in u.items] == ["keep"]
    assert not [p for p in (tmp_path / "ov").iterdir() if p.name.startswith(".tmp-")]


def test_o21_corrupt_user_file_is_reported_not_overwritten(tmp_path):
    d = tmp_path / "ov"
    d.mkdir()
    (d / O.USER_FILE).write_text("{broken")
    with pytest.raises(O.OverlayError):
        O.UserAnnotations(d)
    assert (d / O.USER_FILE).read_text() == "{broken"


# ---------------------------------------------------------------- UI integration
@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    from task_sdr import backends as B
    from task_sdr.backends.simulated import SimulatedBackend
    from task_sdr.ui.main_window import MainWindow
    sysd = tmp_path / "sys"
    sysd.mkdir()
    for f in ("example-ranges.json", "example-markers.json"):
        shutil.copy(FX / f, sysd)
    (sysd / "broken.json").write_text("{")
    usr = tmp_path / "data" / "task-sdr" / "overlays"
    opts = {"dirs": [("system", sysd), ("user", usr)], "toggles_path": tmp_path / "cfg" / "ov.json", "user_dir": usr}
    e = Engine(P.Prefs(), lambda: None, status_dir=str(tmp_path / "s"), claim_dir=str(tmp_path / "c"))
    w = MainWindow(e, None, tmp_path / "p.json", backends=[SimulatedBackend(), *[b for b in B.registry() if b.stub]],
                   overlay_opts=opts)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: bool(not w.overlays.loading and w.overlays.set.datasets), timeout=10000)
    yield w, e, tmp_path
    w.close()


def test_o22_panel_loads_notes_and_errors(window):
    w, e, _ = window
    ov = w.overlays
    assert set(ov.set.datasets) == {"example-ranges", "example-markers"}
    assert "Listed does not mean active" in ov.note.text() and "not transmit authorization" in ov.note.text()
    assert "broken.json" in ov.errors_lbl.text() and "1 file(s) rejected" in ov.status.text()
    assert ov.tree.topLevelItemCount() == 2 and ov.results.count() == 4
    statuses = {ov.tree.topLevelItem(i).text(0): ov.tree.topLevelItem(i).text(2) for i in range(2)}
    assert "EXAMPLE" in statuses["EXAMPLE ranges (test fixture)"] and "UNVERIFIED" in statuses["EXAMPLE ranges (test fixture)"]
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Scanner", "Overlays"]
    assert w.view.overlay_items == []                                   # off by default


def test_o23_source_info_panel(window):
    from PySide6.QtCore import Qt
    w, _, _ = window
    ov = w.overlays
    ov.tree.setCurrentItem(ov.tree.findItems("EXAMPLE ranges (test fixture)", Qt.MatchFlag.MatchExactly, 0)[0])
    t = ov.info.toPlainText()
    for s in ("EXAMPLE DATA", "UNVERIFIED", "Agency / source", "Publication date", "Retrieved", "Last verified",
              "Version", "SHA-256", "Listed does not mean active", "example.invalid"):
        assert s in t, s
    assert ov.info.openLinks() is False and ov.info.openExternalLinks() is False


def test_o24_toggle_draws_and_persists(window):
    w, e, tmp = window
    w.tune(146_000_000)
    w.overlays.set_enabled("example-markers", True)
    assert {it.label for _, it in w.view.overlay_items} == {"EXAMPLE ch 1", "EXAMPLE ch 2"}
    assert json.loads((tmp / "cfg" / "ov.json").read_text()) == {"example-markers": True}
    w.overlays.set_enabled("example-markers", False)
    assert w.view.overlay_items == []


def test_o25_search_and_filter_ui(window):
    w, _, _ = window
    ov = w.overlays
    ov.search.setText("ch 2")
    assert ov.results.count() == 1 and "EXAMPLE ch 2" in ov.results.item(0).text()
    ov.search.setText("")
    ov.type_filter.setCurrentIndex(ov.type_filter.findData("allocation"))
    assert ov.results.count() == 2


def test_o26_tune_requires_confirmation_receive_only(window):
    w, e, _ = window
    ov = w.overlays
    start, mode = e.prefs.freq_hz, e.prefs.mode
    asked = []
    ov.confirm = lambda text: asked.append(text) or False
    ov.search.setText("ch 2")
    ov.results.setCurrentRow(0)
    assert ov.tune_selected() is False and e.prefs.freq_hz == start
    assert "Receive only" in asked[0] and "Listed does not mean active" in asked[0]
    ov.confirm = lambda text: True
    assert ov.tune_selected() is True
    assert e.prefs.freq_hz == 146_025_000 and w.tuner.hz == 146_025_000 and e.prefs.mode == mode


def test_o27_click_marker_offers_tune_plain_click_still_tunes(window, qtbot):
    from PySide6.QtCore import QPoint, Qt
    w, e, _ = window
    w.resize(1200, 800)
    w.show()
    qtbot.waitExposed(w)
    w.tune(146_000_000)
    w.overlays.set_enabled("example-markers", True)
    w._sync_overlays()
    v = w.view
    v.center_hz, v.rate = 146_000_000, e.prefs.sample_rate
    x = int(v.hz_to_x(146_025_000))
    asked = []
    w.overlays.confirm = lambda t: asked.append(t) or False
    qtbot.mouseClick(v, Qt.MouseButton.LeftButton, pos=QPoint(x, v.STRIP_Y0 + 5))
    assert asked and "146.025000 MHz" in asked[0] and e.prefs.freq_hz == 146_000_000      # declined: no change
    w.overlays.confirm = lambda t: True
    qtbot.mouseClick(v, Qt.MouseButton.LeftButton, pos=QPoint(x, v.STRIP_Y0 + 5))
    assert e.prefs.freq_hz == 146_025_000
    n = len(asked)
    v.center_hz = e.prefs.freq_hz
    x2 = int(v.width() * 0.3)
    expect = v.x_to_hz(x2)
    qtbot.mouseClick(v, Qt.MouseButton.LeftButton, pos=QPoint(x2, v.height() - 20))          # waterfall click
    assert len(asked) == n and e.prefs.freq_hz == expect                                    # direct tune, as before


def test_o28_out_of_range_confirmed_tune_still_rejected(window):
    w, e, _ = window
    start = e.prefs.freq_hz
    d = O.parse_dataset(good(id="example-far", items=[{**M, "freq_hz": 5_900_000_000}]), today=TODAY)
    w.overlays.confirm = lambda t: True
    w.overlays.offer_tune(d, d.items[0])
    assert e.prefs.freq_hz == start                       # the device range check still applies after confirmation


def test_o29_user_annotation_ui(window, qtbot):
    w, e, tmp = window
    ov = w.overlays
    w.tune(146_520_000)
    w._sync_overlays()
    ov.ask_text = lambda *a, **k: "my test note"
    ov.annotate_current()
    qtbot.waitUntil(lambda: not ov.loading and "user-annotations" in ov.set.datasets, timeout=10000)
    assert ov.set.enabled("user-annotations")
    assert any(it.label == "my test note" for _, it in w.view.overlay_items)
    ov.search.setText("my test note")
    ov.results.setCurrentRow(0)
    ov.ask_text = lambda *a, **k: "renamed note"
    ov.rename_selected()
    qtbot.waitUntil(lambda: not ov.loading and ov.set.datasets["user-annotations"].items[0].label == "renamed note",
                    timeout=10000)
    ov.search.setText("renamed")
    ov.results.setCurrentRow(0)
    ov.remove_selected()
    qtbot.waitUntil(lambda: not ov.loading and ov.set.datasets["user-annotations"].items == [], timeout=10000)
    # system datasets cannot be edited from the UI
    ov.search.setText("EXAMPLE ch 1")
    ov.results.setCurrentRow(0)
    msgs = []
    ov.message.connect(msgs.append)
    assert ov.remove_selected() is None and "your own annotations" in msgs[-1]


def test_o30_preserves_scanner_bookmarks_prefs(window):
    w, e, tmp = window
    from task_sdr.ui.scanner_panel import ScannerPanel
    assert isinstance(w.scan, ScannerPanel) and w.tabs.widget(0) is w.scan
    assert e.scanner is None and w.scan.scanner.state == "idle"
    w.overlays.set_enabled("example-markers", True)
    assert not (tmp / "p.json").exists() or "overlay" not in (tmp / "p.json").read_text()
    assert not any("overlay" in f for f in P.Prefs.__dataclass_fields__)


def test_o31_no_transmit_or_shell_in_overlay_code():
    for f in ("task_sdr/overlays.py", "task_sdr/ui/overlay_panel.py"):
        t = (SRC / f).read_text()
        for banned in ("subprocess", "os.system", "shell=True", "transmit(", "tx_", "Popen", "urlopen",
                       "requests", "QDesktopServices", "/etc/rain", "devices.json"):
            assert banned not in t, (f, banned)
