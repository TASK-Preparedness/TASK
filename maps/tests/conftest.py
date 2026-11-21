# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""task-maps tests: offscreen Qt, isolated HOME/XDG, local fixtures only.

Any IPv4/IPv6 connection that is not to a loopback test server started by the test itself, and
any non-local name resolution, fails the test: no test talks to a public tile server."""

import os
import socket
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

MAPS = Path(__file__).resolve().parents[1]
REPO = MAPS.parent
# repo root + tests/ only so the GPS "Core path" test can start a real rain-core (tests/p2fixtures.py)
for p in (str(MAPS), str(MAPS / "tests"), str(REPO), str(REPO / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

import mapfix  # noqa: E402

NETWORK_ATTEMPTS = []
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _guard(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        if address[0] in ("127.0.0.1", "::1") and address[1] in mapfix.LOCAL_ALLOWED_PORTS:
            return
        NETWORK_ATTEMPTS.append(address)
        raise AssertionError(f"network connection attempted: {address!r}")


def _connect(self, address):
    _guard(self, address)
    return _orig_connect(self, address)


def _connect_ex(self, address):
    _guard(self, address)
    return _orig_connect_ex(self, address)


def _getaddrinfo(host, *a, **k):
    if host not in (None, "localhost", "127.0.0.1", "::1"):
        NETWORK_ATTEMPTS.append(host)
        raise AssertionError(f"name resolution attempted: {host!r}")
    return _orig_getaddrinfo(host, *a, **k)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for k, v in {"HOME": home, "XDG_CONFIG_HOME": home / ".config", "XDG_DATA_HOME": home / ".local/share",
                 "XDG_STATE_HOME": home / ".local/state", "XDG_CACHE_HOME": home / ".cache"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("TASK_MAPS_SOURCES_DIR", raising=False)
    yield home
    assert not NETWORK_ATTEMPTS, f"network attempts: {NETWORK_ATTEMPTS}"


@pytest.fixture
def tile_server():
    srv = mapfix.TileServer()
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def fake_gpsd():
    srv = mapfix.FakeGpsd()
    srv.start()
    yield srv
    srv.stop()


try:   # real rain-core test fixture from the monorepo (absent in the standalone task-maps source tarball)
    from p2fixtures import p2env  # noqa: E402,F401
except ImportError:   # pragma: no cover
    @pytest.fixture
    def p2env():
        pytest.skip("rain-core test fixtures (repo tests/p2fixtures.py) not available")
