# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""AT-14 flood responsiveness and AT-13 silent-device handshake timeout (slow)."""

import time

import pytest
from PySide6.QtCore import QTimer

from task_mesh.app import build_application
from task_mesh.radio.discovery import Preflight
from tests.fakes.fake_ports import candidate
from tests.fakes.fake_provider import ProviderFactory

C = candidate("/dev/ttyUSB0", "/dev/serial/by-id/usb-A")


class Drift:
    def __init__(self, interval_ms=50):
        self.interval = interval_ms / 1000
        self.ticks = []
        self.t = QTimer()
        self.t.setInterval(interval_ms)
        self.t.timeout.connect(lambda: self.ticks.append(time.monotonic()))

    def start(self):
        self.t.start()

    def stop(self):
        self.t.stop()

    @property
    def max_drift(self):
        gaps = [b - a for a, b in zip(self.ticks, self.ticks[1:])]
        return max(gaps) - self.interval if gaps else float("inf")


def test_at14_flood_5000_packets_gui_stays_responsive(qtbot, xdg):
    factory = ProviderFactory()
    ctx = build_application(env=xdg, discover=lambda: [C], hotplug=None, console_log=False,
                            provider_factory=factory, path_exists=lambda p: True,
                            preflight_fn=lambda p: Preflight(True))
    try:
        qtbot.waitUntil(lambda: ctx.radio.last_snapshot.state == "CONNECTED", timeout=3000)
        flushes0 = ctx.nodes.ui_flushes
        drift = Drift()
        drift.start()
        t0 = time.monotonic()
        th = factory.last.flood(5000, 500.0)
        while th.is_alive():
            qtbot.wait(20)
        qtbot.wait(400)
        elapsed = time.monotonic() - t0
        drift.stop()
        assert drift.max_drift < 0.150, drift.max_drift
        rate = (ctx.nodes.ui_flushes - flushes0) / elapsed
        assert rate <= 4.0 + 1e-9, rate
        assert ctx.model.rowCount() >= 200
    finally:
        ctx.shutdown()


@pytest.mark.slow
@pytest.mark.timeout(120)
def test_at13_silent_device_times_out_gui_never_blocks(qtbot, xdg, tmp_path):
    from task_mesh.domain.models import Classification, PortCandidate
    from tests.fakes.pty_radio import PtyRadio

    radio = PtyRadio(tmp_path / "by-id", silent=True).plug()
    cand = PortCandidate(device=radio.slave_path, by_id=str(radio.link), vid=0x10C4, pid=0xEA60,
                         classification=Classification.LIKELY, open_path=str(radio.link))
    ctx = build_application(env=xdg, discover=lambda: [cand], hotplug=None, console_log=False)
    drift = Drift()
    try:
        qtbot.waitUntil(lambda: ctx.radio.last_snapshot.state == "CONNECTING", timeout=3000)
        drift.start()
        t0 = time.monotonic()
        qtbot.waitUntil(lambda: ctx.radio.last_snapshot.state == "BACKOFF", timeout=50000)
        took = time.monotonic() - t0
        drift.stop()
        assert 25 <= took <= 46, took
        assert ctx.radio.last_snapshot.error_code == "HANDSHAKE_TIMEOUT"
        assert drift.max_drift < 0.150, drift.max_drift
    finally:
        ctx.shutdown()
        radio.unplug()
