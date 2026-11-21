# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""python3-task-comms unit tests (automated, no hardware)."""

import json
import os
import socket
import stat
import threading
from pathlib import Path

import pytest

from task_comms import aprs, audit, core, events, feeds, ownership, status, txpolicy
from task_comms.auth import SessionGate
from task_comms.bridge import Bridge

PKG = Path(__file__).resolve().parents[1] / "task_comms"


def test_c01_status_roundtrip_and_stale(tmp_path):
    t = [1000.0]
    w = status.StatusWriter("task-aprs", tmp_path, clock=lambda: t[0])
    w.write("queued", device="Direwolf ch0", summary="1 queued", counts={"heard": 3}, indicators=["QUEUED"])
    assert stat.S_IMODE((tmp_path / "task-aprs.json").stat().st_mode) == 0o600
    doc = status.read_status(tmp_path / "task-aprs.json", clock=lambda: t[0])
    assert doc["state"] == "queued" and not doc["_stale"] and not doc["_dead"]
    t[0] += 11
    assert status.read_status(tmp_path / "task-aprs.json", clock=lambda: t[0])["_stale"]
    with pytest.raises(ValueError):
        w.write("connected", counts={"message_text": 1})
    with pytest.raises(ValueError):
        w.write("ON-AIR")
    (tmp_path / "bad.json").write_text("{nope")
    assert status.read_all(tmp_path)["bad"] == {"_invalid": "not JSON"}


def test_c02_feeds_roundtrip_readonly_and_corrupt(tmp_path):
    fw = feeds.FeedWriter("task-aprs", tmp_path, clock=lambda: 50)
    fw.upsert(feeds.Entity("aprs:KD2ABC-9", "aprs", "KD2ABC-9", 40.1, -76.3, 40, "aprs-rf"))
    with pytest.raises(ValueError):
        fw.upsert(feeds.Entity("x", "aprs", "x", 91, 0, 1, "aprs-rf"))
    with pytest.raises(ValueError):
        fw.upsert(feeds.Entity("x", "aprs", "x", 0, 0, 1, "aprs-rf", kind="guessed"))
    updated, rows = feeds.read_feed(fw.path, clock=lambda: 100)
    assert updated == 50 and rows[0]["label"] == "KD2ABC-9" and rows[0]["stale"] is False
    assert stat.S_IMODE(fw.path.stat().st_mode) == 0o600
    fw.close()
    (tmp_path / "junk.sqlite").write_bytes(b"not a database at all" * 10)
    assert feeds.read_feed(tmp_path / "junk.sqlite") == (None, [])
    assert feeds.read_feed(tmp_path / "missing.sqlite") == (None, [])


def test_c03_audit_chain_detects_tamper(tmp_path):
    log = audit.AuditLog(tmp_path / "a/tx-audit.jsonl", clock=lambda: 1.0)
    for i in range(3):
        log.append(service="amateur", decision="refused", reason="tx-disabled", **audit.payload_digest(f"m{i}"))
    assert log.verify() == (True, 3, None)
    with pytest.raises(ValueError):
        log.append(text="secret message")
    lines = log.path.read_text().splitlines()
    rec = json.loads(lines[1]); rec["decision"] = "allowed"
    lines[1] = json.dumps(rec, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")
    ok, n, problem = log.verify()
    assert not ok and n == 1 and "line 2" in problem


def test_c04_event_redaction(tmp_path):
    ev = events.EventLog(tmp_path / "e/log.jsonl")
    rec = ev.log("connected", psk="AQ==", session_token="abc", note="key " + "ab" * 20)
    assert rec["psk"] == "[redacted]" and rec["session_token"] == "[redacted]" and "abab" not in rec["note"]


def test_c05_device_claim_exclusive(tmp_path):
    a = ownership.DeviceClaim("/dev/ttyUSB0", "task-mesh", tmp_path)
    b = ownership.DeviceClaim("/dev/ttyUSB0", "task-aprs", tmp_path)
    assert a.acquire() and not b.acquire()
    assert a.holder().startswith("task-mesh")
    a.release()
    assert b.acquire()
    b.release()


def test_c06_holders_scan(tmp_path):
    proc = tmp_path / "proc"
    (proc / "77/fd").mkdir(parents=True)
    dev = tmp_path / "ttyUSB0"; dev.write_text("")
    os.symlink(str(dev), proc / "77/fd/3")
    (proc / "77/comm").write_text("meshtastic\n")
    assert ownership.holders(str(dev), proc, self_pid=1) == [(77, "meshtastic")]


class FakeCore:
    def __init__(self, path):
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path); self.srv.listen(5)
        self.seen = []
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            req = json.loads(c.makefile().readline())
            self.seen.append(req)
            m = req["method"]
            if m == "session.login":
                res = {"session": "TOKEN123", "username": "op", "role": "operator", "idle_timeout_s": 900,
                       "expires_in_s": 3600}
            elif m == "device.list":
                res = {"devices": [{"id": "dev-1", "class": "lora"}],
                       "assignments": {"mesh.primary": {"device_id": "dev-1", "alias": "Heltec", "connected": True}}}
            else:
                res = {}
            c.sendall(json.dumps({"v": 2, "id": req["id"], "ok": True, "result": res}).encode() + b"\n")
            c.close()


