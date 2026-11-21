# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GPS: gpsd JSON client against a loopback fake gpsd; rain-core capability via a real test Core."""

import ast
import time
from pathlib import Path

import pytest

import mapfix
from mapfix import SKY, TPV_FIX, TPV_NOFIX, FakeCore
from task_maps import core, gpsd
from task_maps.gpsd import GpsdClient, GpsState, apply_report

SRC = Path(__file__).resolve().parents[1] / "task_maps"


def wait(pred, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_apply_report_fields():
    st = GpsState()
    st = apply_report(st, {"class": "VERSION", "release": "3.25"}, 1.0)
    st = apply_report(st, TPV_FIX, 2.0)
    st = apply_report(st, SKY, 2.1)
    assert st.gpsd_version == "3.25" and st.mode == 3 and st.has_fix
    assert (st.lat, st.lon, st.alt, st.speed, st.track) == (47.6062, -122.3321, 52.1, 1.5, 90.0)
    assert (st.eph, st.epx, st.epy) == (4.2, 3.1, 3.9) and st.accuracy_m() == 4.2
    assert (st.sats_used, st.sats_visible, st.hdop) == (9, 14, 0.9)
    assert st.fix_fresh(3.0) and not st.fix_fresh(2.0 + gpsd.FIX_STALE_S + 0.1)
    st2 = apply_report(st, {"class": "SKY", "satellites": [{"PRN": 1, "used": True}, {"PRN": 2, "used": False},
                                                           {"PRN": 3, "used": True}]}, 3.0)
    assert (st2.sats_used, st2.sats_visible) == (2, 3)
    lost = apply_report(st, TPV_NOFIX, 4.0)
    assert lost.mode == 1 and not lost.has_fix and lost.lat == 47.6062      # last position kept, marked lost
    assert apply_report(st, {"class": "TPV", "mode": 3, "lat": "x", "lon": None}, 5).last_tpv == 2.0
    no_eph = GpsState(epx=3.0, epy=5.0)
    assert no_eph.accuracy_m() == 5.0 and GpsState().accuracy_m() is None


def test_fix_loss_and_reconnect(fake_gpsd):
    states = []
    fake_gpsd.on_watch = [TPV_FIX, SKY]
    c = GpsdClient(port=fake_gpsd.port, on_update=states.append, backoff=(0.1, 0.2))
    c.start()
    try:
        assert wait(lambda: c.state().has_fix and c.state().sats_used == 9)
        st = c.state()
        assert st.connection == "connected" and st.devices == ["/dev/ttyACM0"] and st.gpsd_version == "3.25"
        fake_gpsd.send(TPV_NOFIX)
        assert wait(lambda: c.state().mode == 1)
        assert c.state().fix_text() == "No fix"
        fake_gpsd.drop_clients()                          # gpsd restarted / socket lost
        assert wait(lambda: c.connects >= 2), "client did not reconnect"
        assert any(s.connection == "unavailable" for s in states)
        assert wait(lambda: c.state().connection == "connected" and c.state().has_fix)
    finally:
        c.stop()
    assert set(c.sent) == {gpsd.WATCH}                    # read-only: only ever ?WATCH
    assert all(r.startswith(b"?WATCH") for r in fake_gpsd.received)


def test_gpsd_absent_backoff():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    mapfix.LOCAL_ALLOWED_PORTS.add(port)
    states = []
    c = GpsdClient(port=port, on_update=states.append, backoff=(0.05, 0.1))
    c.start()
    try:
        assert wait(lambda: len(states) >= 3)
        assert all(x.connection == "unavailable" for x in states) and "no gpsd" in states[0].detail
    finally:
        c.stop()
        mapfix.LOCAL_ALLOWED_PORTS.discard(port)


def test_loopback_only():
    with pytest.raises(ValueError):
        GpsdClient(host="192.168.1.5")


def test_never_opens_serial_devices():
    """The app only talks to gpsd over TCP; no module opens /dev/tty*, pyserial or termios."""
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        assert "/dev/tty" not in text and "import serial" not in text and "termios" not in text, f
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "open" and node.args:
                a = node.args[0]
                assert not (isinstance(a, ast.Constant) and str(a.value).startswith("/dev/")), f


def test_stale_fix_marked_lost(fake_gpsd):
    t = [1000.0]
    fake_gpsd.on_watch = [TPV_FIX]
    c = GpsdClient(port=fake_gpsd.port, clock=lambda: t[0])
    c.start()
    try:
        assert wait(lambda: c.state().has_fix)
        assert c.state().fix_fresh(now=1001.0)
        assert c.state().fix_text(now=1000.0 + 30) == "Fix lost (last position shown)"
    finally:
        c.stop()


def test_core_capability_fake_socket(tmp_path):
    fc = FakeCore(tmp_path / "c.sock", "no-provider")
    try:
        st, text = core.gps_capability(str(tmp_path / "c.sock"))
        assert st == "no-provider" and "no Core provider" in text
        assert fc.requests[0]["method"] == "capability.list" and fc.requests[0]["v"] == 2
        assert "session" not in fc.requests[0]
    finally:
        fc.close()
    st, text = core.gps_capability(str(tmp_path / "missing.sock"))
    assert st is None and "not reachable" in text


def test_core_capability_real_rain_core(p2env):
    """The Core path against a real rain-core 0.2.x test instance (golden devices incl. the u-blox 7)."""
    c = p2env()
    st, text = core.gps_capability(c.config.socket)
    assert st in ("no-provider", "no-device", "available"), (st, text)
    # rain-core 0.2.1 registers no GPS providers: positions must come from gpsd
    assert st != "available"
