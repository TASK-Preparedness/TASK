# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import configparser
import importlib.util
import stat
import tomllib
from pathlib import Path

import pytest

MAPS = Path(__file__).resolve().parents[1]
LAUNCHER_MANIFEST = MAPS.parent / "launcher" / "task_launcher" / "data" / "apps.d" / "020-maps.toml"


def _build_mod():
    spec = importlib.util.spec_from_file_location("build_deb", MAPS / "packaging" / "build_deb.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_stage_layout(tmp_path):
    b = _build_mod()
    root = tmp_path / "root"
    root.mkdir()
    b.stage(root)
    wrapper = root / "usr/bin/task-maps"
    assert stat.S_IMODE(wrapper.stat().st_mode) == 0o755
    assert '"/usr/share/task-maps"' in wrapper.read_text() and wrapper.read_text().startswith("#!/usr/bin/python3")
    assert (root / "usr/share/task-maps/task_maps/app.py").is_file()
    assert sorted(p.name for p in (root / "usr/share/task-maps/sources.d").iterdir()) == [
        "010-usgs-topo.toml", "020-usgs-imagery.toml", "900-osm-standard-refused.toml"]
    assert not (root / "usr/share/task-maps/task_maps/data").exists()   # no empty dir; sources live in sources.d
    assert not list(root.rglob("__pycache__"))
    for f in ("usr/share/applications/task-maps.desktop", "usr/share/icons/hicolor/scalable/apps/task-maps.svg",
              "usr/share/man/man1/task-maps.1.gz", "usr/share/doc/task-maps/changelog.gz",
              "usr/share/doc/task-maps/copyright", "usr/share/doc/task-maps/SOURCES-POLICY.md",
              "usr/share/doc/task-maps/examples/local-tile-server.toml",
              "usr/share/doc/task-maps/docs/ACCEPTANCE-PI.md"):
        assert (root / f).is_file(), f
    assert not (root / "DEBIAN").exists() or not any((root / "DEBIAN").glob("*inst*"))   # no maintainer scripts
    assert "python3-pyside6.qtwidgets" in b.DEPENDS and "gpsd" in b.RECOMMENDS and "gpsd" not in b.DEPENDS
    assert "webengine" not in b.DEPENDS.lower() and "qtlocation" not in b.DEPENDS.lower()


def test_desktop_entry():
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(MAPS / "share/applications/task-maps.desktop")
    e = cp["Desktop Entry"]
    assert e["Exec"] == "task-maps" and e["Icon"] == "task-maps" and e["Type"] == "Application"
    assert e["Name"] == "T.A.S.K. Maps & GPS" and e["Terminal"] == "false"


def test_launcher_tile_prefers_task_maps():
    if not LAUNCHER_MANIFEST.exists():
        pytest.skip("launcher sources not present")
    m = tomllib.loads(LAUNCHER_MANIFEST.read_text())
    assert m["id"] == "task.maps"          # 0.3.0 launcher tile ids (rain.maps migrated)
    assert m["launch"]["exec"] == ["/usr/bin/task-maps"]
    assert m["launch"]["exec_alternatives"] == [["/usr/bin/foxtrotgps"]]
    assert m["launch"]["labels"]["/usr/bin/task-maps"] == "T.A.S.K. Maps"


def test_spdx_headers():
    for f in list((MAPS / "task_maps").rglob("*.py")) + list((MAPS / "tests").glob("*.py")) + \
            list((MAPS / "task_maps/data/sources.d").glob("*.toml")) + [MAPS / "packaging/task-maps",
                                                                        MAPS / "packaging/build_deb.py"]:
        head = f.read_text()[:400]
        assert "SPDX-License-Identifier: GPL-3.0-or-later" in head and "2026 Joshua Sturtz" in head, f