def test_c07_core_client_readonly_and_session(tmp_path):
    path = str(tmp_path / "core.sock")
    fake = FakeCore(path)
    c = core.CoreClient(path)
    with pytest.raises(core.CoreError, match="not-allowed"):
        c.call("device.assign", {"device_id": "dev-1", "logical": "mesh.primary"})
    info = c.login("op", "pw")
    assert "session" not in info and "TOKEN123" not in repr(c)
    assert c.assignment("mesh.primary")["device"]["id"] == "dev-1"
    assert c.assignment("sdr.primary") is None
    assert fake.seen[-1]["session"] == "TOKEN123"
    assert not any(r["method"].startswith("device.assign") for r in fake.seen)
    gate = SessionGate(c)
    assert gate.require("operator") == (True, "")
    assert gate.require("administrator")[0] is False
    ended = []
    gate.listeners.append(ended.append)
    gate.session_ended()
    assert not gate.unlocked and ended == ["session-ended"] and c.token is None


def test_c08_core_socket_fallback():
    have = {"/run/rain/core.sock"}
    assert core.resolve_socket(environ={}, exists=have.__contains__) == "/run/rain/core.sock"
    have.add("/run/task/core.sock")
    assert core.resolve_socket(environ={}, exists=have.__contains__) == "/run/task/core.sock"


def test_c09_aprs_encode_decode_roundtrip():
    src, dst = aprs.parse_callsign("KD2ABC-7"), aprs.parse_callsign("APZTSK")
    info = aprs.message_info("N0CALL-5", "Meet at the trailhead", "A1")
    frame = aprs.encode_ax25(src, dst, [aprs.parse_callsign("WIDE1-1")], info.encode())
    k = aprs.kiss_frame(frame)
    port, payload = aprs.KissDecoder().feed(k)[0]
    p = aprs.parse_aprs(aprs.decode_ax25(payload))
    assert (p.source, p.dest, p.path, p.addressee, p.message) == ("KD2ABC-7", "APZTSK", "WIDE1-1", "N0CALL-5",
                                                                   "Meet at the trailhead")
    assert aprs.message_id_of(p) == "A1"
    ack = aprs.parse_aprs(aprs.decode_ax25(aprs.encode_ax25(dst, src, [], aprs.ack_info("KD2ABC-7", "A1").encode())))
    assert aprs.parse_ack(ack) == ("ack", "A1")
    pos = aprs.parse_aprs(aprs.decode_ax25(aprs.encode_ax25(src, dst, [], aprs.position_info(40.2732, -76.8867).encode())))
    assert pos.kind == "position" and abs(pos.lat - 40.2732) < 0.0002 and abs(pos.lon + 76.8867) < 0.0002
    for bad in ("x" * 68, "pipe|", "tilde~", "brace{", "tab\t"):
        with pytest.raises(ValueError):
            aprs.message_info("KD2ABC", bad)
    with pytest.raises(ValueError):
        aprs.message_info("TOOLONGADDR", "hi")
    with pytest.raises(ValueError):
        aprs.parse_callsign("KD2ABC-16")


