# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from mapfix import make_mbtiles
from task_maps import __version__, app, layers, mbtiles, paths, settings

MAPS = Path(__file__).resolve().parents[1]


def test_offline_import_copy(tmp_path):
    src = make_mbtiles(tmp_path / "My Region (v2).mbtiles", zooms=(0, 1, 2))
    data = tmp_path / "data"
    dest = layers.import_mbtiles(src, data)
    assert dest.parent == data / "maps" / "imported" and dest.name == "My-Region-v2.mbtiles"
    assert not dest.is_symlink() and stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert mbtiles.check(dest, quick=False)[0]
    assert mbtiles.Reader(dest).count() == 21
    dest2 = layers.import_mbtiles(src, data)                  # never overwrites an existing import
    assert dest2.name == "My-Region-v2-2.mbtiles"
    found = layers.scan(data)
    assert [(lay.kind, lay.tiles, lay.minzoom, lay.maxzoom) for lay in found] == [("imported", 21, 0, 2)] * 2
    assert found[0].attribution == "Test fixture tiles"
    assert not list((data / "maps" / "imported").glob("*.part"))


def test_offline_import_wal_source_consistent(tmp_path):
    src = make_mbtiles(tmp_path / "wal.mbtiles", zooms=(0, 1))
    con = sqlite3.connect(src)                   # keep uncheckpointed rows in the -wal file
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("INSERT INTO metadata VALUES ('extra', 'in-wal')")
    con.commit()
    dest = layers.import_mbtiles(src, tmp_path / "d")
    con.close()
    assert mbtiles.Reader(dest).metadata()["extra"] == "in-wal"


def test_offline_import_link_and_reject(tmp_path):
    src = make_mbtiles(tmp_path / "big.mbtiles", zooms=(0,))
    dest = layers.import_mbtiles(src, tmp_path / "d", link=True)
    assert dest.is_symlink() and dest.resolve() == src.resolve()
    junk = tmp_path / "junk.mbtiles"
    junk.write_bytes(b"\0" * 5000)
    with pytest.raises(ValueError, match="junk.mbtiles"):
        layers.import_mbtiles(junk, tmp_path / "d")
    vec = tmp_path / "vec.mbtiles"
    mbtiles.create(vec, {"name": "v", "format": "pbf"})
    with pytest.raises(ValueError, match="raster"):
        layers.import_mbtiles(vec, tmp_path / "d")


def test_layer_attribution_html_stripped(tmp_path):
    p = make_mbtiles(tmp_path / "maps" / "x.mbtiles", zooms=(0,),
                     metadata={"attribution": '<a href="https://x">&copy; Someone</a>', "bounds": "-10,-5,10,5"})
    lay = layers.describe(p, "downloaded")
    assert lay.attribution == "© Someone" and lay.bounds == (-10.0, -5.0, 10.0, 5.0)


def test_settings_defaults_roundtrip_and_corrupt(isolated_env):
    s = settings.load()
    assert s.resolved_data_dir() == paths.default_data_dir()
    assert str(paths.default_data_dir()).endswith(".local/share/task-maps")
    s.coord_format = "dms"
    s.data_dir = "/media/nvme/maps"
    settings.save(s)
    s2 = settings.load()
    assert s2.coord_format == "dms" and str(s2.resolved_data_dir()) == "/media/nvme/maps"
    f = paths.config_dir() / "settings.json"
    f.write_text("{broken")
    s3 = settings.load()
    assert s3.coord_format == "decimal" and s3.load_error
    assert f.read_text() == "{broken"                        # not overwritten on load
    f.write_text(json.dumps({"schema": 1, "cache_tiles": 10 ** 9, "view": [999, 999, 99]}))
    s4 = settings.load()
    assert s4.cache_tiles == 512 and s4.view == [85.0, 180.0, 20.0]


def test_paths_xdg(isolated_env, monkeypatch):
    assert paths.config_dir() == isolated_env / ".config" / "task-maps"
    assert paths.user_sources_dir() == isolated_env / ".config" / "task-maps" / "sources.d"
    monkeypatch.setenv("XDG_DATA_HOME", "/srv/data")
    assert paths.default_data_dir() == Path("/srv/data/task-maps")


def _run(*args, **kw):
    env = dict(os.environ, PYTHONPATH=str(MAPS))
    return subprocess.run([sys.executable, "-m", "task_maps", *args], capture_output=True, text=True, env=env,
                          timeout=60, **kw)


def test_version_flag():
    r = _run("--version")
    assert r.returncode == 0 and r.stdout.strip() == f"task-maps {__version__}"


def test_refuses_root(monkeypatch, capsys):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert app.main([]) == 2
    assert "must not run as root" in capsys.readouterr().err


def test_relative_data_dir_refused(capsys):
    assert app.main(["--data-dir", "rel/path"]) == 2


def test_single_instance_lock(tmp_path):
    lock = tmp_path / "instance.lock"
    a = app.acquire_lock(lock)
    assert a is not None
    code = ("import sys; sys.path.insert(0, %r); from task_maps import app; "
            "print(app.acquire_lock(%r) is None)" % (str(MAPS), str(lock)))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert r.stdout.strip() == "True"                         # a second instance is refused
    a.close()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert r.stdout.strip() == "False"


def test_no_shell_no_webengine_no_root_writes():
    for f in (MAPS / "task_maps").rglob("*.py"):
        t = f.read_text()
        for bad in ("shell=True", "os.system", "os.popen", "QtWebEngine", "QWebEngine", "/etc/rain",
                    "devices.json", "subprocess"):
            assert bad not in t, (f, bad)
