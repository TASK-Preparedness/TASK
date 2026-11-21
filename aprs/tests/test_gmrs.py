# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""GMRS profile with the SIMULATED driver (nothing transmitted)."""

import json

import pytest

from task_aprs import config, dwconf
from task_aprs.gmrs.driver import DriverCapabilities
from task_aprs.gmrs.simulated import SimulatedGmrsDriver
from task_aprs.service import AprsService
from task_comms.feeds import read_feed
from task_comms.txpolicy import GmrsConfig, TxRequest


class Clock:
    t = 5000.0

    def __call__(self):
        return self.t


def make(tmp_path, drv=None, tx=True, role="operator", call="WRAB123"):
    root = tmp_path / "conf"
    config.save_gmrs(GmrsConfig(tx_enabled=tx, callsign=call, attestation="I hold GMRS licence",
                                attestation_date="2026-10-12"), root)
    config.save_profile(config.RadioProfile(id="sim", service="gmrs", driver="simulated", handheld=True,
                                            integral_antenna=True, builtin_data=True), root)
    clock = Clock()
    drv = drv or SimulatedGmrsDriver()
    drv.open()
    svc = AprsService(session_role=lambda: role, conf_root=root, state_root=tmp_path / "st",
                      dw_conf=dwconf.parse(""), clock=clock, gmrs_driver=drv)
    return svc, drv, clock


def test_default_off(tmp_path):
    assert GmrsConfig().tx_enabled is False and GmrsConfig().auto_reply_location is False
    svc, drv, _ = make(tmp_path, tx=False)
    ok, d = svc.gmrs.send("location", lat=40, lon=-77)
    assert not ok and d.code == "tx-disabled" and drv.sent == []


def test_simulated_tx_location_text_and_spacing(tmp_path):
    svc, drv, clock = make(tmp_path)
    assert "SIMULATION" in svc.gmrs.status()
    ok, d = svc.gmrs.send("location", lat=40.1, lon=-77.2)
    assert ok and any(r.startswith("voice-id") for r in d.reminders)
    ok, d = svc.gmrs.send("text", recipient="UNIT2", text="at camp")
    assert not ok and d.code == "spacing"
    clock.t += 30
    ok, d = svc.gmrs.send("text", recipient="UNIT2", text="at camp")
    assert ok and [s["kind"] for s in drv.sent] == ["location", "text"]
    log = (tmp_path / "st" / "audit-gmrs.jsonl").read_text()
    assert "at camp" not in log and '"simulated": true' in log
    assert not (tmp_path / "st" / "audit-amateur.jsonl").exists() or "gmrs" not in \
        (tmp_path / "st" / "audit-amateur.jsonl").read_text()


def test_text_needs_recipient_and_no_amateur(tmp_path):
    svc, drv, clock = make(tmp_path)
    ok, d = svc.gmrs.send("text", recipient="", text="hi")
    assert not ok and any(r.startswith("no-recipient") for r in d.reasons)
    from task_comms.txpolicy import TxPolicy
    req = TxRequest(service="gmrs", kind="text", user_initiated=True, role="operator", text="hi", addressee="N0X",
                    recipient_service="amateur", transport="radio-integrated", channel_mhz=462.5625, duration_s=0.3)
    d = TxPolicy().evaluate_gmrs(req, svc.gmrs_cfg, None)
    assert any(r.startswith("amateur-recipient") for r in d.reasons)


@pytest.mark.parametrize("mhz,ok", [(462.5625, True), (467.5625, True), (462.5500, True), (467.5500, False),
                                    (446.0, False)])
def test_channel_allow_list(tmp_path, mhz, ok):
    svc, drv, _ = make(tmp_path, SimulatedGmrsDriver(channel_mhz=mhz))
    res, d = svc.gmrs.send("location", lat=1, lon=1)
    assert res is ok
    if not ok:
        assert d.code == "channel"


def test_burst_over_one_second_refused(tmp_path):
    svc, drv, _ = make(tmp_path, SimulatedGmrsDriver(burst_s=1.2))
    ok, d = svc.gmrs.send("location", lat=1, lon=1)
    assert not ok and d.code == "duration"


def test_external_modem_refused(tmp_path):
    from task_comms.txpolicy import TxPolicy
    svc, *_ = make(tmp_path)
    req = TxRequest(service="gmrs", kind="location", user_initiated=True, role="operator",
                    transport="direwolf-agw", channel_mhz=462.5625, duration_s=0.3)
    d = TxPolicy().evaluate_gmrs(req, svc.gmrs_cfg, None)
    assert any(r.startswith("gmrs-external-modem") for r in d.reasons)


def test_unverified_real_driver_blocked(tmp_path):
    class Unverified(SimulatedGmrsDriver):
        def capabilities(self):
            c = super().capabilities()
            c.simulated, c.verified_on_hardware = False, False
            return c
    svc, drv, _ = make(tmp_path, Unverified())
    ok, d = svc.gmrs.send("location", lat=1, lon=1)
    assert not ok and d.code == "driver-unverified" and drv.sent == []
    assert "UNVERIFIED" in svc.gmrs.status()


def test_mobile_or_removable_antenna_refused(tmp_path):
    class Mobile(SimulatedGmrsDriver):
        def capabilities(self):
            c = super().capabilities()
            c.handheld, c.integral_antenna = False, False
            return c
    svc, drv, _ = make(tmp_path, Mobile())
    ok, d = svc.gmrs.send("location", lat=1, lon=1)
    codes = [r.split(":")[0] for r in d.reasons]
    assert not ok and "not-handheld" in codes and "antenna" in codes


def test_auto_reply_off_by_default_and_rx_feed(tmp_path):
    svc, drv, _ = make(tmp_path)
    ok, d = svc.gmrs.send("location", lat=1, lon=1, is_auto_reply=True)
    assert not ok and d.code == "auto-reply-off"
    drv.inject("location", "UNIT9", lat=40.3, lon=-76.9)
    drv.inject("text", "UNIT9", text="hello")
    assert [p.kind for p in svc.gmrs.received] == ["location", "text"]
    _, ents = read_feed(svc.feed.path)
    assert [e["id"] for e in ents] == ["gmrs:UNIT9"]


def test_radio_error_reported(tmp_path):
    svc, drv, _ = make(tmp_path, SimulatedGmrsDriver(fail=True))
    ok, d = svc.gmrs.send("location", lat=1, lon=1)
    assert not ok and d.code == "radio-error"


def test_gmrs_and_amateur_configs_separate(tmp_path):
    svc, *_ = make(tmp_path)
    assert svc.amateur_cfg.callsign == "" and svc.gmrs_cfg.callsign == "WRAB123"
    assert svc.profiles == [] and [p.id for p in svc.gmrs_profiles] == ["sim"]
    assert svc.gmrs_policy is not svc.policy
