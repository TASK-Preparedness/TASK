# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A: task-mesh detection, weather and medical honest status, readiness lines."""

import os
import time

from conftest import make_exec
from task_launcher.services import kiwix, medical, mesh, readiness, reference, weather
from task_launcher.services.probe import ProcInfo, file_age_text

DPKG = """Package: other
Status: install ok installed
Version: 1.0

Package: task-mesh
Status: install ok installed
Architecture: arm64
Version: 0.1.0-1

"""


def test_dpkg_version(tmp_path):
    p = tmp_path / "status"
    p.write_text(DPKG)
    assert mesh.dpkg_version("task-mesh", p) == "0.1.0-1" and mesh.dpkg_version("nope", p) == ""
    p.write_text(DPKG.replace("install ok installed\nArchitecture", "deinstall ok config-files\nArchitecture"))
    assert mesh.dpkg_version("task-mesh", p) == ""


def test_mesh_collect(tmp_path, safe_dir):
    exe = make_exec(safe_dir / "bin", "task-mesh")
    st = mesh.collect(candidates=(str(exe),), status_file=tmp_path / "none", ports_fn=lambda: ["usb-Silicon_Labs_CP2102"],
                      procs_fn=lambda: [ProcInfo(5, ["/usr/bin/python3", "-I", "-c", "from rain_mesh.app import main"])])
    assert st.executable == str(exe) and st.running and st.summary() == "task-mesh installed · running"
    st = mesh.collect(candidates=("/nonexistent/task-mesh",), status_file=tmp_path / "none", ports_fn=list,
                      procs_fn=list)
    assert st.summary().startswith("task-mesh not installed")


def test_weather_honest_without_data(tmp_path):
    st = weather.collect(ref_dirs=(), finder=lambda names: {})
    assert st.summary() == "No weather sources or local data · no forecast"
    st = weather.collect(ref_dirs=(), finder=lambda names: {"rtl_433": "/usr/bin/rtl_433"} if "rtl_433" in names else {})
    assert st.summary() == "1 weather decoder installed · no local data"


def test_weather_local_data_age(tmp_path):
    d = tmp_path / "wx"
    d.mkdir()
    old = d / "noaa19-2026.png"
    old.write_bytes(b"x")
    new = d / "sensors.jsonl"
    new.write_text("{}")
    now = time.time()
    os.utime(old, (now - 7200, now - 7200))
    os.utime(new, (now - 120, now - 120))
    (d / "ignore.bin").write_bytes(b"x")
    st = weather.collect(ref_dirs=[str(d), str(tmp_path / "missing")], finder=lambda n: {}, now=lambda: now)
    status, prods = st.dirs[0]
    assert [p.title for p in prods] == ["sensors.jsonl", "noaa19-2026.png"]
    assert st.summary(now) == "Local weather data · newest 2 min old · no forecast"
    assert st.dirs[1][0].detail == "folder missing"


def test_file_age_text():
    assert file_age_text(100, 130) == "30 s old" and file_age_text(0, 3 * 86400) == "3 days old"


def test_medical_discovery(tmp_path):
    ks = kiwix.KiwixStatus(endpoint=kiwix.Candidate(1, verified=True),
                           books=[kiwix.Book(name="mdwiki_en_all", title="mdwiki"),
                                  kiwix.Book(name="wikipedia_en_all", title="Wikipedia", tags="wikipedia"),
                                  kiwix.Book(name="x", title="Hesperian Health Guides")])
    mods = tmp_path / "modules"
    (mods / "en-medline_plus").mkdir(parents=True)
    (mods / "en-medline_plus" / "index.html").write_text("x")
    (mods / "en-scratch").mkdir()
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "TCCC.pdf").write_bytes(b"%PDF")
    (docs / "sub" / "burns.html").write_text("x")
    (docs / "notes.bin").write_bytes(b"x")
    st = medical.collect(ks, [str(docs), str(tmp_path / "gone")], module_dirs=(mods,))
    assert [b.name for b in st.books] == ["mdwiki_en_all", "x"]
    assert st.modules == [("en-medline_plus", str(mods / "en-medline_plus" / "index.html"))]
    assert sorted(os.path.basename(f) for f in st.documents[0][1]) == ["TCCC.pdf", "burns.html"]
    assert st.missing_dirs == [str(tmp_path / "gone")]
    assert st.summary() == "Reference: 2 Kiwix · 1 IIAB module · 2 documents"
    assert medical.collect(None, (), module_dirs=()).summary() == "No offline medical reference found"


