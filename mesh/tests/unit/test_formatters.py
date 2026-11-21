# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
import time

from task_mesh.domain.models import NodeRecord, Source
from task_mesh.ui import formatters as f

NOW = 1790000000


def rec(**kw):
    return NodeRecord(1, NOW, NOW, **kw)


def test_dash_for_unknown_everywhere():
    r = rec()
    assert f.text(None) == f.DASH and f.text("") == f.DASH
    assert f.rssi(r)[0] == f.DASH and f.snr(r)[0] == f.DASH and f.hops(r)[0] == f.DASH
    assert f.battery(r)[0] == f.DASH and f.coordinate(None) == f.DASH
    assert f.last_heard(r, NOW)[0] == f.DASH
    assert f.DASH == "\u2014"


def test_zero_values_are_shown_not_dashed():
    r = rec(rssi_last=0, snr=0.0, hops_away=0, hops_source=Source.RADIO_NODEDB, battery_level=0,
            latitude=0.0, longitude=0.0)
    assert f.rssi(r)[0] == "0 dBm" and f.snr(r)[0] == "0.00 dB" and f.hops(r)[0] == "0"
    assert f.battery(r)[0] == "0 %" and f.coordinate(0.0) == "0.00000"
    assert "0,0" in f.position_tooltip(r)


def test_battery_powered():
    d, tip = f.battery(rec(battery_level=101, voltage=4.9))
    assert d == "Powered" and "101" in tip and "4.90 V" in tip


def test_hops_calc_marker():
    d, tip = f.hops(rec(hops_away=2, hops_source=Source.CALCULATED))
    assert d == "2 calc" and "Calculated" in tip
    assert f.hops(rec(hops_away=2, hops_source=Source.RADIO_NODEDB))[0] == "2"


def test_last_heard_sources():
    d, tip = f.last_heard(rec(last_heard_radio=NOW - 120), NOW)
    assert d == time.strftime("%H:%M:%S", time.localtime(NOW - 120)) and "radio clock" in tip and "2 min ago" in tip
    d, tip = f.last_heard(rec(last_rx_local=NOW - 30), NOW)
    assert d != f.DASH and "this computer" in tip
    d, tip = f.last_heard(rec(last_heard_radio=1000), NOW)
    assert d == f.DASH and "implausible" in tip


def test_snr_source_tooltip():
    assert "last packet" in f.snr(rec(snr=1.0, snr_source=Source.PACKET))[1]
    assert "node database" in f.snr(rec(snr=1.0, snr_source=Source.RADIO_NODEDB))[1]


def test_coordinates_five_decimals():
    assert f.coordinate(40.1234567) == "40.12346" and f.coordinate(-105.1234567) == "-105.12346"
