# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Simulated tests: loopback fake Direwolf only. No radio, no RF."""

import ast
import json
import time
from pathlib import Path

import pytest

from task_aprs import config, dwconf
from task_aprs.amateur import parse_path
from task_aprs.service import AprsService
from task_comms import aprs as codec
from task_comms.audit import AuditLog
from task_comms.status import read_status
from task_comms.txpolicy import AmateurConfig

from fake_direwolf import FakeAgw, FakeKiss

PKG = Path(__file__).resolve().parents[1] / "task_aprs"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def setup(tmp_path, agw_port=None, kiss_port=0, verified=True, ptt=True, tx=True, role="operator"):
    root = tmp_path / "conf"
    config.save_amateur(AmateurConfig(tx_enabled=tx, callsign="N0TST", attestation="I hold N0TST",
                                      attestation_date="2026-10-12"), root)
    config.save_profile(config.RadioProfile(id="test-radio", service="amateur", name="bench", verified=verified), root)
    text = (f"AGWPORT {agw_port or 0}\nKISSPORT {kiss_port}\nCHANNEL 0\nMYCALL N0TST\n"
            + ("PTT /dev/ttyUSB0 RTS\n" if ptt else ""))
    clock = Clock()
    svc = AprsService(session_role=lambda: role, conf_root=root, state_root=tmp_path / "state",
                      dw_conf=dwconf.parse(text), clock=clock)
    return svc, clock


def settle(agw, svc, n):
    assert wait(lambda: len(agw.frames) >= n)
    agw.drain()
    svc.tick()


def ack_frame(frm, to, mid, digi=None):
    path = [codec.Address(digi, 0, True)] if digi else []
    return codec.encode_ax25(codec.parse_callsign(frm), codec.Address("APRS", 0), path,
                             codec.ack_info(to, mid).encode())


@pytest.fixture
def agw():
    s = FakeAgw()
    yield s
    s.close()


def test_agw_send_states_and_ack(tmp_path, agw):
    svc, clock = setup(tmp_path, agw_port=agw.port)
    assert svc.connect() and svc.transport.name == "direwolf-agw"
    assert wait(lambda: "k" in agw.kinds)
    assert agw.frames == []                                    # nothing transmitted on start-up
    o, d = svc.amateur.send("message", addressee="N0DST", text="hello", retries=2)
    assert d.allowed and o.state == "submitted"
    assert wait(lambda: len(agw.frames) == 1)
    f = codec.decode_ax25(agw.frames[0][1])
    assert str(f.source) == "N0TST" and f.dest.call == "APZTSK"
    assert f.info.decode() == ":N0DST    :hello{" + o.msg_id
    svc.tick()
    assert svc.amateur.queued() and o.state == "submitted"
    card = read_status(svc.status.path)
    assert card["state"] == "queued" and card["indicators"] == ["QUEUED"] and "ON-AIR" not in json.dumps(card)
    settle(agw, svc, 1)
    assert o.state == "queue-progress" and "NOT proof of RF" in o.history[-1][2]
    agw.inject(codec.encode_ax25(codec.parse_callsign("N0TST"), codec.Address("APZTSK", 0),
                                 [codec.Address("DIGI", 0, True)], f.info))
    assert wait(lambda: o.state == "heard-digipeated")
    agw.inject(ack_frame("N0DST", "N0TST", o.msg_id))
    assert wait(lambda: o.state == "acked")
    clock.t += 1000
    svc.tick()
    assert len(agw.frames) == 1                                # retries stop on ack
    svc.close()


def test_retries_then_no_ack(tmp_path, agw):
    svc, clock = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    o, d = svc.amateur.send("message", addressee="N0DST", text="hi", retries=2)
    settle(agw, svc, 1)
    for step, n in ((30, 2), (90, 3)):
        clock.t = 1000 + step
        svc.tick()                                             # retry due -> sent
        settle(agw, svc, n)
    clock.t = 1000 + 90 + 121
    svc.tick()
    assert len(agw.frames) == 3                                # first + 2 user-chosen retries
    assert o.state == "no-ack"


def test_rej_and_cancel(tmp_path, agw):
    svc, clock = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    o, _ = svc.amateur.send("message", addressee="N0DST", text="one")
    settle(agw, svc, 1)
    agw.inject(codec.encode_ax25(codec.parse_callsign("N0DST"), codec.Address("APRS", 0), [],
                                 codec.ack_info("N0TST", o.msg_id, reject=True).encode()))
    assert wait(lambda: o.state == "rejected")
    o2, _ = svc.amateur.send("message", addressee="N0DST", text="two")
    settle(agw, svc, 2)
    svc.amateur.cancel(o2.local_id)
    clock.t += 500
    svc.tick()
    assert o2.state == "cancelled" and len(agw.frames) == 2


def test_queue_never_drains_fails(tmp_path, agw):
    svc, clock = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    o, _ = svc.amateur.send("message", addressee="N0DST", text="stuck")
    clock.t += 31
    svc.tick()
    assert o.state == "failed" and "30 s" in o.history[-1][2]
    clock.t += 1000
    svc.tick()
    assert len(agw.frames) == 1                                 # never retried silently


def test_one_in_flight_and_duplicate_guard(tmp_path, agw):
    svc, clock = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    svc.amateur.send("message", addressee="N0DST", text="x")
    o, d = svc.amateur.send("message", addressee="N0OTH", text="y")
    assert o is None and d.code == "busy"
    settle(agw, svc, 1)
    o, d = svc.amateur.send("message", addressee="N0DST", text="x")
    assert o is None and d.needs_confirmation
    o, d = svc.amateur.send("message", addressee="N0DST", text="x", confirmed=("duplicate",))
    assert d.allowed


