# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from task_resources import viewer  # noqa: E402

WEB, WEB_WHY = viewer.webengine_available()
if WEB:
    from task_resources.viewer.web import register_schemes
    register_schemes()      # before any QApplication exists


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for k, sub in (("HOME", ""), ("XDG_DATA_HOME", ".local/share"), ("XDG_CONFIG_HOME", ".config"),
                   ("XDG_CACHE_HOME", ".cache")):
        monkeypatch.setenv(k, str(home / sub) if sub else str(home))
    return home


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["test"])
    yield app


def wait_until(app, cond, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


@pytest.fixture
def settings(tmp_path):
    from task_resources.settings import Settings
    s = Settings()
    s.scan_dirs = [str(tmp_path / "lib")]
    s.library_xml = [str(tmp_path / "lib/library.xml")]
    s.kiwix_desktop_dir = str(tmp_path / "home/.local/share/kiwix-desktop")
    s.managed_root = str(tmp_path / "managed")
    s.free_space_reserve_mb = 0
    (tmp_path / "lib").mkdir(exist_ok=True)
    return s


@pytest.fixture
def library(settings, tmp_path):
    from task_resources.library import Library
    lib = Library(settings, tmp_path / "data/index.sqlite")
    yield lib
    lib.close()


@pytest.fixture
def zim(tmp_path):
    import zimfactory
    (tmp_path / "lib").mkdir(exist_ok=True)
    return zimfactory.make_zim(tmp_path / "lib/Field Manual.zim")


def register(library, path, **kw):
    from task_resources import discovery
    rep = discovery.Report()
    rid = discovery.register(library.index, path, "import", rep, **kw)
    assert rid is not None, rep.errors
    return rid
