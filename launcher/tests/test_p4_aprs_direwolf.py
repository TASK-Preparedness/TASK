# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A: KISS / AX.25 / APRS decoding (receive only) and Direwolf status/config parsing."""

import inspect
import re
import threading
from pathlib import Path

import pytest

from p4helpers import DATA, FakeTnc, ax25_ui, kiss
from task_launcher.services import aprs, direwolf, probe
from task_launcher.services.probe import ProcInfo, Unit


def test_kiss_decoder_escapes_chunks_and_non_data():
    payload = b"A\xc0B\xdbC"
    frame = kiss(payload, port=1)
    dec = aprs.KissDecoder()
    out = []
    for i in range(len(frame)):                       # byte by byte
        out += dec.feed(frame[i:i + 1])
    assert out == [(1, payload)]
    # command frames (TXDELAY etc.) are ignored; bad escape dropped; empty frames ignored
    assert dec.feed(b"\xc0\x01\x20\xc0") == []
    assert dec.feed(b"\xc0\x00AB\xdbX\xc0") == []
    assert dec.feed(b"\xc0\xc0\xc0") == []


def test_kiss_oversize_frame_dropped():
    dec = aprs.KissDecoder()
    assert dec.feed(b"\xc0\x00" + b"x" * (aprs.MAX_FRAME + 10) + b"\xc0") == []
    assert dec.dropped == 1
    assert dec.feed(kiss(ax25_ui("N0CALL", "APRS", ">ok"))) != []


def test_ax25_header_and_path():
    f = aprs.decode_ax25(ax25_ui("N0CALL-9", "APRS", ">hi", ["WIDE1-1*", "WIDE2-1"]))
    assert f.is_ui and f.pid == 0xF0 and f.info == b">hi"
    assert f.header() == "N0CALL-9>APRS,WIDE1-1*,WIDE2-1"


@pytest.mark.parametrize("data", [b"", b"\x00" * 10, b"\x82" * 7 + b"\x83" + b"\x03", bytes(30)])
def test_ax25_rejects_garbage(data):
    with pytest.raises(aprs.AX25Error):
        aprs.decode_ax25(data)


def parse(info, dest="APRS", src="N0CALL-1"):
    return aprs.parse_aprs(aprs.decode_ax25(ax25_ui(src, dest, info)), now=0)


def test_aprs_uncompressed_position_and_weather():
    p = parse("!4903.50N/07201.75W-Test 001234")
    assert p.kind == "position" and abs(p.lat - 49.058333) < 1e-5 and abs(p.lon + 72.029167) < 1e-5
    assert p.symbol == "/-" and p.comment == "Test 001234"
    w = parse("@092345z4903.50N/07201.75W_220/004g005t077r000p000P000h50b09900")
    assert w.kind == "position" and w.weather["wind_dir_deg"] == 220 and w.weather["temp_f"] == 77
    assert w.weather["humidity_pct"] == 50 and w.weather["pressure_dpa"] == 9900


def test_aprs_compressed_position():
    p = parse("!/5L!!<*e7>7P[")
    assert abs(p.lat - 49.5) < 1e-4 and abs(p.lon + 72.75) < 1e-4


def test_aprs_message_status_object_item():
    m = parse(":N0CALL-2 :Hello there{001")
    assert m.kind == "message" and m.addressee == "N0CALL-2" and m.message == "Hello there"
    s = parse(">Monitoring")
    assert s.kind == "status" and s.comment == "Monitoring"
    o = parse(";LEADER   *092345z4903.50N/07201.75W>088/036")
    assert o.kind == "object" and o.name == "LEADER" and o.lat is not None
    i = parse(")AID #2!4903.50N/07201.75WA")
    assert i.kind == "item" and i.name == "AID #2" and i.lon is not None


def test_aprs_mic_e():
    p = parse("`(#fSbl>/Mic-E test", dest="S32UVT")
    assert p.kind == "position (Mic-E)"
    assert abs(p.lat - (33 + 25.64 / 60)) < 1e-4 and abs(p.lon + (112 + 7.74 / 60)) < 1e-4


def test_aprs_bad_position_reports_error_not_crash():
    p = parse("!49XX.50N/07201.75W-")
    assert p.error.startswith("could not decode")


def test_receive_only_socket_has_no_send_api():
    for name in ("send", "sendall", "sendto", "sendmsg", "write"):
        assert not hasattr(aprs.ReceiveOnlySocket, name)
    src = inspect.getsource(aprs)
    assert not re.search(r"\.(send|sendall|sendto|sendmsg)\(", src)


