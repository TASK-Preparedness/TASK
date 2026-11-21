# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Run the real app offscreen at 1024x600 against a pty fake radio (real meshtastic library) and
save screenshots of the CONNECTED (with nodes) and DISCONNECTED states.

Usage: python3 tools/screenshot_demo.py [OUTPUT_DIR]   (default docs/screenshots)
All data shown is synthetic test data from tests/fakes/pty_radio.py, generated on a pseudo-terminal.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from meshtastic.protobuf import mesh_pb2  # noqa: E402
from task_mesh.app import build_application  # noqa: E402
from task_mesh.domain.models import Classification, PortCandidate  # noqa: E402
from task_mesh.radio.hotplug import PollingHotplugWatcher  # noqa: E402
from tests.fakes.pty_radio import MY, OTHER, PtyRadio, default_nodes  # noqa: E402


def extra_nodes():
    def hiker(ni):  # name + position, no battery, no hops
        ni.num = 0x2A3B4C5D
        ni.user.id = "!2a3b4c5d"
        ni.user.long_name = "Trail Hiker"
        ni.user.short_name = "HIKE"
        ni.user.hw_model = mesh_pb2.HardwareModel.TBEAM
        ni.position.latitude_i = 399876543
        ni.position.longitude_i = -1052345678
        ni.last_heard = int(time.time()) - 420

    def truck(ni):  # battery + snr only, no position
        ni.num = 0x0BADCAFE
        ni.user.id = "!0badcafe"
        ni.user.long_name = "Supply Truck"
        ni.user.short_name = "TRK"
        ni.user.hw_model = mesh_pb2.HardwareModel.HELTEC_V3
        ni.device_metrics.battery_level = 42
        ni.snr = -7.5
        ni.last_heard = int(time.time()) - 1800
        ni.hops_away = 1

    return default_nodes() + [hiker, truck]


def pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def wait_state(app, ctx, states, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(app, 0.1)
        if ctx.radio.last_snapshot.state in states:
            return True
    return False


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="task-demo-"))
    env = {"HOME": str(tmp / "home"), "XDG_CONFIG_HOME": str(tmp / "config"), "XDG_STATE_HOME": str(tmp / "state"),
           "XDG_DATA_HOME": str(tmp / "data"), "XDG_CACHE_HOME": str(tmp / "cache")}
    radio = PtyRadio(tmp / "by-id", nodes=extra_nodes())
    radio.plug()

    def discover():
        if not radio.link.exists():
            return []
        return [PortCandidate(device=radio.slave_path, by_id=str(radio.link), vid=0x10C4, pid=0xEA60,
                              serial_number="0001", manufacturer="Silicon Labs",
                              product="CP2102 USB to UART Bridge Controller",
                              classification=Classification.LIKELY, open_path=str(radio.link))]

    app = QApplication.instance() or QApplication(["task-mesh"])
    watcher = PollingHotplugWatcher(lambda: (radio.link.exists(),), interval_ms=500)
    ctx = build_application(env=env, discover=discover, hotplug=watcher, console_log=False)
    ctx.window.resize(1024, 600)
    ctx.window.show()
    if not wait_state(app, ctx, {"CONNECTED"}, 40):
        print("did not connect:", ctx.radio.last_snapshot, file=sys.stderr)
        return 1
    now = int(time.time())
    radio.send_position(OTHER, 401299999, -1051200000, rx_time=now - 5, snr=-3.5, rssi=-97, hop_start=3, hop_limit=1)
    radio.send_telemetry(MY, 101, 4.95, rx_time=now - 2, snr=9.0, rssi=-31)
    radio.send_telemetry(0x0BADCAFE, 41, 3.71, rx_time=now - 60, snr=-8.0, rssi=-118)
    pump(app, 1.5)
    ctx.window.grab().save(str(out / "connected.png"))
    print("saved", out / "connected.png", "state", ctx.radio.last_snapshot.state, "rows", ctx.model.rowCount())
    # 11 columns do not fit 1024 px: show the right-hand columns (Battery, Latitude, Longitude) too.
    bar = ctx.window.table.horizontalScrollBar()
    bar.setValue(bar.maximum())
    pump(app, 0.5)
    ctx.window.grab().save(str(out / "connected-columns-right.png"))
    bar.setValue(0)
    print("saved", out / "connected-columns-right.png")
    radio.unplug()
    if not wait_state(app, ctx, {"BACKOFF", "NO_DEVICE"}, 10):
        print("did not disconnect:", ctx.radio.last_snapshot, file=sys.stderr)
        return 1
    pump(app, 2.5)
    ctx.window.grab().save(str(out / "disconnected.png"))
    print("saved", out / "disconnected.png", "state", ctx.radio.last_snapshot.state)
    ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