def test_reference_toml(tmp_path):
    p = tmp_path / "reference.toml"
    p.write_text('[medical]\ndirs = ["/a", "relative", 3]\n')
    doc, err = reference.load(p)
    assert err == "" and reference.dirs("medical", doc) == ["/a"] and reference.dirs("weather", doc) == []
    p.write_text("[broken")
    assert reference.load(p)[1]
    assert reference.load(tmp_path / "none.toml") == ({}, "")


class FakeLink:
    def __init__(self, live=True, signed=False, devices=None, caps=None):
        self.live, self.signed_in, self.devices, self._caps = live, signed, devices, caps or {}

    def capability_status(self, name):
        return self._caps.get(name)


def test_sdr_readiness_only_claims_ready_when_seen():
    assert readiness.sdr_readiness(FakeLink(live=False)).text.startswith("RTL-SDR: unknown")
    r = readiness.sdr_readiness(FakeLink(caps={"radio.rx": "no-device"}))
    assert r.text == "RTL-SDR: sign in to check · Core radio.rx: no device assigned/connected" and r.level == "muted"
    dev = {"vid": "0bda", "pid": "2838", "connected": True}
    r = readiness.sdr_readiness(FakeLink(signed=True, devices={"devices": [dev]}))
    assert r.level == "ok" and "present" in r.text
    r = readiness.sdr_readiness(FakeLink(signed=True, devices={"devices": [dict(dev, connected=False)]}))
    assert r.level == "warn"
    r = readiness.sdr_readiness(FakeLink(signed=True, devices={"devices": [{"vid": "10c4", "pid": "ea60"}]}))
    assert r.text.startswith("No RTL-SDR")


def test_gps_and_mesh_readiness():
    r = readiness.gps_readiness(FakeLink(caps={"gps.position": "no-provider"}), True)
    assert r.text == "Core gps.position: device connected, no Core provider · gpsd :2947 reachable" and r.level == "ok"
    assert readiness.gps_readiness(FakeLink(live=False), None).text == "Core: not connected"
    pr = readiness.ProbeResults()
    assert pr.line("kiwix", FakeLink()).text == "checking…"
    pr.mesh = mesh.MeshStatus()
    assert pr.line("mesh", FakeLink(caps={"mesh.messaging": "no-device"})).text == \
        "no USB serial device · Core mesh: no device assigned/connected"
    pr.mesh = mesh.MeshStatus(serial_ports=["usb-Silicon_Labs_CP2102-if00-port0"])
    assert pr.line("mesh", FakeLink(live=False)).text == "1 USB serial device"


def test_sdr_conflict_flagged_from_proc():
    busy = readiness.sdr_busy(lambda: [ProcInfo(7, ["/usr/bin/sdrpp"]), ProcInfo(8, ["/usr/bin/rtl_433", "-F", "json"])])
    assert busy == ["rtl_433", "sdrpp"]
    dev = {"vid": "0bda", "pid": "2838", "connected": True}
    r = readiness.sdr_readiness(FakeLink(signed=True, devices={"devices": [dev]}), busy)
    assert r.text == "RTL-SDR 0bda:2838 present (task-core) · in use by rtl_433, sdrpp" and r.level == "warn"
    pr = readiness.ProbeResults()
    pr.sdr_busy = []
    assert pr.line("rtl-sdr", FakeLink(signed=True, devices={"devices": [dev]})).level == "ok"


def test_mesh_serial_conflict_with_meshtastic_cli(tmp_path, safe_dir):
    exe = make_exec(safe_dir / "bin", "task-mesh")
    procs = [ProcInfo(5, ["/usr/bin/python3", "/usr/bin/meshtastic", "--info"]),
             ProcInfo(6, ["/usr/bin/python3", "-I", "-c", "from rain_mesh.app import main"])]
    st = mesh.collect(candidates=(str(exe),), status_file=tmp_path / "none", ports_fn=lambda: ["usb-x"],
                      procs_fn=lambda: procs)
    assert [p.pid for p in st.running] == [6] and [p.pid for p in st.cli_running] == [5]
    r = readiness.mesh_readiness(FakeLink(live=False), st)
    assert r.text.startswith("meshtastic CLI running — serial port conflict") and r.level == "warn"
