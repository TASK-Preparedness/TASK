# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A offscreen renders (skipped unless TL_RENDER_DIR is set). Every image is stamped TESTDATA.

"Simulated Pi app set" renders use fake executables standing in for foxtrotgps, sdrpp and task-mesh
(those programs are not installed on the build box) and a fake local kiwix-serve / KISS TNC."""

import os
import time
from pathlib import Path

import pytest

from conftest import make_exec
from p4helpers import FakeKiwix, FakeTnc, ax25_ui, kiss
from test_p4_ui import kiwix_status, probe_result
from test_render import OUT, stamp
from task_launcher.registry.discovery import BUNDLED_APPS_DIR
from task_launcher.registry.registry import Registry
from task_launcher.registry.tilestore import TileStore
from task_launcher.services import direwolf, medical, weather

pytestmark = pytest.mark.skipif(not OUT, reason="renders only when TL_RENDER_DIR is set")
SIZES = [(1920, 1080), (1024, 600)]
PACKETS = [("N0CALL-9", "!4903.50N/07201.75W>TESTDATA mobile", ["WIDE1-1*", "WIDE2-1"]),
           ("N0CALL-10", ">TESTDATA digipeater status", []),
           ("N0CALL-3", "@092345z4903.50N/07201.75W_220/004g005t077r000p000P000h50b09900", ["WIDE2-1"]),
           ("N0CALL-7", ":N0CALL-9 :TESTDATA message{01", []),
           ("N0CALL-5", ";TESTOBJ  *092345z4903.50N/07201.75W>088/036", [])]


def shot(widget, name, label):
    Path(OUT).mkdir(parents=True, exist_ok=True)
    stamp(widget.grab().toImage(), label).save(str(Path(OUT) / name))


def simulated_registry(tmp_path, safe_dir):
    d = tmp_path / "apps"
    d.mkdir()
    fake = {p: str(make_exec(safe_dir / "fake", os.path.basename(p))) for p in
            ("/usr/bin/foxtrotgps", "/usr/bin/sdrpp", "/usr/bin/task-mesh", "/usr/bin/gpsmon", "/usr/bin/cgps")}
    for f in BUNDLED_APPS_DIR.glob("*.toml"):
        text = f.read_text()
        for a, b in fake.items():
            text = text.replace(f'"{a}"', f'"{b}"')
        (d / f.name).write_text(text)
    return Registry(manifest_dirs=[(d, "package")], desktop_dirs=[], store=TileStore(tmp_path / "tiles.json"))


def wx_status(tmp_path):
    d = tmp_path / "wx-testdata"
    d.mkdir()
    now = time.time()
    for name, age in (("TESTDATA-noaa19-pass.png", 5400), ("TESTDATA-rtl433-sensors.jsonl", 600)):
        (d / name).write_bytes(b"x")
        os.utime(d / name, (now - age, now - age))
    return weather.collect([str(d)], finder=lambda names: {n: f"/usr/bin/{n}" for n in names if n == "rtl_433"})


@pytest.mark.parametrize("size", SIZES)
def test_render_p4_launcher(qtbot, launcher, p2env, tmp_path, safe_dir, local_port, size):
    core = p2env()
    with FakeKiwix("/kiwix/") as fk, FakeTnc([]) as tnc:
        local_port(fk.port)
        dw = direwolf.DirewolfStatus(binary="/usr/bin/direwolf", kiss_open={tnc.port: True}, agw_open={8000: True})
        dw.processes = [type("P", (), {"pid": 1234, "argv": ["/usr/bin/direwolf"]})()]
        w = launcher(core.config.socket, size=size, registry=simulated_registry(tmp_path, safe_dir))
        qtbot.waitUntil(lambda: w.link.live and w.link.health is not None, timeout=5000)
        res = probe_result(kiwix_status(fk.port), dw)
        res["weather"] = wx_status(tmp_path)
        res["gpsd_open"] = True
        res["medical"] = medical.collect(res["kiwix"], (), module_dirs=())
        res["mesh"].serial_ports = ["usb-Silicon_Labs_CP2102_TESTDATA-if00-port0"]
        w._on_probes(res)
        qtbot.wait(100)
        shot(w, f"p4-launcher-statuses-{size[0]}x{size[1]}.png",
             "simulated Pi apps, fake kiwix/TNC" if size[0] < 1400 else
             "Phase 4A statuses; simulated Pi app set (fake foxtrotgps/sdrpp/task-mesh), fake kiwix/TNC, test task-core")
    core.close()


@pytest.mark.parametrize("size", SIZES)
def test_render_p4_launcher_build_box(qtbot, launcher, size):
    w = launcher(size=size, start=False)
    w._on_probes(probe_result())
    qtbot.wait(50)
    shot(w, f"p4-launcher-buildbox-{size[0]}x{size[1]}.png",
         "build box, no Pi apps, no Core" if size[0] < 1400 else
         "Phase 4A on the build box: Pi apps not installed here, no Core, honest Unavailable")


@pytest.mark.parametrize("size", SIZES)
def test_render_p4_windows(qtbot, launcher, tmp_path, local_port, size):
    frames = [kiss(ax25_ui(s, "APRS", i, p)) for s, i, p in PACKETS]
    with FakeKiwix("/kiwix/") as fk, FakeTnc(frames) as tnc:
        local_port(fk.port)
        local_port(tnc.port)
        dw = direwolf.DirewolfStatus(binary="/usr/bin/direwolf", kiss_open={tnc.port: True}, agw_open={8000: True})
        dw.processes = [type("P", (), {"pid": 1234, "argv": ["/usr/bin/direwolf"]})()]
        dw.configs = [direwolf.parse_config((Path(__file__).parent / "p4data/direwolf.conf").read_text(),
                                            "/home/op/direwolf.conf (TESTDATA)")]
        w = launcher(start=False, size=(1024, 600))
        res = probe_result(kiwix_status(fk.port), dw)
        res["weather"] = wx_status(tmp_path)
        res["medical"] = medical.collect(res["kiwix"], (), module_dirs=())
        w._on_probes(res)
        tag = f"{size[0]}x{size[1]}"

        lib = w.open_builtin("library")
        lib.resize(*size)
        lib.books.setCurrentRow(0)
        lib.query.setText("water")
        lib.do_search()
        qtbot.waitUntil(lambda: lib.results.count() == 2 and "Water" in lib.results.item(0).text(), timeout=5000)
        lib._hit_activated(lib.results.item(0))
        qtbot.waitUntil(lambda: "TESTDATA article" in lib.view.toPlainText(), timeout=5000)
        qtbot.wait(50)
        shot(lib, f"p4-library-{tag}.png", "Library window, fake local kiwix-serve")

        radio = w.open_builtin("radio")
        radio.resize(*size)
        radio.start_monitor()
        qtbot.waitUntil(lambda: radio.table.rowCount() == len(PACKETS), timeout=5000)
        qtbot.wait(50)
        shot(radio, f"p4-radio-aprs-{tag}.png", "Radio / APRS, receive-only monitor on a fake KISS TNC")
        radio.stop_monitor()
        qtbot.waitUntil(lambda: radio.monitor is None, timeout=5000)

        wx = w.open_builtin("weather")
        wx.resize(*size)
        qtbot.wait(50)
        shot(wx, f"p4-weather-{tag}.png", "Weather status, TESTDATA folder")

        med = w.open_builtin("medical")
        med.resize(*size)
        qtbot.wait(50)
        shot(med, f"p4-medical-{tag}.png", "Medical reference, fake kiwix catalog")