def test_monitor_decodes_and_never_writes(local_port):
    frames = [kiss(ax25_ui("N0CALL-7", "APRS", "!4903.50N/07201.75W-hello", ["WIDE1-1"])),
              kiss(ax25_ui("N0CALL-8", "APRS", ">status text")), b"\xc0\x00\x01\x02\xc0"]
    with FakeTnc(frames) as tnc:
        local_port(tnc.port)
        got, stop = [], threading.Event()

        def on(p):
            got.append(p)
            if len([x for x in got if not isinstance(x, str)]) >= 2 and any(
                    isinstance(x, str) and x.startswith("undecodable") for x in got):
                stop.set()

        reason = aprs.monitor(tnc.port, on, stop.is_set)
        assert reason == "stopped"
        tnc.client_closed.wait(5)
        assert bytes(tnc.received) == b""                  # receive only: not one byte sent
    pk = [x for x in got if not isinstance(x, str)]
    assert pk[0].source == "N0CALL-7" and pk[0].path == "WIDE1-1" and pk[0].kind == "position"
    assert pk[1].kind == "status"


def test_monitor_connect_failure_and_loopback_only():
    assert "could not connect" in aprs.monitor(1, lambda p: None, lambda: True,
                                               connect=lambda *a: (_ for _ in ()).throw(OSError("refused")))
    with pytest.raises(probe.NotLoopback):
        aprs.ReceiveOnlySocket(8001, host="192.0.2.1")


# ---------------------------------------------------------------- Direwolf

def test_direwolf_config_parse_redacts_passcode():
    c = direwolf.parse_config((DATA / "direwolf.conf").read_text(), "x")
    assert c.mycall == ["N0CALL-10"] and c.adevice == ["plughw:1,0"] and c.ptt == ["GPIO 25"]
    assert c.effective_kiss_ports == [8001] and c.effective_agw_port == 8000
    assert c.iglogin == "N0CALL-10 (passcode hidden)" and "12345" not in repr(c)
    assert c.beacons == 1 and c.digipeat == 1 and c.transmit_capable


def test_direwolf_config_defaults_and_disabled_ports():
    c = direwolf.parse_config("MYCALL N0CALL\n")
    assert c.effective_kiss_ports == [8001] and c.effective_agw_port == 8000 and not c.transmit_capable
    c = direwolf.parse_config("KISSPORT 0\nAGWPORT 0\n")
    assert c.effective_kiss_ports == [] and c.effective_agw_port is None


def test_direwolf_collect_running_with_config(tmp_path):
    conf = tmp_path / "dw.conf"
    conf.write_text("KISSPORT 8101\nAGWPORT 8100\n")
    probed = []
    st = direwolf.collect(home=tmp_path, binary_fn=lambda: "/usr/bin/direwolf",
                          procs_fn=lambda: [ProcInfo(4242, ["/usr/bin/direwolf", "-c", str(conf), "-t", "0"])],
                          units_fn=lambda: [Unit("direwolf.service", "active", "running")],
                          port_fn=lambda p: probed.append(p) or p == 8101)
    assert st.running and st.configs[0].path == str(conf)
    assert st.kiss_open == {8101: True} and st.agw_open == {8100: False}
    assert st.open_kiss_port() == 8101 and "KISS TCP 8101 open" in st.summary()
    assert sorted(probed) == [8100, 8101]


def test_direwolf_not_installed_probes_nothing(tmp_path):
    probed = []
    st = direwolf.collect(home=tmp_path, binary_fn=lambda: "", procs_fn=lambda: [], units_fn=lambda: [],
                          port_fn=lambda p: probed.append(p))
    assert st.summary() == "Direwolf not installed" and probed == []


def test_direwolf_installed_not_running_defaults(tmp_path):
    st = direwolf.collect(home=tmp_path, binary_fn=lambda: "/usr/bin/direwolf", procs_fn=lambda: [],
                          units_fn=lambda: [], port_fn=lambda p: False)
    assert not st.running and st.kiss_open == {8001: False} and "not running" in st.summary()


def test_no_direwolf_launch_code_anywhere():
    root = Path(direwolf.__file__).parents[1]
    for p in root.rglob("*.py"):
        text = p.read_text()
        assert not re.search(r"\[[^\]]*['\"]/usr/bin/direwolf['\"]", text) or p.name == "direwolf.py", p
    assert "Popen" not in Path(direwolf.__file__).read_text()


def test_weather_text_and_summary_without_kind():
    w = parse("@092345z4903.50N/07201.75W_220/004g005t077r000p000P000h50b09900")
    assert "weather: wind 220° 4 mph, gust 5 mph, 77 °F, humidity 50 %, 990.0 hPa" in w.summary()
    assert not w.summary().startswith("position")


def test_kiss_open_without_visible_process(tmp_path):
    st = direwolf.collect(home=tmp_path, binary_fn=lambda: "/usr/bin/direwolf", procs_fn=lambda: [],
                          units_fn=lambda: [], port_fn=lambda p: p == 8001)
    assert st.summary() == "KISS TCP 8001 open · Direwolf process not visible to this user"