def test_c09b_kiss_escaping_roundtrip():
    data = bytes([0x01, 0xC0, 0xDB, 0x7F])
    assert aprs.KissDecoder().feed(aprs.kiss_frame(data, port=2)) == [(2, data)]


def _amateur_ok():
    cfg = txpolicy.AmateurConfig(True, "KD2ABC-7", "I hold amateur licence KD2ABC", "2026-10-12")
    radio = txpolicy.AmateurRadio("ft-test", verified=True, ptt_configured=True)
    req = txpolicy.TxRequest("amateur", "message", True, role="operator", text="hello", addressee="N0CALL",
                             transport="direwolf-agw")
    return cfg, radio, req


def test_c10_amateur_policy():
    pol = txpolicy.TxPolicy(clock=lambda: 0)
    cfg, radio, req = _amateur_ok()
    assert pol.evaluate_amateur(req, cfg, radio).allowed
    for change, code in [(dict(tx_enabled=False), "tx-disabled"), (dict(callsign=""), "no-callsign"),
                         (dict(attestation=""), "no-attestation")]:
        c2 = txpolicy.AmateurConfig(**{**cfg.__dict__, **change})
        assert pol.evaluate_amateur(req, c2, radio).code == code
    assert pol.evaluate_amateur(req, cfg, txpolicy.AmateurRadio("r", verified=False, ptt_configured=True)).code == "radio-unverified"
    assert pol.evaluate_amateur(req, cfg, txpolicy.AmateurRadio("r", verified=True)).code == "no-ptt"
    for change, code in [(dict(user_initiated=False), "not-user-initiated"), (dict(origin="mesh"), "relay-refused"),
                         (dict(role=None), "no-session"), (dict(text="x" * 68), "bad-content")]:
        r2 = txpolicy.TxRequest(**{**req.__dict__, **change})
        assert pol.evaluate_amateur(r2, cfg, radio).code == code
    beacon = txpolicy.TxRequest(**{**req.__dict__, "kind": "beacon", "beacon_interval_s": 300})
    assert pol.evaluate_amateur(beacon, cfg, radio).code == "beacon-interval"
    pol.record_sent(req, channel=0, request_id="m1")
    d = pol.evaluate_amateur(req, cfg, radio)
    assert not d.allowed and d.code == "busy"
    pol.frame_done(0)
    d = pol.evaluate_amateur(req, cfg, radio)
    assert not d.allowed and d.needs_confirmation and d.needs_confirmation[0].startswith("duplicate")
    assert pol.evaluate_amateur(txpolicy.TxRequest(**{**req.__dict__, "confirmed": ("duplicate",)}), cfg, radio).allowed


def test_c11_callsign_formats_never_defaulted():
    assert txpolicy.valid_amateur_callsign("KD2ABC-7") and txpolicy.valid_amateur_callsign("W1AW")
    assert not txpolicy.valid_amateur_callsign("") and not txpolicy.valid_amateur_callsign("NOCALL")
    assert txpolicy.valid_gmrs_callsign("WRAB123") and txpolicy.valid_gmrs_callsign("KAE1234")
    assert not txpolicy.valid_gmrs_callsign("KD2ABC")


def _gmrs_ok():
    cfg = txpolicy.GmrsConfig(True, "WRAB123", "I hold GMRS licence WRAB123", "2026-10-12")
    eq = txpolicy.GmrsEquipment("Simulated GMRS HT", handheld=True, integral_antenna=True, builtin_data=True,
                                software_tx_supported=True, simulated=True)
    req = txpolicy.TxRequest("gmrs", "location", True, role="operator", transport="radio-integrated",
                             channel_mhz=462.5625, duration_s=0.4, recipient_service="gmrs")
    return cfg, eq, req