@pytest.mark.parametrize("kw,code", [
    (dict(tx=False), "tx-disabled"), (dict(verified=False), "radio-unverified"),
    (dict(ptt=False), "no-ptt"), (dict(role=None), "no-session")])
def test_refusals_write_nothing(tmp_path, agw, kw, code):
    svc, _ = setup(tmp_path, agw_port=agw.port, **kw)
    svc.connect()
    o, d = svc.amateur.send("message", addressee="N0DST", text="hi")
    assert o is None and any(r.startswith(code) for r in d.reasons)
    time.sleep(0.1)
    assert agw.frames == []
    log = AuditLog(tmp_path / "state" / "audit-amateur.jsonl")
    assert log.verify()[0]
    rec = json.loads(log.path.read_text().splitlines()[-1])
    assert rec["action"] == "refused" and "hi" not in json.dumps(rec)


def test_bad_content(tmp_path, agw):
    svc, _ = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    o, d = svc.amateur.send("message", addressee="N0DST", text="x" * 68)
    assert o is None and d.code == "bad-content"
    with pytest.raises(ValueError):
        parse_path("WIDE1-1,WIDE2-1,WIDE3-1")


def test_position_now_and_beacon_floor(tmp_path, agw):
    svc, _ = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    o, d = svc.amateur.send("position", lat=40.0, lon=-77.5, comment="test")
    assert d.allowed
    settle(agw, svc, 1)
    svc.tick()
    assert codec.decode_ax25(agw.frames[0][1]).info.startswith(b"=4000.00N/07730.00W>")
    assert o.state == "complete"


def test_kiss_fallback_states(tmp_path):
    k = FakeKiss()
    try:
        svc, _ = setup(tmp_path, agw_port=None, kiss_port=k.port)
        assert svc.connect() and svc.transport.name == "direwolf-kiss"
        o, d = svc.amateur.send("message", addressee="N0DST", text="kiss")
        assert d.allowed and o.state == "submitted" and not svc.amateur.queued()
        assert wait(lambda: k.frames)
        k.inject(ack_frame("N0DST", "N0TST", o.msg_id))
        assert wait(lambda: o.state == "acked")
        assert [h[1] for h in o.history] == ["submitted", "acked"]
    finally:
        k.close()


def test_rx_stations_feed_and_aprs_is_label(tmp_path, agw):
    svc, _ = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    pos = codec.encode_ax25(codec.parse_callsign("N0POS"), codec.Address("APRS", 0), [],
                            codec.position_info(40.5, -76.0).encode())
    third = codec.encode_ax25(codec.parse_callsign("N0IGT"), codec.Address("APRS", 0), [],
                              b"}N0NET>APRS,TCPIP,N0IGT*:" + codec.position_info(41.0, -75.0).encode())
    agw.inject(pos); agw.inject(third)
    assert wait(lambda: "N0NET" in svc.rx.stations and "N0POS" in svc.rx.stations)
    assert svc.rx.stations["N0POS"].via == "RF"
    assert svc.rx.stations["N0NET"].via == "via APRS-IS"
    from task_comms.feeds import read_feed
    _, ents = read_feed(svc.feed.path)
    assert {e["id"] for e in ents} == {"aprs:N0POS", "aprs:N0NET"}


def test_disconnect_reported(tmp_path, agw):
    svc, _ = setup(tmp_path, agw_port=agw.port)
    svc.connect()
    o, _ = svc.amateur.send("message", addressee="N0DST", text="z")
    agw.close()
    assert wait(lambda: svc.transport is None)
    svc.tick()
    assert o.state == "failed"
    assert read_status(svc.status.path)["state"] == "disconnected"


def test_non_loopback_refused():
    from task_aprs.agw import AgwClient
    with pytest.raises(ValueError):
        AgwClient(host="192.168.1.5")


def test_dwconf_channels():
    c = dwconf.parse("ACHANNELS 2\nCHANNEL 0\nMYCALL N0A\nPTT GPIO 25\nCHANNEL 1\nMYCALL N0B\nAGWPORT 0\nPBEACON x\n")
    assert c.channel(0).ptt and not c.channel(1).ptt and c.effective_agw_port is None
    w = c.warnings("N0A", 1)
    assert any("no PTT" in x for x in w) and any("beacon" in x for x in w)


def test_profiles_cannot_cross_services(tmp_path):
    with pytest.raises(ValueError):
        config.RadioProfile(id="x", service="gmrs", interface="DigiRig").validate()
    with pytest.raises(ValueError):
        config.RadioProfile(id="y", service="amateur", driver="simulated").validate()
    config.save_profile(config.RadioProfile(id="g1", service="gmrs", driver="simulated"), tmp_path)
    assert config.load_profiles("amateur", tmp_path) == []
    assert oct((tmp_path / "radios.d" / "g1.toml").stat().st_mode & 0o777) == "0o600"


def test_sources_never_launch_or_write_direwolf():
    for f in PKG.rglob("*.py"):
        src = f.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("system", "Popen", "run", "call"):
                pytest.fail(f"{f}: process launch")
            if isinstance(node, ast.keyword) and node.arg == "shell":
                pytest.fail(f"{f}: shell=")
        assert "/etc/rain" not in src and "devices.json" not in src
        assert "ON-AIR" not in src.replace("no ON-AIR", "")


def test_send_only_from_amateur_controller():
    """AST: send_raw is called only by AmateurTx._transmit (a policy-allowed request)."""
    calls = []
    for f in PKG.rglob("*.py"):
        tree = ast.parse(f.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("send_raw", "request_transmit"):
                        calls.append((f.name, fn.name))
    assert set(calls) == {("amateur.py", "_transmit"), ("service.py", "send")}