def test_c12_gmrs_policy_part95():
    t = [0.0]
    pol = txpolicy.TxPolicy(clock=lambda: t[0])
    cfg, eq, req = _gmrs_ok()
    d = pol.evaluate_gmrs(req, cfg, eq)
    assert d.allowed and d.reminders and d.reminders[0].startswith("voice-id")
    R = lambda **kw: txpolicy.TxRequest(**{**req.__dict__, **kw})
    cases = [(R(transport="direwolf-agw"), "gmrs-external-modem"), (R(channel_mhz=467.55), "channel"),
             (R(channel_mhz=462.0), "channel"), (R(duration_s=1.2), "duration"), (R(duration_s=None), "duration"),
             (R(kind="text", text="hi", addressee=""), "no-recipient"), (R(kind="voice"), "bad-kind"),
             (R(recipient_service="amateur"), "amateur-recipient"), (R(user_initiated=False), "not-user-initiated"),
             (R(origin="aprs"), "relay-refused")]
    for r, code in cases:
        assert pol.evaluate_gmrs(r, cfg, eq).code == code, code
    for ch in txpolicy.GMRS_467_MAIN:
        assert not txpolicy.is_gmrs_data_channel(ch)
    assert len(txpolicy.GMRS_DATA_CHANNELS) == 22
    bad_eq = [txpolicy.GmrsEquipment(**{**eq.__dict__, k: False})
              for k in ("handheld", "integral_antenna", "builtin_data", "software_tx_supported")]
    codes = [pol.evaluate_gmrs(req, cfg, e).code for e in bad_eq]
    assert codes == ["not-handheld", "antenna", "no-builtin-data", "driver-no-tx"]
    real_unverified = txpolicy.GmrsEquipment("BTECH GMRS-PRO", handheld=True, integral_antenna=True, builtin_data=True,
                                             software_tx_supported=True)
    assert pol.evaluate_gmrs(req, cfg, real_unverified).code == "driver-unverified"
    assert pol.evaluate_gmrs(req, txpolicy.GmrsConfig(), eq).code == "tx-disabled"  # off by default
    pol.record_sent(req)
    t[0] = 10
    assert pol.evaluate_gmrs(req, cfg, eq).code == "spacing"
    t[0] = 31
    assert pol.evaluate_gmrs(R(kind="text", text="at camp", addressee="unit 4"), cfg, eq).allowed
    auto = R(user_initiated=False, is_auto_reply=True)
    assert pol.evaluate_gmrs(auto, cfg, eq).code == "auto-reply-off"
    pol.voice_id_done()
    assert not pol.evaluate_gmrs(req, cfg, eq).reminders


def test_c13_amateur_and_gmrs_never_cross():
    pol = txpolicy.TxPolicy(clock=lambda: 0)
    acfg, radio, areq = _amateur_ok()
    gcfg, eq, greq = _gmrs_ok()
    assert pol.evaluate_gmrs(areq, gcfg, eq).code == "wrong-service"
    assert pol.evaluate_amateur(greq, acfg, radio).code == "wrong-service"


def test_c14_retry_schedule():
    assert txpolicy.retry_schedule() == [30, 90, 210]
    assert txpolicy.retry_schedule(5) == [30, 90, 210, 330, 450]
    with pytest.raises(ValueError):
        txpolicy.retry_schedule(6)


def test_c15_bridge_refuses_and_source_rules():
    with pytest.raises(PermissionError):
        Bridge().forward("anything")
    for p in PKG.glob("*.py"):
        src = p.read_text()
        assert "shell=True" not in src and "os.system" not in src, p
        assert src.startswith("# SPDX-License-Identifier: GPL-3.0-or-later\n# SPDX-FileCopyrightText: 2026 Joshua Sturtz"), p
    assert "import socket" not in (PKG / "aprs.py").read_text()  # codec opens no sockets
